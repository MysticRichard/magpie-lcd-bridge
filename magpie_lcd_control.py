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
from typing import Callable, Sequence

from PIL import Image, ImageDraw

import ble_lease
import magpie_lcd

ROOT = Path(__file__).resolve().parent
WORKER_SCRIPT = ROOT / "magpie_lcd.py"
CONFIG_PATH = ROOT / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.json"
PREVIEW_PATH = ROOT / "last-frame.png"
SHORTCUT_ICON_PATH = ROOT / "assets" / "magpie-lcd.ico"
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
DESKTOP_SHORTCUT_NAME = "Magpie LCD Bridge.lnk"
OPEN_SETTINGS_ARG = "--open-settings"

log = logging.getLogger("magpie-lcd-control")

QUOTA_LABELS = {
    "5 hours": "5H",
    "7 days": "7D",
    "month": "本月",
    "credits": "积分",
    "extra credits": "额外",
    "total credits": "总积分",
    "总积分": "总积分",
    "基础积分包": "基础",
    "赠送积分包": "赠送",
    "deepseek-v4.1-flash tokens (est.)": "DS4.1",
}


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


def quota_short_label(name: str) -> str:
    folded = name.casefold()
    known = QUOTA_LABELS.get(folded)
    if known:
        return known
    if " · " in name:
        left, right = (part.strip() for part in name.split(" · ", 1))
        tail = QUOTA_LABELS.get(right.casefold(), right)
        if "gemini" in left.casefold():
            return f"G{tail}"
        if "claude" in left.casefold() or "gpt" in left.casefold():
            return f"CG{tail}"
    return name if len(name) <= 7 else name[:6] + "…"


def _quota_period_rank(name: str) -> int:
    folded = name.casefold()
    if "5 hour" in folded:
        return 0
    if "7 day" in folded:
        return 1
    if "month" in folded:
        return 2
    return 3


def order_quota_windows(
    windows: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    scope_order: dict[str, int] = {}
    ranked = []
    for index, (name, label) in enumerate(windows):
        scope = name.split(" · ", 1)[0] if " · " in name else ""
        scope_order.setdefault(scope, len(scope_order))
        ranked.append((scope_order[scope], _quota_period_rank(name), index, name, label))
    return tuple((name, label) for *_, name, label in sorted(ranked))


def quota_option_groups(
    payload: dict,
    current_groups: Sequence[magpie_lcd.QuotaGroup] = (),
) -> tuple[magpie_lcd.QuotaGroup, ...]:
    configured_titles = {group.provider: group.title for group in current_groups}
    configured_labels = {
        (group.provider, name): label
        for group in current_groups
        for name, label in group.windows
    }
    grouped: dict[str, tuple[str, list[tuple[str, str]], set[str]]] = {}
    order: list[str] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        if not provider:
            continue
        title = configured_titles.get(provider) or str(item.get("name") or provider).strip()
        windows: list[tuple[str, str]] = []
        names: set[str] = set()
        for window in item.get("windows", []):
            if not isinstance(window, dict):
                continue
            name = str(window.get("name") or "").strip()
            if not name or name in names:
                continue
            names.add(name)
            windows.append(
                (name, configured_labels.get((provider, name), quota_short_label(name)))
            )
        if not windows:
            continue
        if provider not in grouped:
            grouped[provider] = (title, [], set())
            order.append(provider)
        group_title, group_windows, group_names = grouped[provider]
        for name, label in windows:
            if name not in group_names:
                group_names.add(name)
                group_windows.append((name, label))
    options = tuple(
        magpie_lcd.QuotaGroup(
            grouped[provider][0],
            provider,
            order_quota_windows(grouped[provider][1]),
        )
        for provider in order
    )
    if not options:
        raise ValueError("Magpie 当前没有可显示的额度窗口")
    return options


def build_quota_groups(
    options: Sequence[magpie_lcd.QuotaGroup],
    selected: set[tuple[str, str]],
) -> tuple[magpie_lcd.QuotaGroup, ...]:
    groups = []
    for option in options:
        windows = tuple(
            (name, label)
            for name, label in order_quota_windows(option.windows)
            if (option.provider, name) in selected
        )
        if windows:
            groups.append(magpie_lcd.QuotaGroup(option.title, option.provider, windows))
    if not groups:
        raise ValueError("至少选择一个额度窗口")
    if len(groups) > 2:
        raise ValueError("最多选择两个供应商")
    for group in groups:
        if len(group.windows) > 3:
            raise ValueError(f"{group.title} 最多选择三个额度窗口")
    return tuple(groups)


def quota_checkbox_states(
    options: Sequence[magpie_lcd.QuotaGroup],
    selected: set[tuple[str, str]],
) -> dict[tuple[str, str], bool]:
    counts = {
        group.provider: sum(
            (group.provider, name) in selected for name, _ in group.windows
        )
        for group in options
    }
    active_providers = {provider for provider, count in counts.items() if count}
    states: dict[tuple[str, str], bool] = {}
    for group in options:
        for name, _ in group.windows:
            key = (group.provider, name)
            states[key] = key in selected or (
                counts[group.provider] < 3
                and (
                    group.provider in active_providers
                    or len(active_providers) < 2
                )
            )
    return states


def save_quota_config(
    path: Path,
    groups: Sequence[magpie_lcd.QuotaGroup],
) -> None:
    payload = json.dumps(
        {
            "quota_groups": [
                {
                    "provider": group.provider,
                    "title": group.title,
                    "windows": [
                        {"name": name, "label": label}
                        for name, label in group.windows
                    ],
                }
                for group in groups
            ]
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    _atomic_write(path, payload)


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


def build_controller_launch(extra_args: Sequence[str] = ()) -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        executable = sys.executable
        arguments = list(extra_args)
    else:
        executable = str(worker_python())
        arguments = [str(Path(__file__).resolve()), *extra_args]
    return executable, subprocess.list2cmdline(arguments)


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
    executable, arguments = build_controller_launch()
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


def build_desktop_shortcut_create_args() -> list[str]:
    # Shortcut uses absolute install paths; remake it after moving the repository.
    executable, arguments = build_controller_launch([OPEN_SETTINGS_ARG])
    executable = executable.replace("'", "''")
    arguments = arguments.replace("'", "''")
    directory = str(ROOT).replace("'", "''")
    icon = str(SHORTCUT_ICON_PATH).replace("'", "''")
    return _powershell_args(
        "$desktop = [Environment]::GetFolderPath('DesktopDirectory'); "
        "if (-not $desktop) { throw 'Desktop folder not found' }; "
        f"$path = Join-Path $desktop '{DESKTOP_SHORTCUT_NAME}'; "
        "$shell = New-Object -ComObject WScript.Shell; "
        "$shortcut = $shell.CreateShortcut($path); "
        f"$shortcut.TargetPath = '{executable}'; "
        f"$shortcut.Arguments = '{arguments}'; "
        f"$shortcut.WorkingDirectory = '{directory}'; "
        f"$shortcut.IconLocation = '{icon},0'; "
        "$shortcut.Description = 'Magpie LCD Bridge controller and settings'; "
        "$shortcut.Save(); [Console]::WriteLine($path)"
    )


def _run_powershell_command(args: list[str]) -> str:
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
        raise RuntimeError(detail or f"PowerShell 操作失败，退出码 {result.returncode}")
    return result.stdout.strip()


def create_desktop_shortcut() -> Path:
    if os.name != "nt":
        raise RuntimeError("桌面快捷方式只支持 Windows")
    output = _run_powershell_command(build_desktop_shortcut_create_args())
    if not output:
        raise RuntimeError("创建桌面快捷方式失败：系统未返回快捷方式路径")
    return Path(output)


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
    _run_powershell_command(command)
    _remove_legacy_run_value()


def read_autostart() -> bool:
    if os.name != "nt":
        return False
    return _run_powershell_command(_powershell_args(
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


def make_icon(size: int = 64) -> Image.Image:
    scale = size / 64

    def scaled(value: int) -> int:
        return round(value * scale)

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (scaled(7), scaled(7), scaled(57), scaled(57)),
        radius=scaled(10),
        fill="#087f73",
    )
    draw.rectangle(
        (scaled(15), scaled(17), scaled(49), scaled(38)),
        outline="white",
        width=scaled(4),
    )
    draw.line(
        (scaled(20), scaled(43), scaled(44), scaled(43)),
        fill="white",
        width=scaled(4),
    )
    draw.line(
        (scaled(24), scaled(48), scaled(40), scaled(48)),
        fill="white",
        width=scaled(3),
    )
    draw.rectangle(
        (scaled(21), scaled(23), scaled(30), scaled(27)), fill="white"
    )
    draw.rectangle(
        (scaled(33), scaled(23), scaled(43), scaled(27)), fill="white"
    )
    return image


class TrayApp:
    def __init__(self, open_settings_on_start: bool = False) -> None:
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
        self.open_settings_on_start = open_settings_on_start
        self.ui_root = None

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

    def _open_preview(self, _icon=None, _item=None) -> str:
        if not PREVIEW_PATH.exists():
            message = "尚无预览，请先启动显示并等待一次刷新"
            self._notify(message)
            return message
        try:
            os.startfile(PREVIEW_PATH)
        except OSError as error:
            self._handle_error("打开预览", error)
            return f"打开预览失败：{error}"
        log.info("已请求打开最新预览：%s", PREVIEW_PATH)
        return "已请求打开最新预览"

    def _open_config(self, _icon=None, _item=None) -> str:
        if not CONFIG_PATH.exists():
            message = "还没有 config.json；已打开 config.example.json 供参考"
            self._notify(message)
            try:
                os.startfile(EXAMPLE_CONFIG_PATH)
            except OSError as error:
                self._handle_error("打开额度配置示例", error)
                return f"打开配置示例失败：{error}"
            log.info("已请求打开配置示例：%s", EXAMPLE_CONFIG_PATH)
            return message
        try:
            os.startfile(CONFIG_PATH)
        except OSError as error:
            self._handle_error("打开额度配置", error)
            return f"打开额度配置失败：{error}"
        log.info("已请求打开额度配置：%s", CONFIG_PATH)
        return "已请求打开额度配置"

    def _create_desktop_shortcut(self, _icon=None, _item=None) -> str:
        try:
            path = create_desktop_shortcut()
        except Exception as error:
            self._handle_error("创建桌面快捷方式", error)
            return f"创建桌面快捷方式失败：{error}"
        log.info("已创建桌面快捷方式：%s", path)
        return f"桌面快捷方式已创建：{path.name}"

    def _open_settings(self, _icon=None, _item=None) -> None:
        if self.settings_lock.locked():
            return
        request_settings()

    def _show_settings(self, parent=None) -> None:
        if not self.settings_lock.acquire(blocking=False):
            return
        try:
            import tkinter as tk

            self._settings_window(tk, parent)
        finally:
            self.settings_lock.release()
            self._update_menu()

    def _save_settings(
        self,
        interval: int,
        autostart: bool,
        start_on_launch: bool,
        quota_groups: Sequence[magpie_lcd.QuotaGroup] | None = None,
    ) -> str | None:
        old = self.settings
        new = Settings(interval, autostart, start_on_launch)
        try:
            if old.autostart != new.autostart:
                set_autostart(new.autostart)
            quota_changed = False
            if quota_groups is not None:
                old_quota_groups = magpie_lcd.load_quota_config(CONFIG_PATH)
                quota_changed = tuple(quota_groups) != old_quota_groups
                save_quota_config(CONFIG_PATH, quota_groups)
            new.save()
            self.settings = new
        except Exception as error:
            self._handle_error("保存设置", error)
            return f"保存失败：{error}"
        if (
            old.interval_seconds != new.interval_seconds or quota_changed
        ) and self._worker_running():
            try:
                self._restart_worker()
            except Exception as error:
                self._handle_error("应用显示设置", error)
                return f"设置已保存，但当前无法立即重启显示：{error}"
        return None

    def _settings_window(self, tk, parent=None) -> None:
        root = tk.Toplevel(parent) if parent is not None else tk.Tk()
        closed = threading.Event()
        root.title("Magpie LCD Bridge 设置")
        root.geometry("720x760")
        root.resizable(True, True)
        root.configure(bg="#f4f7f7")

        def close_window() -> None:
            if closed.is_set():
                return
            closed.set()
            log.info("关闭设置窗口")
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_window)

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
        status_var = tk.StringVar(value="正在读取状态…")
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
            ("刷新间隔", f"{self.settings.interval_seconds} 秒", "最近刷新", "—"),
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

        current_groups = magpie_lcd.load_quota_config(CONFIG_PATH)
        selected_existing = {
            (group.provider, name)
            for group in current_groups
            for name, _ in group.windows
        }
        quota_vars: dict[tuple[str, str], tk.BooleanVar] = {}
        quota_checks: dict[tuple[str, str], tk.Checkbutton] = {}
        available_options = [current_groups]

        quota_header = tk.Frame(outer, bg="#f4f7f7")
        quota_header.pack(fill="x", pady=(16, 7))
        tk.Label(
            quota_header,
            text="额度显示",
            font=section_font,
            bg="#f4f7f7",
            fg="#2c4248",
        ).pack(side="left")
        quota_status_var = tk.StringVar(
            value="最多显示 2 个供应商，每个供应商最多 3 个窗口"
        )
        tk.Label(
            quota_header,
            textvariable=quota_status_var,
            font=("Microsoft YaHei UI", 8),
            bg="#f4f7f7",
            fg="#68787c",
        ).pack(side="left", padx=(14, 0))

        quota_panel = tk.Frame(
            outer,
            bg="#ffffff",
            highlightbackground="#dce4e6",
            highlightthickness=1,
            height=190,
        )
        quota_panel.pack(fill="x")
        quota_panel.pack_propagate(False)
        quota_canvas = tk.Canvas(
            quota_panel,
            bg="#ffffff",
            highlightthickness=0,
            bd=0,
        )
        quota_scrollbar = tk.Scrollbar(
            quota_panel,
            orient="vertical",
            command=quota_canvas.yview,
        )
        quota_canvas.configure(yscrollcommand=quota_scrollbar.set)
        quota_scrollbar.pack(side="right", fill="y")
        quota_canvas.pack(side="left", fill="both", expand=True)
        quota_options_frame = tk.Frame(quota_canvas, bg="#ffffff", padx=12, pady=10)
        quota_window_id = quota_canvas.create_window(
            (0, 0),
            window=quota_options_frame,
            anchor="nw",
        )
        quota_options_frame.bind(
            "<Configure>",
            lambda _event: quota_canvas.configure(
                scrollregion=quota_canvas.bbox("all")
            ),
        )
        quota_canvas.bind(
            "<Configure>",
            lambda event: quota_canvas.itemconfigure(quota_window_id, width=event.width),
        )

        def scroll_quota_options(event) -> str:
            if event.delta:
                quota_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        def bind_quota_wheel(widget) -> None:
            widget.bind("<MouseWheel>", scroll_quota_options)
            for child in widget.winfo_children():
                bind_quota_wheel(child)

        def update_quota_limits() -> None:
            selected = {
                key for key, variable in quota_vars.items() if variable.get()
            }
            states = quota_checkbox_states(available_options[0], selected)
            for key, checkbox in quota_checks.items():
                checkbox.configure(state="normal" if states.get(key) else "disabled")
            visible_selected = selected & states.keys()
            provider_count = len({provider for provider, _ in visible_selected})
            quota_status_var.set(
                f"已选 {provider_count} 家、{len(visible_selected)} 个窗口；"
                "最多 2 家，每组最多 3 个"
            )

        def render_quota_options(
            options: Sequence[magpie_lcd.QuotaGroup],
        ) -> None:
            available_options[0] = tuple(options)
            quota_checks.clear()
            for child in quota_options_frame.winfo_children():
                child.destroy()
            if not options:
                tk.Label(
                    quota_options_frame,
                    text="Magpie 当前没有可显示的额度窗口",
                    font=font,
                    bg="#ffffff",
                    fg="#7d8b8e",
                ).pack(anchor="w")
                return
            for group in options:
                tk.Label(
                    quota_options_frame,
                    text=group.title,
                    font=("Microsoft YaHei UI", 9, "bold"),
                    bg="#ffffff",
                    fg="#263c42",
                ).pack(anchor="w", pady=(5, 2))
                for name, label in order_quota_windows(group.windows):
                    key = (group.provider, name)
                    variable = quota_vars.get(key)
                    if variable is None:
                        variable = tk.BooleanVar(value=key in selected_existing)
                        quota_vars[key] = variable
                    checkbox = tk.Checkbutton(
                        quota_options_frame,
                        text=f"{name}    {label}",
                        variable=variable,
                        command=update_quota_limits,
                        font=font,
                        bg="#ffffff",
                        activebackground="#ffffff",
                        selectcolor="#ffffff",
                        anchor="w",
                    )
                    checkbox.pack(anchor="w", padx=(16, 0), pady=1)
                    quota_checks[key] = checkbox
            bind_quota_wheel(quota_options_frame)
            update_quota_limits()

        render_quota_options(current_groups)
        quota_fetching = [False]
        quota_fetch_result: list[
            tuple[tuple[magpie_lcd.QuotaGroup, ...] | None, str | None]
        ] = []

        def fetch_quota_options() -> None:
            if closed.is_set():
                return
            if quota_fetching[0]:
                return
            quota_fetching[0] = True
            quota_fetch_result.clear()
            quota_status_var.set("正在从 Magpie 读取额度…")

            def worker() -> None:
                try:
                    payload = magpie_lcd.fetch_json(
                        f"{magpie_lcd.DEFAULT_BASE_URL}/v1/magpie/quotas",
                        timeout=20,
                    )
                    options = quota_option_groups(payload, current_groups)
                except Exception as error:
                    quota_fetch_result.append(
                        (None, f"读取失败：{type(error).__name__}: {error}")
                    )
                    return
                quota_fetch_result.append((options, None))

            threading.Thread(target=worker, daemon=True).start()
            root.after(100, poll_quota_fetch)

        def poll_quota_fetch() -> None:
            if closed.is_set():
                return
            if not quota_fetch_result:
                root.after(100, poll_quota_fetch)
                return
            options, error = quota_fetch_result.pop()
            quota_fetching[0] = False
            if error:
                quota_status_var.set(error)
                return
            render_quota_options(options or ())
            quota_status_var.set(
                f"已读取 {len(options or ())} 个供应商；窗口按 5H → 7D → 本月排序；"
                "最多选 2 个，每组最多 3 个"
            )

        tk.Button(
            quota_header,
            text="重新读取",
            font=("Microsoft YaHei UI", 8),
            command=fetch_quota_options,
            relief="solid",
            bd=1,
            padx=8,
            pady=2,
        ).pack(side="right")

        quota_canvas.bind("<MouseWheel>", scroll_quota_options)
        feedback_var = tk.StringVar()

        def run_action(button, opener) -> None:
            if button["state"] == "disabled":
                return
            button.configure(state="disabled")
            feedback_var.set("正在处理…")
            result: list[str] = []

            def worker() -> None:
                try:
                    result.append(opener())
                except Exception as error:
                    result.append(f"处理失败：{type(error).__name__}: {error}")

            threading.Thread(target=worker, daemon=True).start()

            def poll() -> None:
                if closed.is_set():
                    return
                if not result:
                    root.after(50, poll)
                    return
                feedback_var.set(result.pop())
                button.configure(state="normal")

            root.after(50, poll)

        actions = tk.Frame(outer, bg="#f4f7f7")
        actions.pack(fill="x", pady=(18, 0))
        open_config_button = tk.Button(
            actions,
            text="打开额度配置",
            font=font,
            relief="solid",
            bd=1,
            padx=12,
            pady=5,
        )
        open_config_button.configure(
            command=lambda: run_action(open_config_button, self._open_config)
        )
        open_config_button.pack(side="left")
        open_preview_button = tk.Button(
            actions,
            text="打开最新预览",
            font=font,
            relief="solid",
            bd=1,
            padx=12,
            pady=5,
        )
        open_preview_button.configure(
            command=lambda: run_action(open_preview_button, self._open_preview)
        )
        open_preview_button.pack(side="left", padx=(9, 0))
        shortcut_button = tk.Button(
            actions,
            text="创建桌面快捷方式",
            font=font,
            relief="solid",
            bd=1,
            padx=12,
            pady=5,
        )
        shortcut_button.configure(
            command=lambda: run_action(
                shortcut_button, self._create_desktop_shortcut
            )
        )
        shortcut_button.pack(side="left", padx=(9, 0))

        footer = tk.Frame(outer, bg="#f4f7f7")
        footer.pack(fill="x", side="bottom", pady=(24, 0))
        tk.Label(
            footer,
            text="停止显示会释放蓝牙，LCD 可能回到固件时钟模式。",
            font=("Microsoft YaHei UI", 8),
            bg="#f4f7f7",
            fg="#7d8b8e",
        ).pack(side="left")
        cancel = tk.Button(footer, text="取消", font=font, command=close_window, relief="solid", bd=1, padx=14, pady=5)
        cancel.pack(side="right")

        def save() -> None:
            if save_button["state"] == "disabled":
                return
            save_button.configure(state="disabled")
            feedback_var.set("正在保存…")
            try:
                interval = normalize_interval(interval_var.get())
                selected = {
                    key for key, variable in quota_vars.items() if variable.get()
                }
                quota_groups = build_quota_groups(available_options[0], selected)
                autostart = autostart_var.get()
                start_on_launch = start_var.get()
            except ValueError as error:
                feedback_var.set(f"保存失败：{error}")
                save_button.configure(state="normal")
                return

            result: list[str] = []

            def worker() -> None:
                try:
                    error = self._save_settings(
                        interval,
                        autostart,
                        start_on_launch,
                        quota_groups,
                    )
                    result.append(error or "设置已保存")
                except Exception as error:
                    result.append(f"保存失败：{type(error).__name__}: {error}")

            threading.Thread(target=worker, daemon=True).start()

            def poll() -> None:
                if closed.is_set():
                    return
                if not result:
                    root.after(50, poll)
                    return
                feedback_var.set(result.pop())
                status_var.set("设置已保存，正在刷新状态…")
                save_button.configure(state="normal")

            root.after(50, poll)

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
        tk.Label(
            footer,
            textvariable=feedback_var,
            font=("Microsoft YaHei UI", 8),
            bg="#f4f7f7",
            fg="#27664f",
        ).pack(side="right", padx=(0, 12))

        status_result: list[tuple[str, tuple[str, str], str]] = []
        status_refreshing = [False]

        def collect_status() -> None:
            try:
                status_result.append(
                    (self._status_label(), self._ble_label(), self._last_refresh_label())
                )
            except Exception as error:
                status_result.append(
                    (
                        f"状态读取失败：{type(error).__name__}",
                        ("未知", "#6b777a"),
                        "—",
                    )
                )

        def refresh_status() -> None:
            if closed.is_set():
                return
            if not status_refreshing[0]:
                status_refreshing[0] = True
                threading.Thread(target=collect_status, daemon=True).start()
            if status_result:
                status_text, ble_state, refresh_text = status_result.pop()
                status_refreshing[0] = False
                status_var.set(status_text)
                status_widgets[0].configure(text=ble_state[0], fg=ble_state[1])
                if refresh_widget is not None:
                    refresh_widget.configure(text=refresh_text)
            root.after(1000, refresh_status)

        root.after(1000, refresh_status)
        root.after(100, fetch_quota_options)
        if parent is None:
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

    def _poll_settings_requests(self) -> None:
        if self.stop_event.is_set():
            self.ui_root.destroy()
            return
        if consume_settings_request():
            self._show_settings(self.ui_root)
        self.ui_root.after(200, self._poll_settings_requests)

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
                pystray.MenuItem("创建桌面快捷方式", self._create_desktop_shortcut),
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
        import tkinter as tk

        self.ui_root = tk.Tk()
        self.ui_root.withdraw()
        self.icon.run_detached()
        if self.open_settings_on_start:
            request_settings()
        self.ui_root.after(100, self._poll_settings_requests)
        try:
            self.ui_root.mainloop()
        finally:
            self.stop_event.set()
            if self.icon is not None:
                self.icon.stop()
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
        TrayApp(open_settings_on_start=OPEN_SETTINGS_ARG in sys.argv[1:]).run()
        return 0
    except Exception as error:
        log.exception("控制器运行失败：%s", error)
        return 1
    finally:
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
