# Implementation Backlog: Desktop Tray Control

## Phase 1: Setup

- [x] T001 [P] Add the `pystray` runtime dependency and refresh `uv.lock` in `pyproject.toml`.
- [x] T002 [P] Confirm local-only controller settings stay outside Git under `%LOCALAPPDATA%` and controller logs are covered by `*.log`.

## Phase 2: Controller Foundation

- [x] T003 Implement bounded interval normalization, settings persistence, and worker command construction in `magpie_lcd_control.py` (covers FR-005, FR-006, FR-007).
- [x] T004 Implement hidden worker process start, stop, restart, and error state in `magpie_lcd_control.py` (covers FR-001, FR-003, FR-009, FR-010).
- [x] T005 Implement single-controller mutex and settings-request handling in `magpie_lcd_control.py` (covers FR-003, FR-004, SC-004).
- [x] T006 Implement current-user startup read/write helpers in `magpie_lcd_control.py` (covers FR-008).

## Phase 3: User Interface

- [x] T007 Implement the tray menu and status labels in `magpie_lcd_control.py` (covers FR-002, FR-010).
- [x] T008 Implement the settings window with interval, autostart, automatic display, preview, and config actions in `magpie_lcd_control.py` (covers FR-002, FR-005, FR-006, FR-008).
- [x] T009 Add start, stop, status, install-startup, and uninstall-startup PowerShell wrappers in `scripts/*.ps1` (covers FR-002, FR-008, FR-011, FR-012).

## Phase 4: Verification and Documentation

- [x] T010 Add controller tests for settings, interval validation, worker command construction, and fake process lifecycle in `test_magpie_lcd_control.py` (covers SC-006).
- [x] T011 Add controller setup, migration, operation, and fallback documentation in `docs/controller.md` and `README.md` (covers SC-007).
- [x] T012 Run the full Python suite, syntax checks, lock check, whitespace check, and sensitive-data scan.
- [ ] T013 Manually verify the tray icon, start/stop, immediate refresh, settings, preview/config links, and exit on the target Windows desktop (covers SC-001, SC-002, SC-003, SC-004).
- [ ] T014 Verify the worker releases BLE after stopping and sends a frame after restarting on the target device; record the separate device evidence.
- [ ] T015 Verify the current-user startup entry after explicit user approval and do not leave the old scheduled task and new startup entry both enabled.
- [x] T016 [P] Confirm the existing `magpie_lcd.py run` CLI and legacy PowerShell scripts remain available as fallback and document the compatibility boundary (covers FR-012, SC-005).
