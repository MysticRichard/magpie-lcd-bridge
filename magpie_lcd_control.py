from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

import ble_lease

ROOT = Path(__file__).resolve().parent
WORKER_SCRIPT = ROOT / "magpie_lcd.py"
CONFIG_PATH = ROOT / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.json"
PREVIEW_PATH = ROOT / "last-frame.png"
WORKER_LOG_PATH = ROOT / "logs" / "magpie-lcd.log"
CONTROLLER_LOG_PATH = ROOT / "logs" / "controller.log"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MagpieLcdBridge"
SETTINGS_PATH = APP_DIR / "settings.json"
SHOW_SETTINGS_REQUEST = APP_DIR / "show-settings.request"
MUTEX_NAME = "Local\\MagpieLcdBridgeController"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Magpie LCD Bridge Control"

DEFAULT_INTERVAL = 60
MIN_INTERVAL = 30
MAX_INTERVAL = 3600
DTOKEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AUTOSTART_TASK_NAME = "Magpie LCD Bridge Controller"

log = logging.getLogger("magpie-lcd-control")


def normalize_interval(value: object) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("刷新间隔必须是整数秒") from error
    if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        raise ValueError(f"刷新间隔必须在 {MIN_INTERVAL}-{MAX_INTERVAL} 秒之间")
    return interval


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


@dataclass
class Settings:
    interval_seconds: int = DEFAULT_INTERVAL
    autostart: bool = False
    start_on_launch: bool = True

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> Settings:
        if not path.exists():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                interval_seconds=normalize_interval(
                    payload.get("interval_seconds", DEFAULT_INTERVAL)
                ),
                autostart=payload.get("autostart") is True,
                start_on_launch=payload.get("start_on_launch") is not False,
            )
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as error:
            log.warning("读取控制器设置失败，使用默认值：%s", error)
            return cls()

    def save(self, path: Path = SETTINGS_PATH) -> None:
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2).encode("utf-8")
        _atomic_write(path, payload)


def worker_python() -> Path:
    if not getattr(sys, "frozen", False):
        project_runtime = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        if project_runtime.exists():
            return project_runtime
    python = Path(sys.executable)
    if python.name.lower() == "python.exe":
        windowless = python.with_name("pythonw.exe")
        if windowless.exists():
            return windowless
    return python


def build_worker_command(interval: int) -> list[str]:
    return [
        str(worker_python()),
        str(WORKER_SCRIPT),
        "--log-file",
        str(WORKER_LOG_PATH),
        "run",
        "--interval",
        str(normalize_interval(interval)),
    ]


def _powershell_args(script: str) -> list[str]:
    script = (
        "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'; "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + script
    )
    return [
        str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
        base64.b64encode(script.encode("utf-16le")).decode("ascii"),
    ]


def build_autostart_create_args() -> list[str]:
    if getattr(sys, "frozen", False):
        executable, arguments = sys.executable, ""
    else:
        executable = str(worker_python())
        arguments = subprocess.list2cmdline([str(Path(__file__).resolve())])
    executable = executable.replace("'", "''")
    arguments = arguments.replace("'", "''")
    argument_option = f" -Argument '{arguments}'" if arguments else ""
    directory = str(ROOT).replace("'", "''")
    return _powershell_args(
        "$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name; "
        f"$action = New-ScheduledTaskAction -Execute '{executable}'"
        f"{argument_option} -WorkingDirectory '{directory}'; "
        "$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user; "
        "$principal = New-ScheduledTaskPrincipal -UserId $user "
        "-LogonType Interactive -RunLevel Limited; "
        "$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew "
        "-ExecutionTimeLimit (New-TimeSpan -Days 3650); "
        f"Register-ScheduledTask -TaskName '{AUTOSTART_TASK_NAME}' -TaskPath '\\' "
        "-Action $action -Trigger $trigger -Principal $principal -Settings $settings "
        "-Force | Out-Null"
    )


def _run_autostart_command(args: list[str]) -> str:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=DTOKEN,
        check=False,
        timeout=30,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"计划任务操作失败，退出码 {result.returncode}")
    return result.stdout.strip()


def _remove_legacy_run_value() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except FileNotFoundError:
        pass


def set_autostart(enabled: bool) -> None:
    if os.name != "nt":
        raise RuntimeError("登录自启只支持 Windows")

    if enabled:
        command = build_autostart_create_args()
    else:
        command = _powershell_args(
            "$task = Get-ScheduledTask -TaskPath '\\' | "
            f"Where-Object TaskName -eq '{AUTOSTART_TASK_NAME}'; "
            "if ($task) { $task | Unregister-ScheduledTask -Confirm:$false }"
        )
    _run_autostart_command(command)
    _remove_legacy_run_value()


def read_autostart() -> bool:
    if os.name != "nt":
        return False
    return _run_autostart_command(_powershell_args(
        "$task = Get-ScheduledTask -TaskPath '\\' | "
        f"Where-Object TaskName -eq '{AUTOSTART_TASK_NAME}'; "
        "if ($task -and $task.Settings.Enabled) { 'enabled' }"
    )) == "enabled"


class SingleInstance:
    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self.handle = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, self.name)
        return ctypes.windll.kernel32.GetLastError() != 183

    def release(self) -> None:
        if self.handle and os.name == "nt":
            ctypes.windll.kernel32.CloseHandle(self.handle)
        self.handle = None


def request_settings() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SHOW_SETTINGS_REQUEST.touch()


def consume_settings_request() -> bool:
    if not SHOW_SETTINGS_REQUEST.exists():
        return False
    try:
        SHOW_SETTINGS_REQUEST.unlink()
    except OSError:
        return False
    return True


def terminate_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt" and getattr(process, "pid", None):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=DTOKEN,
            check=False,
            timeout=10,
        )
    else:
        process.terminate()


class WorkerProcess:
    def __init__(
        self,
        command_factory: Callable[[int], list[str]] = build_worker_command,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        terminate_factory: Callable[[subprocess.Popen], None] = terminate_process_tree,
    ) -> None:
        self.command_factory = command_factory
        self.popen_factory = popen_factory
        self.terminate_factory = terminate_factory
        self.process: subprocess.Popen | None = None
        self.started_at: datetime | None = None
        self.last_error: str | None = None

    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def start(self, interval: int) -> bool:
        if self.is_running():
            return False
        try:
            self.process = self.popen_factory(
                self.command_factory(interval),
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DTOKEN,
            )
            self.started_at = datetime.now()
            self.last_error = None
            log.info("worker 已启动，间隔 %d 秒", interval)
            return True
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            log.error("worker 启动失败：%s", self.last_error)
            raise

    def stop(self) -> bool:
        process = self.process
        self.process = None
        self.started_at = None
        if process is None or process.poll() is not None:
            return False
        try:
            self.terminate_factory(process)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                log.warning("worker 未在 8 秒内退出，强制结束")
                process.kill()
                process.wait(timeout=3)
            log.info("worker 已停止")
            return True
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            log.error("worker 停止失败：%s", self.last_error)
            raise

    def restart(self, interval: int) -> bool:
        self.stop()
        return self.start(interval)


def recent_worker_time(marker: str) -> str | None:
    try:
        lines = WORKER_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-200:]):
        if marker in line and len(line) >= 19:
            return line[11:19]
    return None


def recent_worker_state(since: datetime | None = None) -> tuple[str, str | None]:
    try:
        lines = WORKER_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "unknown", None
    since_text = since.strftime("%Y-%m-%d %H:%M:%S") if since else None
    for line in reversed(lines[-300:]):
        if len(line) < 19:
            continue
        if since_text and line[:19] < since_text:
            break
        stamp = line[11:19]
        if "图片已发送" in line or "已连接 DA-LCD" in line:
            return "connected", stamp
        if "BLE 更新失败" in line or "BLE 连接已断开" in line:
            return "reconnecting", stamp
    return "unknown", None


def make_icon() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((7, 7, 57, 57), radius=10, fill="#087f73")
    draw.rectangle((15, 17, 49, 38), outline="white", width=4)
    draw.line((20, 43, 44, 43), fill="white", width=4)
    draw.line((24, 48, 40, 48), fill="white", width=3)
    draw.rectangle((21, 23, 30, 27), fill="white")
    draw.rectangle((33, 23, 43, 27), fill="white")
    return image


class TrayApp:
    def __init__(self) -> None:
        self.settings = Settings.load()
        # The startup entry is the source of truth for the checkbox.
        self.settings.autostart = read_autostart()
        self.worker = WorkerProcess()
        self.worker_lock = threading.RLock()
        self.settings_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.icon = None
        self.lease = ble_lease.BleLeaseManager(
            self.worker,
            self.worker_lock,
            interval_getter=lambda: self.settings.interval_seconds,
            on_change=self._update_menu,
        )
        self.lease_server: ble_lease.BleLeasePipeServer | None = None
        self.lease_watchdog: ble_lease.LeaseWatchdog | None = None

    def _worker_running(self) -> bool:
        with self.worker_lock:
            return self.worker.is_running()

    def _start_worker(self) -> None:
        owner = self.lease.start_worker_if_idle(self.settings.interval_seconds)
        if owner:
            raise RuntimeError(f"蓝牙正由 {owner} 临时占用")

    def _stop_worker(self) -> None:
        with self.worker_lock:
            self.worker.stop()

    def _restart_worker(self) -> None:
        owner = self.lease.restart_worker_if_idle(self.settings.interval_seconds)
        if owner:
            raise RuntimeError(f"蓝牙正由 {owner} 临时占用")

    def _status_label(self, _item=None) -> str:
        owner = self.lease.owner
        if owner:
            return f"BLE 由 {owner} 临时占用 · LCD 已暂停"
        if not self._worker_running():
            return f"已停止 · {self.settings.interval_seconds} 秒"
        with self.worker_lock:
            state, stamp = recent_worker_state(self.worker.started_at)
        if state == "connected" and stamp:
            return f"运行中 · {self.settings.interval_seconds} 秒 · {stamp} 已刷新"
        if state == "reconnecting":
            return f"运行中 · {self.settings.interval_seconds} 秒 · BLE 重连中"
        return f"运行中 · {self.settings.interval_seconds} 秒 · 等待首次刷新"

    def _last_refresh_label(self) -> str:
        if not self._worker_running():
            return "等待中"
        with self.worker_lock:
            state, stamp = recent_worker_state(self.worker.started_at)
        return stamp if state == "connected" and stamp else "等待中"

    def _toggle_label(self, _item=None) -> str:
        return "停止显示" if self._worker_running() else "启动显示"

    def _notify(self, message: str) -> None:
        if self.icon is None:
            return
        try:
            self.icon.notify(message, "Magpie LCD Bridge")
        except Exception:
            log.debug("系统通知不可用", exc_info=True)

    def _handle_error(self, action: str, error: Exception) -> None:
        self.worker.last_error = f"{type(error).__name__}: {error}"
        log.error("%s失败：%s", action, self.worker.last_error)
        self._notify(f"{action}失败：{self.worker.last_error}")

    def _toggle_worker(self, _icon=None, _item=None) -> None:
        try:
            if self._worker_running():
                self._stop_worker()
            else:
                self._start_worker()
        except Exception as error:
            self._handle_error("切换显示状态", error)
        self._update_menu()

    def _immediate_refresh(self, _icon=None, _item=None) -> None:
        try:
            self._restart_worker()
            self._notify("已请求立即刷新")
        except Exception as error:
            self._handle_error("立即刷新", error)
        self._update_menu()

    def _open_preview(self, _icon=None, _item=None) -> None:
        if not PREVIEW_PATH.exists():
            self._notify("尚无预览，请先启动显示并等待一次刷新")
            return
        try:
            os.startfile(PREVIEW_PATH)
        except OSError as error:
            self._handle_error("打开预览", error)

    def _open_config(self, _icon=None, _item=None) -> None:
        if not CONFIG_PATH.exists():
            self._notify("还没有 config.json；已打开 config.example.json 供参考")
            try:
                os.startfile(EXAMPLE_CONFIG_PATH)
            except OSError as error:
                self._handle_error("打开额度配置示例", error)
            return
        try:
            os.startfile(CONFIG_PATH)
        except OSError as error:
            self._handle_error("打开额度配置", error)

    def _open_settings(self, _icon=None, _item=None) -> None:
        if not self.settings_lock.acquire(blocking=False):
            return
        try:
            import tkinter as tk
            from tkinter import messagebox

            self._settings_window(tk, messagebox)
        finally:
            self.settings_lock.release()
            self._update_menu()

    def _save_settings(
        self,
        interval: int,
        autostart: bool,
        start_on_launch: bool,
        messagebox,
    ) -> bool:
        old = self.settings
        new = Settings(interval, autostart, start_on_launch)
        try:
            if old.autostart != new.autostart:
                set_autostart(new.autostart)
            new.save()
            self.settings = new
            if old.interval_seconds != new.interval_seconds and self._worker_running():
                self._restart_worker()
            return True
        except Exception as error:
            messagebox.showerror("设置保存失败", str(error))
            self._handle_error("保存设置", error)
            return False

    def _settings_window(self, tk, messagebox) -> None:
        root = tk.Tk()
        root.title("Magpie LCD Bridge 设置")
        root.geometry("620x560")
        root.resizable(False, False)
        root.configure(bg="#f4f7f7")

        font = ("Microsoft YaHei UI", 9)
        title_font = ("Microsoft YaHei UI", 18, "bold")
        section_font = ("Microsoft YaHei UI", 10, "bold")
        muted = "#68787c"

        outer = tk.Frame(root, bg="#f4f7f7", padx=26, pady=22)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg="#f4f7f7")
        header.pack(fill="x")
        left = tk.Frame(header, bg="#f4f7f7")
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="桌面小屏控制", font=title_font, bg="#f4f7f7", fg="#15252b").pack(anchor="w")
        tk.Label(
            left,
            text="Magpie 用量与额度 · DA14585 TFT",
            font=font,
            bg="#f4f7f7",
            fg=muted,
        ).pack(anchor="w", pady=(5, 0))
        status_var = tk.StringVar(value=self._status_label())
        status = tk.Label(
            header,
            textvariable=status_var,
            font=("Microsoft YaHei UI", 9, "bold"),
            bg="#e4f4ef",
            fg="#27664f",
            padx=11,
            pady=7,
        )
        status.pack(side="right", anchor="n")

        summary = tk.Frame(outer, bg="#ffffff", highlightbackground="#dce4e6", highlightthickness=1)
        summary.pack(fill="x", pady=(19, 22))
        summary_inner = tk.Frame(summary, bg="#ffffff", padx=16, pady=13)
        summary_inner.pack(fill="x")
        summary_inner.columnconfigure(1, weight=1)
        summary_inner.columnconfigure(3, weight=1)
        summary_rows = (
            ("刷新间隔", f"{self.settings.interval_seconds} 秒", "最近刷新", self._last_refresh_label()),
            ("蓝牙连接", "已停止", "设备", "DA-LCD-772D"),
        )
        status_widgets = []
        refresh_widget = None
        for row, values in enumerate(summary_rows):
            for col, value in enumerate(values):
                color = "#263c42"
                font_style = ("Microsoft YaHei UI", 9, "bold") if col in (1, 3) else font
                if col % 2 == 0:
                    tk.Label(summary_inner, text=value, font=font, bg="#ffffff", fg=muted).grid(
                        row=row, column=col, sticky="w", padx=(0, 10), pady=4
                    )
                else:
                    widget = tk.Label(summary_inner, text=value, font=font_style, bg="#ffffff", fg=color)
                    widget.grid(row=row, column=col, sticky="e", padx=(0, 24), pady=4)
                    if row == 1 and col == 1:
                        status_widgets.append(widget)
                    if row == 0 and col == 3:
                        refresh_widget = widget

        tk.Label(outer, text="显示控制", font=section_font, bg="#f4f7f7", fg="#2c4248").pack(anchor="w")
        interval_row = tk.Frame(outer, bg="#f4f7f7")
        interval_row.pack(fill="x", pady=(12, 9))
        tk.Label(interval_row, text="自动刷新间隔", font=font, bg="#f4f7f7", fg="#3d5157").pack(side="left")
        interval_var = tk.StringVar(value=str(self.settings.interval_seconds))
        interval_entry = tk.Entry(
            interval_row,
            textvariable=interval_var,
            width=8,
            font=font,
            relief="solid",
            bd=1,
        )
        interval_entry.pack(side="left", padx=(28, 6))
        tk.Label(interval_row, text="秒", font=font, bg="#f4f7f7", fg=muted).pack(side="left")
        tk.Label(
            interval_row,
            text=f"范围 {MIN_INTERVAL} – {MAX_INTERVAL} 秒",
            font=font,
            bg="#f4f7f7",
            fg="#879397",
        ).pack(side="left", padx=(15, 0))

        autostart_var = tk.BooleanVar(value=self.settings.autostart)
        start_var = tk.BooleanVar(value=self.settings.start_on_launch)
        tk.Checkbutton(
            outer,
            text="登录 Windows 后自动启动控制器",
            variable=autostart_var,
            font=font,
            bg="#f4f7f7",
            activebackground="#f4f7f7",
            anchor="w",
        ).pack(fill="x", pady=(3, 2))
        tk.Checkbutton(
            outer,
            text="启动控制器后自动开始显示",
            variable=start_var,
            font=font,
            bg="#f4f7f7",
            activebackground="#f4f7f7",
            anchor="w",
        ).pack(fill="x", pady=2)

        actions = tk.Frame(outer, bg="#f4f7f7")
        actions.pack(fill="x", pady=(18, 0))
        tk.Button(
            actions,
            text="打开额度配置",
            font=font,
            command=self._open_config,
            relief="solid",
            bd=1,
            padx=12,
            pady=5,
        ).pack(side="left")
        tk.Button(
            actions,
            text="打开最新预览",
            font=font,
            command=self._open_preview,
            relief="solid",
            bd=1,
            padx=12,
            pady=5,
        ).pack(side="left", padx=(9, 0))

        footer = tk.Frame(outer, bg="#f4f7f7")
        footer.pack(fill="x", side="bottom", pady=(24, 0))
        tk.Label(
            footer,
            text="停止显示会释放蓝牙，LCD 可能回到固件时钟模式。",
            font=("Microsoft YaHei UI", 8),
            bg="#f4f7f7",
            fg="#7d8b8e",
        ).pack(side="left")
        cancel = tk.Button(footer, text="取消", font=font, command=root.destroy, relief="solid", bd=1, padx=14, pady=5)
        cancel.pack(side="right")

        def save() -> None:
            try:
                interval = normalize_interval(interval_var.get())
            except ValueError as error:
                messagebox.showerror("刷新间隔无效", str(error))
                return
            if self._save_settings(interval, autostart_var.get(), start_var.get(), messagebox):
                messagebox.showinfo("Magpie LCD Bridge", "设置已保存")
                status_var.set(self._status_label())

        save_button = tk.Button(
            footer,
            text="保存",
            font=("Microsoft YaHei UI", 9, "bold"),
            command=save,
            bg="#087f73",
            fg="#ffffff",
            activebackground="#05675e",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=5,
        )
        save_button.pack(side="right", padx=(0, 9))

        def refresh_status() -> None:
            if not root.winfo_exists():
                return
            status_var.set(self._status_label())
            status_widgets[0].configure(
                text=self._ble_label()[0],
                fg=self._ble_label()[1],
            )
            if refresh_widget is not None:
                refresh_widget.configure(text=self._last_refresh_label())
            root.after(1000, refresh_status)

        root.after(1000, refresh_status)
        root.mainloop()

    def _update_menu(self) -> None:
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                log.debug("更新托盘菜单失败", exc_info=True)

    def _ble_label(self) -> tuple[str, str]:
        owner = self.lease.owner
        if owner:
            return f"由 {owner} 占用", "#a36a1f"
        if not self._worker_running():
            return "已停止", "#6b777a"
        with self.worker_lock:
            state, _ = recent_worker_state(self.worker.started_at)
        if state == "connected":
            return "已连接", "#15805f"
        if state == "reconnecting":
            return "重连中", "#bd5b3e"
        return "等待中", "#6b777a"

    def _quit(self, _icon=None, _item=None) -> None:
        self.stop_event.set()
        try:
            if self.lease_watchdog is not None:
                self.lease_watchdog.stop()
            if self.lease_server is not None:
                self.lease_server.stop()
            self._stop_worker()
        finally:
            if self.icon is not None:
                self.icon.stop()

    def _watch_settings_requests(self) -> None:
        while not self.stop_event.wait(0.8):
            if consume_settings_request():
                threading.Thread(target=self._open_settings, daemon=True).start()

    def run(self) -> None:
        import pystray

        self.icon = pystray.Icon(
            "magpie-lcd",
            make_icon(),
            "Magpie LCD Bridge",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_label, None, enabled=False),
                pystray.MenuItem("立即刷新", self._immediate_refresh, default=True),
                pystray.MenuItem("设置", self._open_settings),
                pystray.MenuItem("打开最新预览", self._open_preview),
                pystray.MenuItem("打开额度配置", self._open_config),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._toggle_label, self._toggle_worker),
                pystray.MenuItem("退出控制器", self._quit),
            ),
        )
        self.lease_server = ble_lease.BleLeasePipeServer(self.lease)
        self.lease_watchdog = ble_lease.LeaseWatchdog(self.lease)
        self.lease_server.start()
        self.lease_watchdog.start()
        if self.settings.start_on_launch and self.lease.owner is None:
            try:
                self._start_worker()
            except Exception as error:
                self._handle_error("启动显示", error)
        threading.Thread(target=self._watch_settings_requests, daemon=True).start()
        try:
            self.icon.run()
        finally:
            if self.lease_watchdog is not None:
                self.lease_watchdog.stop()
            if self.lease_server is not None:
                self.lease_server.stop()
            self._stop_worker()


def main() -> int:
    CONTROLLER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(CONTROLLER_LOG_PATH, encoding="utf-8"),
        ],
    )
    instance = SingleInstance()
    if not instance.acquire():
        request_settings()
        return 0
    try:
        TrayApp().run()
        return 0
    except Exception as error:
        log.exception("控制器运行失败：%s", error)
        return 1
    finally:
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
