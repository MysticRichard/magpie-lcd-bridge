import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ble_lease
import magpie_lcd_control as control


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


class ControllerSettingsTests(unittest.TestCase):
    def test_defaults_and_round_trip(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(control.Settings.load(path), control.Settings())

            settings = control.Settings(120, True, False)
            settings.save(path)

            self.assertEqual(control.Settings.load(path), settings)

    def test_interval_is_bounded(self) -> None:
        self.assertEqual(control.normalize_interval("60"), 60)
        with self.assertRaisesRegex(ValueError, "30-3600"):
            control.normalize_interval(29)
        with self.assertRaisesRegex(ValueError, "30-3600"):
            control.normalize_interval(3601)
        with self.assertRaisesRegex(ValueError, "整数"):
            control.normalize_interval("abc")

    def test_invalid_saved_values_fall_back_to_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"interval_seconds": 1}', encoding="utf-8")
            self.assertEqual(control.Settings.load(path), control.Settings())

    def test_worker_command_targets_existing_worker_cli(self) -> None:
        command = control.build_worker_command(90)
        self.assertEqual(Path(command[1]), control.WORKER_SCRIPT)
        self.assertEqual(command[-2:], ["--interval", "90"])
        self.assertIn("run", command)
        self.assertEqual(command[command.index("run") + 1 :], ["--interval", "90"])


class WorkerProcessTests(unittest.TestCase):
    def test_start_stop_and_restart(self) -> None:
        created = []

        def popen_factory(command, **kwargs):
            process = FakeProcess()
            created.append((command, kwargs, process))
            return process

        worker = control.WorkerProcess(
            command_factory=lambda interval: ["worker", "--interval", str(interval)],
            popen_factory=popen_factory,
            terminate_factory=lambda process: process.terminate(),
        )

        self.assertTrue(worker.start(60))
        self.assertTrue(worker.is_running())
        self.assertFalse(worker.start(60))
        self.assertEqual(created[0][0], ["worker", "--interval", "60"])

        worker.stop()
        self.assertTrue(created[0][2].terminated)
        self.assertFalse(worker.is_running())

        self.assertTrue(worker.restart(120))
        self.assertEqual(created[1][0], ["worker", "--interval", "120"])
        self.assertFalse(created[1][2].terminated)

    def test_stop_escalates_when_worker_does_not_exit(self) -> None:
        class StubbornProcess(FakeProcess):
            def wait(self, timeout=None):
                if not self.killed:
                    raise subprocess.TimeoutExpired("worker", timeout or 0)
                return self.returncode

        created = []

        def popen_factory(command, **kwargs):
            process = StubbornProcess()
            created.append(process)
            return process

        worker = control.WorkerProcess(
            command_factory=lambda interval: ["worker", "--interval", str(interval)],
            popen_factory=popen_factory,
            terminate_factory=lambda process: process.terminate(),
        )
        worker.start(60)
        worker.stop()
        self.assertTrue(created[0].killed)


class SettingsRequestTests(unittest.TestCase):
    def test_request_file_is_consumed_once(self) -> None:
        with TemporaryDirectory() as directory:
            request = Path(directory) / "show-settings.request"
            with patch.object(control, "SHOW_SETTINGS_REQUEST", request):
                self.assertFalse(control.consume_settings_request())
                control.request_settings()
                self.assertTrue(request.exists())
                self.assertTrue(control.consume_settings_request())
                self.assertFalse(request.exists())


class WorkerLogTests(unittest.TestCase):
    def test_recent_worker_state_respects_worker_start_time(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "magpie-lcd.log"
            path.write_text(
                "\n".join(
                    (
                        "2026-11-05 12:00:00,000 INFO 图片已发送：格式 5",
                        "2026-11-05 12:01:00,000 ERROR BLE 更新失败：TimeoutError",
                    )
                ),
                encoding="utf-8",
            )
            with patch.object(control, "WORKER_LOG_PATH", path):
                self.assertEqual(
                    control.recent_worker_state(datetime(2026, 11, 5, 12, 0, 30)),
                    ("reconnecting", "12:01:00"),
                )
                self.assertEqual(
                    control.recent_worker_state(datetime(2026, 11, 5, 12, 1, 30)),
                    ("unknown", None),
                )


class FakeLeaseWorker:
    def __init__(self, running: bool) -> None:
        self.running = running
        self.stops = 0
        self.starts = []

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> bool:
        self.stops += 1
        self.running = False
        return True

    def start(self, interval: int) -> bool:
        self.starts.append(interval)
        self.running = True
        return True

    def restart(self, interval: int) -> bool:
        self.stop()
        return self.start(interval)


class BleLeaseManagerTests(unittest.TestCase):
    def make_manager(
        self, *, running: bool = True, now: float = 0.0
    ) -> tuple[ble_lease.BleLeaseManager, FakeLeaseWorker, list[float]]:
        worker = FakeLeaseWorker(running)
        clock_value = [now]
        manager = ble_lease.BleLeaseManager(
            worker,
            control.threading.RLock(),
            interval_getter=lambda: 60,
            clock=lambda: clock_value[0],
            token_factory=lambda: "token-test",
            release_wait=0,
        )
        return manager, worker, clock_value

    def test_acquire_stops_running_worker_and_release_resumes_it(self) -> None:
        manager, worker, _ = self.make_manager()

        granted = manager.acquire("inkmemo", 120)

        self.assertTrue(granted["ok"])
        self.assertEqual(granted["state"], "granted")
        self.assertEqual(granted["token"], "token-test")
        self.assertFalse(worker.is_running())
        self.assertEqual(worker.stops, 1)

        released = manager.release("token-test")

        self.assertTrue(released["ok"])
        self.assertEqual(worker.starts, [60])
        self.assertTrue(worker.is_running())

    def test_release_does_not_start_a_worker_that_was_already_stopped(self) -> None:
        manager, worker, _ = self.make_manager(running=False)

        manager.acquire("inkmemo", 120)
        manager.release("token-test")

        self.assertEqual(worker.stops, 0)
        self.assertEqual(worker.starts, [])

    def test_second_owner_gets_busy_without_overwriting_the_lease(self) -> None:
        manager, _, _ = self.make_manager()

        self.assertTrue(manager.acquire("inkmemo", 120)["ok"])
        busy = manager.acquire("other", 120)

        self.assertFalse(busy["ok"])
        self.assertEqual(busy["state"], "busy")
        self.assertEqual(busy["owner"], "inkmemo")

    def test_heartbeat_extends_the_lease_and_bad_token_is_rejected(self) -> None:
        manager, _, clock = self.make_manager()
        manager.acquire("inkmemo", 30)
        clock[0] = 20

        renewed = manager.heartbeat("token-test", 60)
        invalid = manager.heartbeat("wrong", 60)

        self.assertTrue(renewed["ok"])
        self.assertEqual(renewed["expires_in"], 60)
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["state"], "invalid_token")

    def test_expired_lease_automatically_resumes_the_worker(self) -> None:
        manager, worker, clock = self.make_manager()
        manager.acquire("inkmemo", 30)
        clock[0] = 31

        status = manager.status()

        self.assertIsNone(status["lease"])
        self.assertTrue(worker.is_running())
        self.assertEqual(worker.starts, [60])

    def test_pipe_server_round_trip_uses_explicit_key(self) -> None:
        import uuid

        worker = FakeLeaseWorker(True)
        manager = ble_lease.BleLeaseManager(
            worker,
            control.threading.RLock(),
            interval_getter=lambda: 60,
            token_factory=lambda: "pipe-token",
            release_wait=0,
        )
        with TemporaryDirectory() as directory:
            pipe_name = rf"\\.\pipe\MagpieLcdBridge.Test.{uuid.uuid4().hex}"
            key_path = Path(directory) / "lease.key"
            server = ble_lease.BleLeasePipeServer(
                manager, pipe_name=pipe_name, key_path=key_path
            )
            server.start()
            try:
                granted = ble_lease.request_lease(
                    {"op": "acquire", "owner": "inkmemo", "ttl_seconds": 120},
                    pipe_name=pipe_name,
                    key_path=key_path,
                )
                released = ble_lease.request_lease(
                    {"op": "release", "owner": "inkmemo", "token": "pipe-token"},
                    pipe_name=pipe_name,
                    key_path=key_path,
                )
            finally:
                server.stop()

        self.assertTrue(granted["ok"])
        self.assertTrue(released["ok"])
        self.assertTrue(worker.is_running())

    def test_tray_blocks_start_and_restart_while_external_lease_is_active(self) -> None:
        worker = FakeLeaseWorker(False)
        app = object.__new__(control.TrayApp)
        app.worker = worker
        app.worker_lock = control.threading.RLock()
        app.settings = control.Settings(interval_seconds=60)
        app.lease = ble_lease.BleLeaseManager(
            worker,
            app.worker_lock,
            interval_getter=lambda: 60,
            token_factory=lambda: "token-test",
            release_wait=0,
        )
        app.lease.acquire("inkmemo", 120)

        with self.assertRaisesRegex(RuntimeError, "inkmemo"):
            app._start_worker()
        with self.assertRaisesRegex(RuntimeError, "inkmemo"):
            app._restart_worker()
        self.assertEqual(worker.starts, [])

    def test_tray_starts_and_restarts_only_after_lease_release(self) -> None:
        worker = FakeLeaseWorker(False)
        app = object.__new__(control.TrayApp)
        app.worker = worker
        app.worker_lock = control.threading.RLock()
        app.settings = control.Settings(interval_seconds=60)
        app.lease = ble_lease.BleLeaseManager(
            worker,
            app.worker_lock,
            interval_getter=lambda: 60,
            token_factory=lambda: "token-test",
            release_wait=0,
        )

        app._start_worker()
        app._restart_worker()

        self.assertTrue(worker.is_running())
        self.assertEqual(worker.starts, [60, 60])


if __name__ == "__main__":
    unittest.main()
