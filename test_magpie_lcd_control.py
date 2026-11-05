import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
