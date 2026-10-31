# BLE Reconnect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the hidden Magpie LCD runner from hanging on a broken BLE write and make it retry the device connection quickly.

**Architecture:** Keep the existing `LcdBle` and scheduled-task architecture. Bound each GATT write, clear connection state on disconnect/failure, and choose a short retry delay after a failed refresh. Route hidden-task logs to an ignored local file.

**Tech Stack:** Python 3.12, asyncio, Bleak, Pillow, PowerShell Scheduled Tasks, unittest.

**Spec:** `docs/superpowers/specs/2026-10-31-ble-reconnect-design.md`

## Global Constraints

- Keep `push` one-shot: it sends one frame and exits.
- Keep the DA14585 image protocol and existing 320x240 rendering unchanged.
- Do not add third-party dependencies.
- Do not commit `config.json`, Bluetooth addresses, logs, screenshots, or local virtual environments.

## Review Focus

- A GATT write that never completes must time out instead of pinning `run`.
- A disconnected client must be cleared before the next reconnect attempt.
- A BLE failure must not wait for the entire 60-second refresh interval before retrying.
- The scheduled task must remain hidden and must write diagnostics without exposing credentials.
- Existing `push` behavior must not silently change into a persistent process.

### Task 1: BLE timeout and reconnect timing

**Files:**
- Modify: `magpie_lcd.py`
- Test: `test_magpie_lcd.py`

**Interfaces:**
- `LcdBle(address: str | None = None, write_timeout: float = BLE_WRITE_TIMEOUT)`
- `refresh_delay(interval: int, failed: bool) -> int`

- [ ] **Step 1: Add failing tests** for a hanging fake GATT write raising `asyncio.TimeoutError`, for `refresh_delay(60, True) == 10`, and for `refresh_delay(60, False) == 60`.
- [ ] **Step 2: Run the focused tests** and confirm they fail because the timeout and delay interfaces do not exist.
- [ ] **Step 3: Implement the minimum timeout, disconnect-state cleanup, and retry-delay logic in `magpie_lcd.py`.
- [ ] **Step 4: Run the focused tests** and confirm they pass.
- [ ] **Step 5: Run the complete unittest suite** and confirm no regressions.

### Task 2: Silent-task diagnostics and documentation

**Files:**
- Modify: `scripts/install-autostart.ps1`
- Modify: `README.md`
- Modify: `docs/operations.md`
- Modify: `.gitignore`

**Interfaces:**
- Scheduled task arguments include `--log-file "logs\magpie-lcd.log"`.
- `main()` accepts the optional `--log-file` path and configures file logging.

- [ ] **Step 1: Update the hidden task action and ignored local paths.
- [ ] **Step 2: Document the distinction between `push` and `run`, retry behavior, and the log location.
- [ ] **Step 3: Reinstall the task and inspect its command, hidden flag, and running state.

### Task 3: End-to-end verification

**Files:**
- No new production files.

- [ ] **Step 1: Run the complete unittest suite and PowerShell parser checks.
- [ ] **Step 2: Stop and start the existing task using the project scripts.
- [ ] **Step 3: Verify the task is hidden, the process is alive, and `logs/magpie-lcd.log` receives startup/connection diagnostics.
- [ ] **Step 4: Record any physical-device behavior that remains unverified.
