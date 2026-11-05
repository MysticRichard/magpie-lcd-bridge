# Technical Implementation Plan: Magpie LCD Bridge

## 1. Technical Context

- **Language / Runtime**: Python 3.11-3.14; development and deployment pin Python 3.12.
- **Primary Dependencies**: Pillow for rendering and Bleak 3.0.2 for Windows BLE.
- **Storage / Database**: No database. Optional untracked `config.json`; transient logs and `last-frame.png` remain local.
- **Testing Framework**: Python `unittest`.
- **Target Platform & Constraints**: Windows BLE/WinRT; DA14585 320x240 TFT; default 60-second refresh; one controller per display.
- **Data Sources**: Magpie `GET /v1/magpie/usage?period=today` and `GET /v1/magpie/quotas` under `http://127.0.0.1:3425`.
- **Device Interface**: Image characteristic `0000ff01-0000-1000-8000-00805f9b34fb`; existing packed/delta image transfer protocol.

## 2. Constitution Check

- **Status**: PASS
- **Local Data and Privacy**: Data is fetched only through `urllib.request` from a configurable loopback endpoint; no credentials are read, and `.gitignore` excludes `config.json`, logs, and generated frames.
- **Preserve the Device**: The code implements image framing and BLE characteristic writes only. It does not include OTA or firmware modification.
- **Honest Data Presentation**: Missing quotas become unavailable rings; refresh failures preserve the prior snapshot and mark it stale.
- **Configurable, Bounded UI**: `QuotaGroup` and `QuotaWindow Configuration` drive two rows; rendering truncates each row to three rings.
- **Recoverable Unattended Operation**: `run` owns one `LcdBle` instance, bounds writes and cleanup, filters stale callbacks through connection generations, and records failures for later retries.
- **Evidence Before Claims**: Unit tests cover protocol and recovery logic; target-device checks remain separately recorded in project notes.

## 3. Project Structure & Touch-Points

```text
magpie-lcd-bridge/
  magpie_lcd.py                  # data models, HTTP reads, rendering, protocol, BLE client, CLI
  test_magpie_lcd.py             # automated regression suite
  config.example.json            # public quota configuration example
  pyproject.toml                 # Python and dependency contract
  uv.lock                        # reproducible dependency lock
  scripts/
    install-autostart.ps1        # hidden per-user scheduled task
    start-magpie-lcd.ps1
    stop-magpie-lcd.ps1
    status-magpie-lcd.ps1
    uninstall-autostart.ps1
  docs/                          # usage, configuration, compatibility, protocol, operations
  .specify/memory/constitution.md
  specs/001-magpie-lcd-bridge/
```

## 4. Data Flow and Interfaces

1. `load_quota_config()` reads the optional local configuration; built-in Codex and OpenCode Go groups are the default.
2. `read_snapshot()` runs `load_snapshot()` through `asyncio.to_thread()` so blocking HTTP work does not block the BLE event loop.
3. `load_snapshot()` reads Magpie usage and quota payloads and maps them into immutable `Snapshot`, `QuotaDisplayGroup`, and `QuotaRing` objects.
4. The renderer draws required metrics and configured quota rings into a 320x240 Pillow image and writes `last-frame.png` for preview or optional diagnostics.
5. The protocol layer encodes RGB565 data, applies PackBits or delta compression, chunks bytes into packets, calculates CRC, and sends the frame through the existing BLE characteristic.
6. `run` reuses one `LcdBle`; `connect()` explicitly scans once, passes the resulting `BLEDevice` to `BleakClient`, and uses a connection generation to ignore late callbacks.
7. BLE writes use a finite timeout; cleanup first cancels pending writes with a bounded wait, then disconnects with a bounded wait, and does not begin a new connection until cleanup completes.

### CLI Contract

- `render`: fetch data and write a local frame without BLE.
- `scan`: list local DA-LCD candidates.
- `push`: send one frame and disconnect.
- `run --interval 60`: keep the worker alive and refresh continuously.
- `--address`: select one discovered device without publishing the address.

### Configuration Contract

`config.json` contains `quota_groups`, each with `provider`, `title`, and ordered `windows`. Each window contains `name` and `label`. The application must reject malformed structures or consume them with an explicit diagnostic; absent values remain unavailable.

## 5. Phase 0: Research and Decisions

- The original controller informed the BLE framing and confirmation behavior, but its source is not copied into this project.
- Bleak 3.0.2 is selected to match the verified controller-era Windows behavior and public `BLEDevice` connection API. Connecting with a scanned device avoids an additional implicit scan.
- A single long-lived client is preferred over reconnect-per-frame because it reduces Windows BLE session churn while healthy.
- Blocking HTTP is moved off the BLE loop with `asyncio.to_thread()`.
- Full-frame transfer is retained because no public firmware evidence supports partial refresh. The 60-second default remains unchanged pending explicit product approval.
- Cross-process BLE arbitration is not implemented because the current evidence does not justify a global lock; operators must avoid concurrent bridge/controller sessions.

## 6. Phase 1: Data Model, Contracts, and Validation

- **Data Model**: Immutable configuration and snapshot dataclasses separate source identity from display labels.
- **Interface Contracts**: Four CLI modes, local JSON configuration, two Magpie endpoints, and one BLE image characteristic.
- **Rendering Validation**: Representative frames cover normal values, unavailable quotas, stale data, two rows, and three-digit costs.
- **Protocol Validation**: Tests cover packet framing, compression, CRC, confirmation behavior, timeout cleanup, device-object reuse, and callback isolation.
- **Operational Validation**: PowerShell scripts are parsed and checked against the scheduled task; a real device check confirms connection and consecutive frames.

## 7. Testing Strategy

- Run `uv run python -m unittest -v` for the full Python regression suite.
- Run `uv run python -m py_compile magpie_lcd.py test_magpie_lcd.py` for syntax.
- Run `uv lock --check` to verify dependency resolution.
- Parse the PowerShell lifecycle scripts before packaging changes.
- For rendering and BLE changes, compare `last-frame.png` and perform a target-device push or short run.
- Keep automated-test success, BLE-send success, visible display confirmation, and long-term stability as separate evidence levels.

## 8. Deployment, Recovery, and Known Limits

- Install the per-user hidden scheduled task with `scripts/install-autostart.ps1`; use start/stop/status/uninstall scripts for lifecycle control.
- If the display is discoverable but GATT service discovery repeatedly times out, preserve logs and first stop known competing BLE workers. A user-controlled Windows Bluetooth toggle is a documented recovery experiment, not a proven root-cause fix.
- If the display stops advertising, power-cycle the display and observe whether the existing worker reconnects.
- The screen may show its firmware clock after an intentional disconnect or process stop.
- Long-running DA14585 stability and simultaneous BLE activity from unrelated projects remain operational risks, not solved guarantees.
