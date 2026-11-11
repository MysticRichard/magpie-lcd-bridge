from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import struct
import tempfile
import time
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from PIL import Image, ImageDraw, ImageFont

WIDTH = 320
HEIGHT = 240
SCALE = 4

DATA_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
IMAGE_BEGIN = 176
IMAGE_DATA = 177
IMAGE_END = 178
FORMAT_RGB565_RAW = 1
FORMAT_RGB565_PACKBITS = 5
FORMAT_RGB565_DELTA_PACKBITS = 6
CHUNK_SIZE = 156
TRANSFER_WINDOW = 12
BLE_WRITE_TIMEOUT = 10.0
BLE_WRITE_CANCEL_TIMEOUT = 2.0
BLE_DISCONNECT_TIMEOUT = 5.0
BLE_CLEANUP_WAIT_TIMEOUT = 5.0

DEFAULT_BASE_URL = "http://127.0.0.1:3425"
DEFAULT_CNY_PER_USD = 6.68

FONT_UI = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_UI_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
FONT_NUMBER = Path(r"C:\Windows\Fonts\segoeuib.ttf")

COLOR_BG = "#F4F4F7"
COLOR_CARD = "#FFFFFF"
COLOR_BORDER = "#DFE0E7"
COLOR_TEXT = "#292A33"
COLOR_TEXT_SOFT = "#565762"
COLOR_TITLE = "#24252D"
COLOR_GREEN = "#17814B"
COLOR_RING = "#51515D"
COLOR_RING_TRACK = "#E5E5E9"
COLOR_LOW = "#D27844"
COLOR_LOW_TRACK = "#F1DFD3"
COLOR_STATUS = "#A34822"

log = logging.getLogger("magpie-lcd")


def refresh_delay(interval: int, failed: bool) -> int:
    if failed:
        return min(10, max(2, interval))
    return max(10, interval)


@dataclass(frozen=True)
class QuotaRing:
    label: str
    remaining: int | None


@dataclass(frozen=True)
class QuotaGroup:
    title: str
    provider: str
    windows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class QuotaDisplayGroup:
    title: str
    rings: tuple[QuotaRing, ...]


DEFAULT_QUOTA_GROUPS = (
    QuotaGroup("Codex", "codex", (("5 hours", "5H"), ("7 days", "7D"))),
    QuotaGroup(
        "OpenCode Go",
        "opencode-go",
        (("5 hours", "5H"), ("7 days", "7D"), ("Month", "本月")),
    ),
)


@dataclass(frozen=True)
class Snapshot:
    tokens_total: int
    cost_cny: float
    has_unpriced: bool
    cache_rate: int | None
    quota_groups: tuple[QuotaDisplayGroup, ...]
    updated_at: datetime


def fetch_json(url: str, timeout: float = 10) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "magpie-lcd-bridge/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _provider(payload: dict, provider_id: str) -> dict | None:
    for item in payload.get("data", []):
        if item.get("provider") == provider_id:
            return item
    return None


def _remaining(provider: dict | None, names: Sequence[str]) -> tuple[int | None, ...]:
    windows = (provider or {}).get("windows", [])
    result: list[int | None] = []
    for name in names:
        match = next((window for window in windows if window.get("name") == name), None)
        value = match.get("remaining") if match else None
        result.append(round(value) if isinstance(value, (int, float)) else None)
    return tuple(result)


def load_quota_config(path: Path | None = None) -> tuple[QuotaGroup, ...]:
    if path is None or not path.exists():
        return DEFAULT_QUOTA_GROUPS
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        groups = []
        for item in payload["quota_groups"]:
            windows = tuple(
                (str(window["name"]), str(window["label"]))
                for window in item.get("windows", [])
            )
            groups.append(QuotaGroup(str(item["title"]), str(item["provider"]), windows))
        if not groups:
            raise ValueError("quota_groups cannot be empty")
        return tuple(groups[:2])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        log.warning("读取额度配置失败，使用默认配置：%s", error)
        return DEFAULT_QUOTA_GROUPS


def load_snapshot(
    base_url: str = DEFAULT_BASE_URL,
    cny_per_usd: float = DEFAULT_CNY_PER_USD,
    quota_groups: Sequence[QuotaGroup] = DEFAULT_QUOTA_GROUPS,
) -> Snapshot:
    base_url = base_url.rstrip("/")
    usage = fetch_json(f"{base_url}/v1/magpie/usage?period=today", timeout=12)
    quotas = fetch_json(f"{base_url}/v1/magpie/quotas", timeout=20)

    input_tokens = int(usage.get("input") or 0)
    output_tokens = int(usage.get("output") or 0)
    cache_read = int(usage.get("cache_read") or 0)
    cache_write = int(usage.get("cache_write") or 0)
    tokens_total = input_tokens + output_tokens + cache_read + cache_write

    cache_base = input_tokens + cache_read + cache_write
    cache_rate = round(cache_read * 100 / cache_base) if cache_base else None
    cost_usd = float(usage.get("cost") or 0)

    resolved_groups = []
    for group in quota_groups[:2]:
        remaining = _remaining(
            _provider(quotas, group.provider),
            tuple(name for name, _ in group.windows),
        )
        resolved_groups.append(
            QuotaDisplayGroup(
                group.title,
                tuple(
                    QuotaRing(label, value)
                    for (_, label), value in zip(group.windows, remaining)
                ),
            )
        )

    return Snapshot(
        tokens_total=tokens_total,
        cost_cny=cost_usd * cny_per_usd,
        has_unpriced=int(usage.get("unpriced") or 0) > 0,
        cache_rate=cache_rate,
        quota_groups=tuple(resolved_groups),
        updated_at=datetime.now().astimezone(),
    )


@lru_cache(maxsize=64)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _font_ui(size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_UI_BOLD if bold else FONT_UI
    if not path.exists():
        raise FileNotFoundError(f"Missing font: {path}")
    return _font(str(path), max(1, round(size * SCALE)))


def _font_number(size: float) -> ImageFont.FreeTypeFont:
    if not FONT_NUMBER.exists():
        raise FileNotFoundError(f"Missing font: {FONT_NUMBER}")
    return _font(str(FONT_NUMBER), max(1, round(size * SCALE)))


def _sx(value: float) -> int:
    return round(value * SCALE)


def _text(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    value: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    anchor: str = "ls",
) -> None:
    draw.text((_sx(x), _sx(y)), value, font=font, fill=fill, anchor=anchor)


def _card(draw: ImageDraw.ImageDraw, x: float, y: float, width: float, height: float) -> None:
    draw.rounded_rectangle(
        (_sx(x), _sx(y), _sx(x + width), _sx(y + height)),
        radius=_sx(10),
        fill=COLOR_CARD,
        outline=COLOR_BORDER,
        width=SCALE,
    )


def _format_tokens(total: int | None) -> tuple[str, str]:
    if total is None:
        return "—", ""
    if total >= 100_000_000:
        return f"{total / 100_000_000:.2f}", "亿"
    if total >= 10_000:
        value = total / 10_000
        return (f"{value:.0f}" if value >= 1000 else f"{value:.1f}"), "万"
    return str(total), ""


def _format_cost(cost: float | None, has_unpriced: bool) -> str:
    if cost is None:
        return "—"
    suffix = "+" if has_unpriced else ""
    return f"≈¥{cost:.2f}{suffix}"


def _fit_cost_font(draw: ImageDraw.ImageDraw, value: str, size: float = 19) -> ImageFont.FreeTypeFont:
    max_width = (232.5 - 4 - 119.5) * SCALE
    while size > 12.5:
        font = _font_number(size)
        if draw.textlength(value, font=font) <= max_width:
            return font
        size -= 0.5
    return _font_number(12.5)


def ring_positions(count: int) -> tuple[int, ...]:
    if count <= 0:
        return ()
    return tuple(282 - 52 * index for index in range(min(count, 3) - 1, -1, -1))


def _draw_ring(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    ring: QuotaRing | None,
) -> None:
    radius = 20
    stroke = 3.5
    missing = ring is None or ring.remaining is None
    value = 0 if missing else max(0, min(100, ring.remaining))
    low = not missing and value < 10
    active = COLOR_LOW if low else COLOR_RING
    track = COLOR_RING_TRACK if missing or not low else COLOR_LOW_TRACK
    box = (_sx(cx - radius), _sx(cy - radius), _sx(cx + radius), _sx(cy + radius))
    line_width = _sx(stroke)

    draw.ellipse(box, outline=track, width=line_width)
    if not missing and value >= 100:
        draw.ellipse(box, outline=active, width=line_width)
    elif not missing and value > 0:
        draw.arc(box, start=-90, end=-90 + 360 * value / 100, fill=active, width=line_width)

    percent = "—" if missing else f"{value}%"
    percent_size = 11.5 if value == 100 and not missing else 14
    _text(
        draw,
        cx,
        cy + 5,
        percent,
        _font_number(percent_size),
        "#6B6C78" if missing else "#25262F",
        "ms",
    )
    _text(draw, cx, cy + 32, ring.label if ring else "", _font_ui(10.5), "#50515D", "ms")


def _draw_quota_card(
    draw: ImageDraw.ImageDraw,
    y: float,
    group: QuotaDisplayGroup | None,
) -> None:
    _card(draw, 10.5, y, 299, 65.5)
    title = group.title if group else "额度"
    rings = group.rings if group else ()
    _text(draw, 21, y + 25.5, title, _font_ui(15.5, bold=True), COLOR_TEXT)
    _text(draw, 21, y + 43.5, "剩余额度", _font_ui(11.5), COLOR_TEXT_SOFT)
    for cx, ring in zip(ring_positions(len(rings)), rings):
        _draw_ring(draw, cx, y + 27, ring)


def render_dashboard(snapshot: Snapshot | None, state: str, now: datetime) -> Image.Image:
    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), COLOR_BG)
    draw = ImageDraw.Draw(image)

    status = {
        "normal": ("用量与额度", COLOR_TEXT_SOFT),
        "stale": ("数据已过期", COLOR_STATUS),
        "unavailable": ("暂未读到 Magpie", COLOR_STATUS),
    }[state]

    _text(draw, 11, 22, "magpie", _font_number(17), COLOR_TEXT, "ls")
    _text(draw, 78, 21, status[0], _font_ui(12), status[1], "ls")
    _text(draw, 309, 22, now.strftime("%H:%M"), _font_number(17), "#30313A", "rs")

    _card(draw, 10.5, 32, 299, 55)
    draw.line((_sx(107.5), _sx(43), _sx(107.5), _sx(79)), fill="#E7E8ED", width=SCALE)
    draw.line((_sx(232.5), _sx(43), _sx(232.5), _sx(79)), fill="#E7E8ED", width=SCALE)

    token_value, token_unit = _format_tokens(snapshot.tokens_total if snapshot else None)
    cost_value = _format_cost(snapshot.cost_cny if snapshot else None, snapshot.has_unpriced if snapshot else False)
    cache_value = f"{snapshot.cache_rate}%" if snapshot and snapshot.cache_rate is not None else "—"

    _text(draw, 20, 49, "今日 Token", _font_ui(12), COLOR_TEXT_SOFT)
    token_font = _font_number(29)
    _text(draw, 21, 77, token_value, token_font, COLOR_TITLE)
    token_width = draw.textlength(token_value, font=token_font) / SCALE
    if token_unit:
        _text(draw, 21 + token_width + 4, 76, token_unit, _font_ui(15.5), "#424450")

    _text(draw, 119.5, 49, "参考费用", _font_ui(12), COLOR_TEXT_SOFT)
    _text(draw, 119.5, 76, cost_value, _fit_cost_font(draw, cost_value), COLOR_GREEN if snapshot else "#777987")

    _text(draw, 244.5, 49, "缓存命中率", _font_ui(11), COLOR_TEXT_SOFT)
    _text(draw, 244.5, 77, cache_value, _font_number(27), COLOR_TITLE)

    groups = snapshot.quota_groups if snapshot else ()
    _draw_quota_card(draw, 94.5, groups[0] if len(groups) > 0 else None)
    _draw_quota_card(draw, 167.5, groups[1] if len(groups) > 1 else None)

    return image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def rgb565_bytes(image: Image.Image) -> bytes:
    output = bytearray(WIDTH * HEIGHT * 2)
    offset = 0
    pixels = image.convert("RGB").tobytes()
    for index in range(0, len(pixels), 3):
        red, green, blue = pixels[index : index + 3]
        color = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
        output[offset] = color >> 8
        output[offset + 1] = color & 0xFF
        offset += 2
    return bytes(output)


def pack_bits(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(data):
        run = 1
        while index + run < len(data) and data[index + run] == data[index] and run < 128:
            run += 1
        if run >= 3:
            output.extend((0x80 | (run - 1), data[index]))
            index += run
            continue

        start = index
        index += run
        while index < len(data) and index - start < 128:
            run = 1
            while index + run < len(data) and data[index + run] == data[index] and run < 128:
                run += 1
            if run >= 3:
                break
            index += min(run, 128 - (index - start))
        output.append(index - start - 1)
        output.extend(data[start:index])
    return bytes(output)


def row_delta(data: bytes, stride: int) -> bytes:
    output = bytearray(len(data))
    for index, value in enumerate(data):
        previous = 0 if index % stride == 0 else data[index - 1]
        output[index] = (value - previous) & 0xFF
    return bytes(output)


def image_payload(image: Image.Image) -> tuple[int, bytes]:
    raw = rgb565_bytes(image)
    packed = pack_bits(raw)
    delta = pack_bits(row_delta(raw, 2))
    candidates = (
        (len(raw), FORMAT_RGB565_RAW, raw),
        (len(packed), FORMAT_RGB565_PACKBITS, packed),
        (len(delta), FORMAT_RGB565_DELTA_PACKBITS, delta),
    )
    _, format_id, payload = min(candidates, key=lambda item: item[0])
    return format_id, payload


def iter_image_packets(payload: bytes, format_id: int, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    if format_id not in (FORMAT_RGB565_RAW, FORMAT_RGB565_PACKBITS, FORMAT_RGB565_DELTA_PACKBITS):
        raise ValueError(f"Unsupported format: {format_id}")
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    bytes_per_pixel = 1 if format_id in (FORMAT_RGB565_RAW, FORMAT_RGB565_PACKBITS, FORMAT_RGB565_DELTA_PACKBITS) else 0
    begin = bytearray(20)
    begin[:2] = bytes((IMAGE_BEGIN, 1))
    struct.pack_into("<HHBBII", begin, 2, WIDTH, HEIGHT, format_id, bytes_per_pixel, len(payload), crc)
    yield bytes(begin)

    sequence = 0
    for offset in range(0, len(payload), chunk_size):
        part = payload[offset : offset + chunk_size]
        yield bytes((IMAGE_DATA, sequence & 0xFF, (sequence >> 8) & 0xFF)) + part
        sequence = (sequence + 1) & 0xFFFF

    yield bytes((IMAGE_END,)) + struct.pack("<IH", crc, sequence)


def iter_image_writes(
    payload: bytes,
    format_id: int,
    chunk_size: int = CHUNK_SIZE,
    window: int = TRANSFER_WINDOW,
) -> Iterator[tuple[bytes, bool]]:
    data_count = math.ceil(len(payload) / chunk_size)
    data_index = 0
    for packet in iter_image_packets(payload, format_id, chunk_size):
        response = packet[0] != IMAGE_DATA
        if packet[0] == IMAGE_DATA:
            data_index += 1
            response = data_index % window == 0 or data_index == data_count
        yield packet, response


async def scan_devices(timeout: float = 5.0) -> list[tuple[str, Any]]:
    from bleak import BleakScanner

    result = await BleakScanner.discover(timeout=timeout, return_adv=True)
    matches: list[tuple[str, Any]] = []
    if isinstance(result, dict):
        entries = result.values()
    else:
        entries = ((device, None) for device in result)
    for device, advertisement in entries:
        name = getattr(device, "name", None) or getattr(advertisement, "local_name", None) or ""
        if name.startswith("DA-LCD-"):
            matches.append((name, device))
    return sorted(matches, key=lambda item: (item[0], item[1].address))


class LcdBle:
    def __init__(self, address: str | None = None, write_timeout: float = BLE_WRITE_TIMEOUT) -> None:
        self.address = address
        self.write_timeout = write_timeout
        self.client = None
        self.data_char = None
        self._pending_write: asyncio.Task | None = None
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._generation = 0

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected and self.data_char)

    def _on_disconnect(self, generation: int, client) -> None:
        if generation != self._generation or client is not self.client:
            log.debug("忽略旧 BLE 连接的断线回调")
            return
        self.data_char = None
        log.warning("BLE 连接已断开")

    def _track_cleanup(self, task: asyncio.Task) -> None:
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_done)

    def _cleanup_done(self, task: asyncio.Task) -> None:
        self._cleanup_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _wait_for_cleanup(self) -> None:
        if not self._cleanup_tasks:
            return
        _, pending = await asyncio.wait(
            self._cleanup_tasks, timeout=BLE_CLEANUP_WAIT_TIMEOUT
        )
        if pending:
            raise RuntimeError("上一轮 BLE 连接清理尚未完成")

    async def connect(self) -> None:
        from bleak import BleakClient

        if self.client is not None:
            await self.close()
        await self._wait_for_cleanup()

        devices = await scan_devices()
        if not devices:
            raise RuntimeError("未发现 DA-LCD-XXXX 设备；确认屏幕已上电且未被 DA LCD Studio 占用")
        if self.address:
            matches = [
                (name, device)
                for name, device in devices
                if device.address.casefold() == self.address.casefold()
            ]
            if not matches:
                raise RuntimeError(f"未发现指定 DA-LCD 设备 {self.address}")
        else:
            matches = devices
        if len(matches) > 1:
            names = ", ".join(f"{name} ({device.address})" for name, device in matches)
            raise RuntimeError(f"发现多台 DA-LCD，请用 --address 指定：{names}")

        name, device = matches[0]
        self.address = device.address
        self._generation += 1
        generation = self._generation

        self.client = BleakClient(
            device,
            disconnected_callback=lambda client: self._on_disconnect(generation, client),
            timeout=20,
            winrt={"use_cached_services": False},
        )
        await self.client.connect()
        services = self.client.services
        if services is None:
            await self.client.get_services()
            services = self.client.services
        for service in services or ():
            for characteristic in service.characteristics:
                if str(characteristic.uuid).lower() == DATA_UUID:
                    self.data_char = characteristic
                    break
            if self.data_char:
                break
        if not self.data_char:
            await self.close()
            raise RuntimeError("已连接，但没有发现 FF01 图片特征")
        log.info("已连接 %s (%s)，图片特征 FF01 可用", name, device.address)

    async def send_image(self, image: Image.Image) -> tuple[int, int]:
        if not self.connected:
            raise RuntimeError("蓝牙设备未连接")
        format_id, payload = image_payload(image)
        count = 0
        started = time.monotonic()
        total = math.ceil(len(payload) / CHUNK_SIZE) + 2
        for index, (packet, response) in enumerate(iter_image_writes(payload, format_id), 1):
            operation = asyncio.create_task(
                self.client.write_gatt_char(self.data_char, packet, response=response)
            )
            self._pending_write = operation
            try:
                await asyncio.wait_for(asyncio.shield(operation), timeout=self.write_timeout)
            except asyncio.TimeoutError:
                phase = {IMAGE_BEGIN: "起始包", IMAGE_DATA: "数据包", IMAGE_END: "结束包"}.get(
                    packet[0], f"命令 {packet[0]}"
                )
                log.error(
                    "BLE 写入超时：%s %d/%d，响应=%s，超时 %.1f 秒",
                    phase,
                    index,
                    total,
                    response,
                    self.write_timeout,
                )
                raise
            except Exception as error:
                phase = {IMAGE_BEGIN: "起始包", IMAGE_DATA: "数据包", IMAGE_END: "结束包"}.get(
                    packet[0], f"命令 {packet[0]}"
                )
                log.error(
                    "BLE 写入失败：%s %d/%d，响应=%s，异常 %s: %r",
                    phase,
                    index,
                    total,
                    response,
                    type(error).__name__,
                    error,
                )
                raise
            finally:
                if operation.done():
                    self._pending_write = None
            count += 1
        elapsed = time.monotonic() - started
        log.info(
            "图片已发送：格式 %d，数据 %d 字节，%d 包，%.1f 秒",
            format_id,
            len(payload),
            count,
            elapsed,
        )
        return format_id, len(payload)

    async def close(self) -> None:
        self._generation += 1
        client = self.client
        pending = self._pending_write
        self.client = None
        self.data_char = None
        self._pending_write = None

        if pending and not pending.done():
            pending.cancel()
            _, unfinished = await asyncio.wait(
                {pending}, timeout=BLE_WRITE_CANCEL_TIMEOUT
            )
            if unfinished:
                log.warning("BLE 写入取消未完成，转入后台清理")
                self._track_cleanup(pending)

        if client and client.is_connected:
            disconnect_task = asyncio.create_task(client.disconnect())
            done, _ = await asyncio.wait(
                {disconnect_task}, timeout=BLE_DISCONNECT_TIMEOUT
            )
            if disconnect_task in done:
                try:
                    disconnect_task.result()
                except (asyncio.CancelledError, Exception) as error:
                    log.warning("释放 BLE 连接失败：%s: %r", type(error).__name__, error)
            else:
                log.warning(
                    "释放 BLE 连接超时 %.1f 秒，转入后台清理",
                    BLE_DISCONNECT_TIMEOUT,
                )
                disconnect_task.cancel()
                self._track_cleanup(disconnect_task)


def save_preview(image: Image.Image, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{output.stem}.",
        suffix=".png",
        dir=output.parent,
    )
    os.close(fd)
    try:
        image.save(temp_name, format="PNG")
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Magpie 用量与额度 320x240 BLE 液晶屏桥接")
    parser.add_argument("--base-url", default=os.environ.get("MAGPIE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--rate",
        type=float,
        default=float(os.environ.get("MAGPIE_CNY_PER_USD", DEFAULT_CNY_PER_USD)),
        help="USD to CNY rate used for the approximate cost",
    )
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("last-frame.png"))
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(
            os.environ.get(
                "MAGPIE_LCD_LOG",
                str(Path(__file__).with_name("logs") / "magpie-lcd.log"),
            )
        ),
        help="path for background diagnostics",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(
            os.environ.get(
                "MAGPIE_LCD_CONFIG",
                str(Path(__file__).with_name("config.json")),
            )
        ),
        help="JSON file defining the two quota groups and their windows",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("render", help="render a local preview without BLE")
    subparsers.add_parser("scan", help="scan for DA-LCD devices")

    for name, description in (
        ("push", "render and send one frame"),
        ("run", "keep data and the LCD updated"),
    ):
        command = subparsers.add_parser(name, help=description)
        command.add_argument("--address", help="DA-LCD BLE address; auto-scan when omitted")
        if name == "run":
            command.add_argument("--interval", type=int, default=60, help="seconds between refreshes")
    return parser


async def read_snapshot(args: argparse.Namespace) -> Snapshot:
    groups = load_quota_config(args.config)
    return await asyncio.to_thread(load_snapshot, args.base_url, args.rate, groups)


async def async_main(args: argparse.Namespace) -> int:
    if args.command == "scan":
        devices = await scan_devices()
        if not devices:
            print("未发现 DA-LCD 设备")
            return 1
        for name, device in devices:
            print(f"{name}\t{device.address}")
        return 0

    if args.command == "render":
        snapshot = load_snapshot(args.base_url, args.rate, load_quota_config(args.config))
        image = render_dashboard(snapshot, "normal", datetime.now().astimezone())
        save_preview(image, args.output)
        print(f"已生成 {args.output}；今日 Token {snapshot.tokens_total}，费用 {snapshot.cost_cny:.2f} CNY")
        return 0

    ble = LcdBle(args.address)
    last: Snapshot | None = None
    try:
        if args.command == "push":
            try:
                last = await read_snapshot(args)
                state = "normal"
            except Exception as error:
                log.error("读取 Magpie 失败：%s", error)
                state = "unavailable"
            image = render_dashboard(last, state, datetime.now().astimezone())
            save_preview(image, args.output)
            await ble.connect()
            await ble.send_image(image)
            return 0

        while True:
            now = datetime.now().astimezone()
            try:
                last = await read_snapshot(args)
                state = "normal"
            except Exception as error:
                log.error("读取 Magpie 失败：%s", error)
                state = "stale" if last else "unavailable"

            image = render_dashboard(last, state, now)
            save_preview(image, args.output)
            try:
                if not ble.connected:
                    await ble.connect()
                await ble.send_image(image)
                failed = False
            except Exception as error:
                log.error("BLE 更新失败：%s: %r", type(error).__name__, error)
                await ble.close()
                failed = True
            await asyncio.sleep(refresh_delay(args.interval, failed))
    finally:
        await ble.close()


def main() -> int:
    args = build_parser().parse_args()
    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(args.log_file, encoding="utf-8"),
        ],
    )
    log.info("桥接程序启动：%s", args.command)
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        log.error("执行失败：%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
