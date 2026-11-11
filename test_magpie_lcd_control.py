import base64
import json
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

    def test_autostart_uses_a_current_user_logon_task(self) -> None:
        command = control.build_autostart_create_args()

        self.assertEqual(Path(command[0]).name, "powershell.exe")
        self.assertEqual(command[1:5], [
            "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        ])
        self.assertEqual(command[5], "-EncodedCommand")
        script = base64.b64decode(command[6]).decode("utf-16le")
        self.assertIn("Register-ScheduledTask", script)
        self.assertIn("-AtLogOn", script)
        self.assertIn("-Hidden", script)

    def test_desktop_shortcut_opens_settings_through_controller(self) -> None:
        command = control.build_desktop_shortcut_create_args()
        script = base64.b64decode(command[6]).decode("utf-16le")

        self.assertIn("DesktopDirectory", script)
        self.assertIn("WScript.Shell", script)
        self.assertIn(control.DESKTOP_SHORTCUT_NAME, script)
        self.assertIn("magpie_lcd_control.py", script)
        self.assertIn("--open-settings", script)
        self.assertIn(control.SHORTCUT_ICON_PATH.name, script)
        self.assertIn("IconLocation", script)

    def test_desktop_shortcut_creation_returns_saved_path(self) -> None:
        expected = Path(r"C:\Users\demo\Desktop") / control.DESKTOP_SHORTCUT_NAME
        result = subprocess.CompletedProcess([], 0, f"{expected}\n", "")
        with patch.object(control.subprocess, "run", return_value=result):
            self.assertEqual(control.create_desktop_shortcut(), expected)

    def test_shortcut_icon_contains_windows_sizes(self) -> None:
        with control.Image.open(control.SHORTCUT_ICON_PATH) as image:
            self.assertEqual(image.format, "ICO")
            self.assertIn((256, 256), image.info["sizes"])

    def test_tray_shortcut_action_reports_created_name(self) -> None:
        app = object.__new__(control.TrayApp)
        app.icon = None
        expected = Path(r"C:\Users\demo\Desktop") / control.DESKTOP_SHORTCUT_NAME
        with patch.object(control, "create_desktop_shortcut", return_value=expected):
            self.assertEqual(
                app._create_desktop_shortcut(),
                f"桌面快捷方式已创建：{control.DESKTOP_SHORTCUT_NAME}",
            )

    def test_installer_creates_desktop_shortcut(self) -> None:
        script = (control.ROOT / "scripts" / "install-controller-autostart.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("create-controller-shortcut.ps1", script)

    def test_shortcut_argument_opens_settings_after_startup(self) -> None:
        with patch.object(control.sys, "argv", ["magpie_lcd_control.py", "--open-settings"]), patch.object(
            control, "SingleInstance"
        ) as instance_class, patch.object(control, "TrayApp") as app_class, patch.object(
            control.logging, "basicConfig"
        ):
            instance_class.return_value.acquire.return_value = True
            self.assertEqual(control.main(), 0)

        app_class.assert_called_once_with(open_settings_on_start=True)
        app_class.return_value.run.assert_called_once_with()

    def test_failed_task_registration_preserves_legacy_autostart(self) -> None:
        result = subprocess.CompletedProcess([], 1, "", "Access denied")
        with patch.object(control.subprocess, "run", return_value=result), patch.object(
            control, "_remove_legacy_run_value"
        ) as remove:
            with self.assertRaisesRegex(RuntimeError, "Access denied"):
                control.set_autostart(True)
            remove.assert_not_called()

    def test_autostart_reports_a_disabled_task_as_off(self) -> None:
        result = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(control.subprocess, "run", return_value=result):
            self.assertFalse(control.read_autostart())

    def test_open_preview_reports_success_and_missing_file(self) -> None:
        app = object.__new__(control.TrayApp)
        app.icon = None
        with TemporaryDirectory() as directory:
            preview = Path(directory) / "last-frame.png"
            with patch.object(control, "PREVIEW_PATH", preview):
                self.assertIn("尚无预览", app._open_preview())
                preview.write_bytes(b"png")
                with patch.object(control.os, "startfile") as startfile:
                    self.assertEqual(app._open_preview(), "已请求打开最新预览")
                startfile.assert_called_once_with(preview)


class QuotaSelectionTests(unittest.TestCase):
    def test_magpie_payload_is_grouped_deduplicated_and_keeps_known_labels(self) -> None:
        payload = {
            "data": [
                {
                    "provider": "codex",
                    "name": "Codex",
                    "windows": [
                        {"name": "5 hours"},
                        {"name": "7 days"},
                        {"name": "5 hours"},
                    ],
                },
                {
                    "provider": "workbuddy",
                    "name": "WorkBuddy",
                    "windows": [{"name": "Credits"}],
                },
                {
                    "provider": "workbuddy",
                    "name": "WorkBuddy",
                    "windows": [
                        {"name": "Credits"},
                        {"name": "Extra credits"},
                    ],
                },
                {
                    "provider": "antigravity",
                    "name": "Antigravity",
                    "windows": [
                        {"name": "Gemini · 7 days"},
                        {"name": "Gemini · 5 hours"},
                        {"name": "Claude & GPT · 7 days"},
                        {"name": "Claude & GPT · 5 hours"},
                    ],
                },
                {"provider": "empty", "name": "Empty", "windows": []},
            ]
        }
        current = (
            control.magpie_lcd.QuotaGroup(
                "我的 Codex",
                "codex",
                (("5 hours", "五时"),),
            ),
        )

        options = control.quota_option_groups(payload, current)

        self.assertEqual([group.provider for group in options], [
            "codex",
            "workbuddy",
            "antigravity",
        ])
        self.assertEqual(options[0].title, "我的 Codex")
        self.assertEqual(options[0].windows, (("5 hours", "五时"), ("7 days", "7D")))
        self.assertEqual(
            options[1].windows,
            (("Credits", "积分"), ("Extra credits", "额外")),
        )
        self.assertEqual(
            options[2].windows,
            (
                ("Gemini · 5 hours", "G5H"),
                ("Gemini · 7 days", "G7D"),
                ("Claude & GPT · 5 hours", "CG5H"),
                ("Claude & GPT · 7 days", "CG7D"),
            ),
        )

    def test_saved_window_order_prefers_short_periods(self) -> None:
        options = (
            control.magpie_lcd.QuotaGroup(
                "OpenCode Go",
                "opencode-go",
                (("Month", "本月"), ("7 days", "7D"), ("5 hours", "5H")),
            ),
        )

        groups = control.build_quota_groups(
            options,
            {("opencode-go", "Month"), ("opencode-go", "7 days"), ("opencode-go", "5 hours")},
        )

        self.assertEqual(
            groups[0].windows,
            (("5 hours", "5H"), ("7 days", "7D"), ("Month", "本月")),
        )

    def test_selection_is_bounded_to_two_groups_and_three_windows(self) -> None:
        options = (
            control.magpie_lcd.QuotaGroup(
                "A", "a", (("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"))
            ),
            control.magpie_lcd.QuotaGroup("B", "b", (("1", "1"),)),
            control.magpie_lcd.QuotaGroup("C", "c", (("1", "1"),)),
        )

        with self.assertRaisesRegex(ValueError, "至少选择"):
            control.build_quota_groups(options, set())
        with self.assertRaisesRegex(ValueError, "最多选择两个"):
            control.build_quota_groups(
                options,
                {("a", "1"), ("b", "1"), ("c", "1")},
            )
        with self.assertRaisesRegex(ValueError, "最多选择三个"):
            control.build_quota_groups(
                options,
                {("a", "1"), ("a", "2"), ("a", "3"), ("a", "4")},
            )

    def test_checkbox_states_block_new_providers_and_fourth_window(self) -> None:
        options = (
            control.magpie_lcd.QuotaGroup(
                "A", "a", (("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"))
            ),
            control.magpie_lcd.QuotaGroup("B", "b", (("1", "1"),)),
            control.magpie_lcd.QuotaGroup("C", "c", (("1", "1"),)),
        )

        two_providers = control.quota_checkbox_states(
            options, {("a", "1"), ("b", "1")}
        )
        self.assertFalse(two_providers[("c", "1")])
        self.assertTrue(two_providers[("a", "2")])

        one_group_full = control.quota_checkbox_states(
            options, {("a", "1"), ("a", "2"), ("a", "3")}
        )
        self.assertFalse(one_group_full[("a", "4")])
        self.assertTrue(one_group_full[("b", "1")])

    def test_saved_selection_round_trips_through_worker_config_loader(self) -> None:
        groups = (
            control.magpie_lcd.QuotaGroup(
                "Codex", "codex", (("5 hours", "5H"), ("7 days", "7D"))
            ),
            control.magpie_lcd.QuotaGroup(
                "OpenCode Go", "opencode-go", (("Month", "本月"),)
            ),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"

            control.save_quota_config(path, groups)

            self.assertEqual(control.magpie_lcd.load_quota_config(path), groups)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(list(payload["quota_groups"][0]), [
                "provider",
                "title",
                "windows",
            ])

    def test_empty_magpie_payload_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有可显示"):
            control.quota_option_groups({"data": []})


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

    def test_wrong_key_does_not_stop_the_pipe_server(self) -> None:
        import uuid
        from multiprocessing import AuthenticationError
        from multiprocessing.connection import Client

        manager, _, _ = self.make_manager()
        with TemporaryDirectory() as directory:
            pipe_name = rf"\\.\pipe\MagpieLcdBridge.Test.{uuid.uuid4().hex}"
            key_path = Path(directory) / "lease.key"
            server = ble_lease.BleLeasePipeServer(
                manager, pipe_name=pipe_name, key_path=key_path
            )
            server.start()
            try:
                with self.assertRaises(AuthenticationError):
                    Client(pipe_name, family="AF_PIPE", authkey=b"stale-key")
                server.thread.join(timeout=0.2)
                self.assertTrue(server.thread.is_alive())
                status = ble_lease.request_lease(
                    {"op": "status"}, pipe_name=pipe_name, key_path=key_path
                )
                self.assertEqual(status["state"], "idle")
            finally:
                if not server.thread.is_alive():
                    server.listener.close()
                    server.thread = None
                server.stop()

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
