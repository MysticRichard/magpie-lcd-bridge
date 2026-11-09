# Technical Implementation Plan: Desktop Tray Control

## 1. Technical Context

- **Language / Runtime**: Python 3.11-3.14, Windows-first, project virtual environment with `pythonw.exe`.
- **UI Dependencies**: `pystray` for the tray icon and Tkinter/ttk from the standard library for the settings window.
- **Process Model**: One tray controller process plus one child `magpie_lcd.py run` worker.
- **Persistence**: `%LOCALAPPDATA%\MagpieLcdBridge\settings.json`; logs remain under the repository `logs/` directory and stay ignored.
- **Windows Integration**: Named mutex for one controller per session and current-user `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` for login startup.
- **Testing**: Python `unittest` with fake process and settings paths.

## 2. Constitution Check

- **Status**: PASS
- **Local Data and Privacy**: The controller manages local processes only; it does not read Magpie credentials or add network access.
- **Preserve the Device**: BLE rendering, transfer, and firmware behavior remain in the existing worker.
- **Honest Data Presentation**: The tray does not display a synthetic usage value; it only reports worker lifecycle state.
- **Configurable, Bounded UI**: Interval settings are bounded to 30-3600 seconds and quota configuration remains in the existing `config.json`.
- **Recoverable Unattended Operation**: The controller can start, stop, restart, and exit the worker; a second launch is blocked by a named mutex.
- **Evidence Before Claims**: Tests cover settings and process lifecycle; actual tray behavior, BLE release, and login startup remain separate target-device checks.

## 3. Project Structure & Touch-Points

```text
magpie-lcd-bridge/
  magpie_lcd_control.py          # tray controller, settings, worker lifecycle
  test_magpie_lcd_control.py     # controller regression tests
  pyproject.toml                 # add pystray dependency
  scripts/
    start-controller.ps1
    stop-controller.ps1
    status-controller.ps1
    install-controller-autostart.ps1
    uninstall-controller-autostart.ps1
  docs/controller.md
  specs/002-desktop-tray-control/
```

The existing `magpie_lcd.py`, BLE protocol, renderer, `config.json` schema, and current PowerShell worker scripts are not refactored as part of this feature.

## 4. Data Flow and Interfaces

1. The controller loads local settings, acquires the named controller mutex, and checks the current-user startup state.
2. It builds a worker command using the current Python executable and the saved interval, then starts `magpie_lcd.py run --interval N` as a hidden child process.
3. The tray reads the child process state and displays a status label.
4. Start/stop actions invoke the worker manager. Immediate refresh and interval changes stop and restart the worker so the new command is applied.
5. The settings window writes settings atomically outside the repository and updates the hidden current-user logon task through PowerShell ScheduledTasks.
6. When the user exits, the controller stops the worker and then stops the tray icon.

### Controller Menu Contract

- Status line: running/stopped, interval, latest event/error.
- `立即刷新`: restart the worker with the saved interval.
- `设置`: open the modeless settings window.
- `打开最新预览`: open `last-frame.png`.
- `打开额度配置`: open `config.json`; if absent, show an instructional message without writing local config.
- `停止显示` / `启动显示`: toggle the worker.
- `退出控制器`: stop the worker and exit.

## 5. Phase 0: Research and Decisions

- Follow the existing pattern for `pystray`, Tkinter settings, and a named mutex. The original `HKCU\Run` startup mechanism is superseded by the approved 2026-11-06 logon-task migration.
- Use a child process rather than moving the asyncio BLE loop into the tray process; this preserves the previously verified worker behavior.
- Use a local request file to make a second launch open the existing settings window.
- Keep the current worker PowerShell scripts as a fallback until the tray path is accepted.

## 6. Implementation Phases

### Phase 1: Settings and Worker Lifecycle

- Add a settings dataclass with atomic local persistence.
- Add interval normalization and worker command construction.
- Add a worker manager with bounded terminate/kill behavior and a fakeable process factory.

### Phase 2: Tray and Settings UI

- Add the pystray menu and a small Tkinter settings window.
- Add start/stop, immediate refresh, preview/config links, and exit.
- Add single-instance and settings-request handling.
- Add current-user startup read/write helpers.

### Phase 3: Scripts and Documentation

- Add PowerShell wrappers for manual control and optional login startup.
- Document migration from the existing scheduled task without silently registering two startup paths.
- Add automated regression tests and run the existing suite.

## 7. Testing Strategy

- `uv run python -m unittest -v` for the existing bridge plus controller tests.
- `uv run python -m py_compile magpie_lcd.py magpie_lcd_control.py`
- `uv lock --check` and `git diff --check`.
- Manual first-run check: launch via `pythonw`, verify one tray icon, start/stop, settings, preview/config links, and exit.
- Target-device check: after stopping the worker, confirm BLE is released and the LCD may return to clock mode; start again and confirm a frame is sent.
- Login startup check: verify exactly one startup entry exists, then test the user-facing logon path separately.

## 2026-11-06 Autostart Repair

- Evidence: Windows logged in at 09:01:53; Shell enumerated Run commands but did not execute the LCD entry. Paths and imports were valid; the precise reason for the omission remains unknown.
- Use the already verified `Register-ScheduledTask` interface, not `schtasks.exe /Create`, which returned access denied in this user session.
- Both the tray helper and scripts configure `Magpie LCD Bridge Controller`: current-user logon trigger, Interactive/Limited principal, hidden, battery allowed, IgnoreNew, 3650-day runtime limit, explicit executable/arguments/working directory.
- Encode the PowerShell command as UTF-16LE Base64 and quote paths as literal strings. Capture errors and propagate them to the existing settings error path; retain the legacy Run value if registration fails.
- Disable removes the startup task without stopping the current controller. Read state reflects disabled tasks as off. Remove the legacy Run value only after a successful operation.
- Verify create/read/disable/delete on an isolated task without launching it; then verify the real task and frame logs. Actual logout/login and user-visible acceptance remain separate.
- Rollback: uninstall the new controller task, restore the previous controller startup implementation if needed, or use the existing manual start script. Do not enable the legacy worker task alongside the controller.
- InkMemo changes and deployment are owned by the other authorized chat; this repair does not modify its files, processes, or tasks.

## 8. Deployment, Recovery, and Known Limits

- The controller is source-first for this iteration; EXE packaging is deferred until UI and lifecycle behavior are accepted.
- If the old `Magpie LCD Bridge` scheduled task is present, the user must remove it before enabling controller startup to avoid two startup sources.
- Force-stopping the controller from PowerShell stops both the controller and its worker; normal tray exit is preferred.
- A stopped worker may leave the LCD in clock mode because the device firmware does not guarantee frame retention.
- Cross-project BLE contention remains outside this feature; no automatic global BLE lease is introduced.
