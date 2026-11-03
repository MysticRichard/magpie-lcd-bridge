import asyncio
import struct
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from magpie_lcd import (
    DATA_UUID,
    FORMAT_RGB565_DELTA_PACKBITS,
    FORMAT_RGB565_PACKBITS,
    FORMAT_RGB565_RAW,
    HEIGHT,
    LcdBle,
    SCALE,
    WIDTH,
    QuotaDisplayGroup,
    QuotaGroup,
    QuotaRing,
    Snapshot,
    _fit_cost_font,
    _format_tokens,
    image_payload,
    iter_image_packets,
    iter_image_writes,
    load_quota_config,
    load_snapshot,
    pack_bits,
    read_snapshot,
    ring_positions,
    render_dashboard,
    refresh_delay,
    row_delta,
)


def unpack_bits(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(data):
        control = data[index]
        index += 1
        if control < 128:
            length = control + 1
            output.extend(data[index : index + length])
            index += length
        else:
            length = (control & 0x7F) + 1
            output.extend([data[index]] * length)
            index += 1
    return bytes(output)


class ProtocolTests(unittest.TestCase):
    def test_failed_refresh_retries_quickly(self) -> None:
        self.assertEqual(refresh_delay(60, True), 10)
        self.assertEqual(refresh_delay(60, False), 60)

    def test_pack_bits_round_trip(self) -> None:
        data = bytes(range(256)) + b"\xff" * 300 + b"ABCABCABC"
        self.assertEqual(unpack_bits(pack_bits(data)), data)

    def test_row_delta_round_trip(self) -> None:
        data = bytes((index * 17) & 0xFF for index in range(100))
        delta = row_delta(data, 2)
        restored = bytearray(len(data))
        for index, value in enumerate(delta):
            previous = 0 if index % 2 == 0 else restored[index - 1]
            restored[index] = (previous + value) & 0xFF
        self.assertEqual(bytes(restored), data)

    def test_packet_headers_and_sequence(self) -> None:
        payload = bytes(range(200))
        packets = list(iter_image_packets(payload, FORMAT_RGB565_PACKBITS, chunk_size=80))
        self.assertEqual(packets[0][:2], bytes((176, 1)))
        self.assertEqual(len(packets[0]), 20)
        self.assertEqual(packets[0][16:], b"\0" * 4)
        width, height, format_id, bpp, length, _ = struct.unpack("<HHBBII", packets[0][2:16])
        self.assertEqual((width, height, format_id, bpp, length), (320, 240, 5, 1, 200))
        self.assertEqual(len(packets), 5)
        self.assertEqual(packets[1][:3], bytes((177, 0, 0)))
        self.assertEqual(packets[2][:3], bytes((177, 1, 0)))
        self.assertEqual(packets[3][:3], bytes((177, 2, 0)))
        self.assertEqual(packets[-1][0], 178)

    def test_data_writes_are_confirmed_every_twelve_packets(self) -> None:
        writes = list(iter_image_writes(bytes(range(100)), FORMAT_RGB565_PACKBITS, chunk_size=20, window=4))
        self.assertEqual(writes[0][1], True)
        self.assertEqual([response for packet, response in writes if packet[0] == 177], [False, False, False, True, True])
        self.assertEqual(writes[-1][1], True)

    def test_render_and_encoding(self) -> None:
        snapshot = Snapshot(
            tokens_total=56_160_000,
            cost_cny=18.46,
            has_unpriced=True,
            cache_rate=95,
            quota_groups=(
                QuotaDisplayGroup("Codex", (QuotaRing("5H", 69), QuotaRing("7D", 22))),
                QuotaDisplayGroup(
                    "OpenCode Go",
                    (QuotaRing("5H", 100), QuotaRing("7D", 4), QuotaRing("本月", 52)),
                ),
            ),
            updated_at=datetime.now().astimezone(),
        )
        image = render_dashboard(snapshot, "normal", datetime(2026, 10, 31, 9, 40))
        self.assertEqual(image.size, (WIDTH, HEIGHT))
        format_id, payload = image_payload(image)
        self.assertIn(format_id, (FORMAT_RGB565_RAW, FORMAT_RGB565_PACKBITS, FORMAT_RGB565_DELTA_PACKBITS))
        self.assertLess(len(payload), WIDTH * HEIGHT * 2)

    def test_display_formatters(self) -> None:
        self.assertEqual(_format_tokens(56_160_000), ("5616", "万"))
        self.assertEqual(_format_tokens(123_456_789), ("1.23", "亿"))
        self.assertEqual(_format_tokens(999), ("999", ""))

    def test_load_snapshot_maps_usage_and_quota_windows(self) -> None:
        usage = {
            "input": 2_000_000,
            "output": 500_000,
            "cache_read": 7_000_000,
            "cache_write": 0,
            "cost": 2.0,
            "unpriced": 3,
        }
        quotas = {
            "data": [
                {"provider": "codex", "windows": [{"name": "5 hours", "remaining": 64}, {"name": "7 days", "remaining": 21}]},
                {
                    "provider": "opencode-go",
                    "windows": [
                        {"name": "5 hours", "remaining": 99},
                        {"name": "7 days", "remaining": 4},
                        {"name": "Month", "remaining": 52},
                    ],
                },
            ]
        }
        with patch("magpie_lcd.fetch_json", side_effect=(usage, quotas)):
            snapshot = load_snapshot(cny_per_usd=6.5)

        self.assertEqual(snapshot.tokens_total, 9_500_000)
        self.assertEqual(snapshot.cache_rate, 78)
        self.assertEqual(snapshot.cost_cny, 13.0)
        self.assertTrue(snapshot.has_unpriced)
        self.assertEqual([ring.remaining for ring in snapshot.quota_groups[0].rings], [64, 21])
        self.assertEqual([ring.remaining for ring in snapshot.quota_groups[1].rings], [99, 4, 52])

    def test_quota_groups_and_ring_positions_are_configurable(self) -> None:
        config = {
            "quota_groups": [
                {
                    "provider": "custom-provider",
                    "title": "Custom",
                    "windows": [
                        {"name": "short", "label": "短"},
                    ],
                }
            ]
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(__import__("json").dumps(config), encoding="utf-8")
            groups = load_quota_config(path)

        self.assertEqual(groups, (QuotaGroup("Custom", "custom-provider", (("short", "短"),)),))
        self.assertEqual(ring_positions(1), (282,))
        self.assertEqual(ring_positions(2), (230, 282))
        self.assertEqual(ring_positions(3), (178, 230, 282))

    def test_three_digit_cost_fits_its_column(self) -> None:
        image = render_dashboard(None, "unavailable", datetime(2026, 10, 31, 9, 40))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(image)
        value = "≈¥123.45+"
        font = _fit_cost_font(draw, value)
        self.assertLessEqual(draw.textlength(value, font=font), (232.5 - 4 - 119.5) * SCALE)


class HangingClient:
    def __init__(self):
        self.is_connected = True

    async def write_gatt_char(self, *_args, **_kwargs):
        await asyncio.Future()

    async def disconnect(self):
        self.is_connected = False


class DisconnectableHangingClient(HangingClient):
    pass


class OrderedCleanupClient:
    def __init__(self) -> None:
        self.is_connected = True
        self.write_cancelled = asyncio.Event()
        self.disconnect_after_write_cancel = False

    async def write_gatt_char(self, *_args, **_kwargs) -> None:
        try:
            await asyncio.Future()
        finally:
            self.write_cancelled.set()

    async def disconnect(self) -> None:
        self.disconnect_after_write_cancel = self.write_cancelled.is_set()
        self.is_connected = False


class SlowDisconnectClient:
    def __init__(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        await asyncio.sleep(10)


class FakeDevice:
    def __init__(self, name: str, address: str) -> None:
        self.name = name
        self.address = address


class FakeCharacteristic:
    uuid = DATA_UUID


class FakeService:
    characteristics = (FakeCharacteristic(),)


class FakeBleakClient:
    instances = []

    def __init__(self, address_or_device, disconnected_callback, **_kwargs) -> None:
        self.address_or_device = address_or_device
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.services = (FakeService(),)
        self.instances.append(self)

    async def connect(self) -> None:
        self.is_connected = True

    async def get_services(self) -> None:
        return None

    async def disconnect(self) -> None:
        self.is_connected = False


class BleTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_uses_scanned_device_object(self) -> None:
        device = FakeDevice("DA-LCD-772D", "AA:BB:CC:DD:EE:FF")
        FakeBleakClient.instances.clear()
        ble = LcdBle()
        with (
            patch("magpie_lcd.scan_devices", new=AsyncMock(return_value=[("DA-LCD-772D", device)])),
            patch("bleak.BleakClient", FakeBleakClient),
        ):
            await ble.connect()
            self.assertIs(FakeBleakClient.instances[0].address_or_device, device)
            self.assertEqual(ble.address, device.address)
            await ble.close()

    async def test_connect_filters_scan_results_by_address(self) -> None:
        first = FakeDevice("DA-LCD-FIRST", "00:00:00:00:00:01")
        second = FakeDevice("DA-LCD-SECOND", "00:00:00:00:00:02")
        FakeBleakClient.instances.clear()
        ble = LcdBle(address=second.address.lower())
        with (
            patch(
                "magpie_lcd.scan_devices",
                new=AsyncMock(return_value=[("DA-LCD-FIRST", first), ("DA-LCD-SECOND", second)]),
            ),
            patch("bleak.BleakClient", FakeBleakClient),
        ):
            await ble.connect()
            self.assertIs(FakeBleakClient.instances[0].address_or_device, second)
            await ble.close()

    async def test_stale_disconnect_callback_does_not_clear_new_connection(self) -> None:
        ble = LcdBle()
        current_client = object()
        ble.client = current_client
        ble.data_char = object()
        ble._generation = 2

        ble._on_disconnect(1, object())
        self.assertIsNotNone(ble.data_char)

        ble._on_disconnect(2, current_client)
        self.assertIsNone(ble.data_char)

    async def test_close_cancels_pending_write_before_disconnect(self) -> None:
        ble = LcdBle()
        client = OrderedCleanupClient()
        ble.client = client
        ble.data_char = object()
        ble._pending_write = asyncio.create_task(client.write_gatt_char())
        await asyncio.sleep(0)

        await ble.close()

        self.assertTrue(client.disconnect_after_write_cancel)

    async def test_close_bounds_hanging_disconnect(self) -> None:
        ble = LcdBle()
        ble.client = SlowDisconnectClient()
        ble.data_char = object()

        with patch("magpie_lcd.BLE_DISCONNECT_TIMEOUT", 0.01):
            started = asyncio.get_running_loop().time()
            await ble.close()
            elapsed = asyncio.get_running_loop().time() - started

        self.assertLess(elapsed, 0.5)
        self.assertTrue(ble._cleanup_tasks)
        for task in tuple(ble._cleanup_tasks):
            task.cancel()
        await asyncio.gather(*ble._cleanup_tasks, return_exceptions=True)

    async def test_connect_waits_for_incomplete_cleanup(self) -> None:
        ble = LcdBle()
        cleanup = asyncio.create_task(asyncio.Event().wait())
        ble._track_cleanup(cleanup)

        with (
            patch("magpie_lcd.BLE_CLEANUP_WAIT_TIMEOUT", 0.01),
            patch("magpie_lcd.scan_devices", new=AsyncMock()) as scan,
            self.assertRaisesRegex(RuntimeError, "上一轮 BLE 连接清理尚未完成"),
        ):
            await ble.connect()

        scan.assert_not_awaited()
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)

    async def test_snapshot_read_is_offloaded_from_event_loop(self) -> None:
        args = SimpleNamespace(base_url="http://example.test", rate=6.5, config=Path("missing.json"))
        expected = object()
        with (
            patch("magpie_lcd.load_quota_config", return_value=()),
            patch("magpie_lcd.asyncio.to_thread", new=AsyncMock(return_value=expected)) as offload,
        ):
            result = await read_snapshot(args)

        self.assertIs(result, expected)
        offload.assert_awaited_once_with(load_snapshot, args.base_url, args.rate, ())

    async def test_gatt_write_timeout_prevents_run_from_hanging(self) -> None:
        from PIL import Image

        ble = LcdBle(write_timeout=0.01)
        ble.client = HangingClient()
        ble.data_char = object()
        with patch("magpie_lcd.image_payload", return_value=(FORMAT_RGB565_RAW, b"payload")):
            with patch("magpie_lcd.iter_image_writes", return_value=((b"packet", True),)):
                with self.assertRaises(asyncio.TimeoutError):
                    await ble.send_image(Image.new("RGB", (1, 1)))
        await ble.close()

    async def test_gatt_timeout_keeps_write_until_connection_cleanup(self) -> None:
        from PIL import Image

        ble = LcdBle(write_timeout=0.01)
        ble.client = DisconnectableHangingClient()
        ble.data_char = object()
        with patch("magpie_lcd.image_payload", return_value=(FORMAT_RGB565_RAW, b"payload")):
            with patch("magpie_lcd.iter_image_writes", return_value=((b"packet", True),)):
                with self.assertRaises(asyncio.TimeoutError):
                    await ble.send_image(Image.new("RGB", (1, 1)))

        self.assertIsNotNone(ble._pending_write)
        self.assertFalse(ble._pending_write.cancelled())
        await ble.close()
        self.assertIsNone(ble._pending_write)


if __name__ == "__main__":
    unittest.main()
