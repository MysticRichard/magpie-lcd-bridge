# Implementation Backlog: Magpie LCD Bridge

## Phase 1: Setup

- [x] T001 [P] Establish the Python project metadata and Bleak/Pillow dependency contract in `pyproject.toml` (supports FR-006, FR-009).
- [x] T002 [P] Add local-only ignore rules for virtual environments, generated frames, logs, and `config.json` in `.gitignore` (covers FR-015, SC-008).

## Phase 2: Foundational

- [x] T003 Implement immutable usage snapshot and quota configuration models in `magpie_lcd.py` (covers FR-004).
- [x] T004 Implement local Magpie usage and quota retrieval with stale-snapshot behavior in `magpie_lcd.py` (covers FR-001, FR-005).
- [x] T005 Implement the RGB565 frame encoder, packet framing, CRC, and existing BLE image protocol in `magpie_lcd.py` (covers FR-006).

## Phase 3: User Story 1 - View Local Usage and Quotas (Priority: P1)

**Goal**: Render the required local metrics on the target 320x240 dashboard.
**Independent Test Criteria**: Generate a representative frame and verify required metrics, quota rings, unavailable states, and a three-digit cost without overlaps.

- [x] T006 [US1] Implement the 320x240 dashboard renderer and local `render` mode in `magpie_lcd.py` (covers FR-002, FR-007, SC-001).
- [x] T007 [US1] Implement cost sizing, quota-ring layout, and stale-data indicators in `magpie_lcd.py` (covers FR-002, FR-005, SC-001).
- [x] T008 [US1] Add renderer regression checks for representative values, missing quotas, and three-digit costs in `test_magpie_lcd.py` (covers FR-002, SC-001).

## Phase 4: User Story 2 - Configure Quota Providers (Priority: P1)

**Goal**: Drive two quota rows from local provider and window configuration.
**Independent Test Criteria**: Change the example configuration and verify row titles, labels, ordering, and truncation without source edits.

- [x] T009 [US2] Implement quota configuration loading and provider/window mapping in `magpie_lcd.py` (covers FR-003, FR-004).
- [x] T010 [P] [US2] Publish the configurable Codex and OpenCode Go schema in `config.example.json` (covers FR-004, SC-002).
- [x] T011 [US2] Add quota mapping, unknown-window, and configuration behavior tests in `test_magpie_lcd.py` (covers FR-003, FR-005, SC-002).
- [x] T012 [US2] Document configuration fields and troubleshooting in `docs/configuration.md` (covers FR-004, FR-016).

## Phase 5: User Story 3 - Run Unattended on Windows (Priority: P2)

**Goal**: Support hidden Windows startup and explicit manual lifecycle control.
**Independent Test Criteria**: Install, start, inspect, stop, and uninstall the hidden task while releases remain possible.

- [x] T013 [US3] Implement `render`, `scan`, `push`, and long-running `run` modes in `magpie_lcd.py` (covers FR-007, FR-008, FR-009, SC-003).
- [x] T014 [US3] Implement install, start, stop, status, and uninstall lifecycle scripts in `scripts/*.ps1` (covers FR-013, FR-014, SC-005).
- [x] T015 [US3] Configure the scheduled task to use hidden `pythonw.exe` with `run --interval 60` in `scripts/install-autostart.ps1` (covers FR-009, FR-013, SC-003, SC-005).
- [x] T016 [P] [US3] Document Windows startup, manual controls, logs, and recovery in `docs/usage.md` (covers FR-013, FR-016, SC-005).

## Phase 6: User Story 4 - Recover from BLE Failures (Priority: P2)

**Goal**: Keep the worker alive and retry after ordinary BLE failures without stale-session interference.
**Independent Test Criteria**: Simulate timeout, reconnect, and late callback behavior; verify bounded cleanup, retry, and consecutive sends on the target device.

- [x] T017 [US4] Implement bounded BLE writes, pending-write cleanup, disconnect waits, and retry delay in `magpie_lcd.py` (covers FR-010, SC-004).
- [x] T018 [US4] Implement scanned-device reuse, explicit single-scan reconnect, and connection-generation callback isolation in `magpie_lcd.py` (covers FR-011, SC-004).
- [x] T019 [US4] Move Magpie HTTP reads off the BLE event loop in `magpie_lcd.py` (covers FR-001, FR-009).
- [x] T020 [US4] Add timeout, device-object, stale-callback, background-read, and retry-timing tests in `test_magpie_lcd.py` (covers FR-010, FR-011, SC-004, SC-006).
- [x] T021 [US4] Record BLE recovery behavior and known limits in `docs/operations.md` (covers FR-012, FR-016, SC-007).

## Phase 7: Polish and Cross-Cutting Concerns

- [x] T022 [P] Document setup, use cases, limitations, protocol, and device conditions in `README.md` and `docs/*.md` (covers FR-016, SC-007).
- [x] T023 [P] Publish MIT licensing and firmware/controller/hardware-source acknowledgements in `LICENSE` and `NOTICE.md` (covers FR-016, SC-007).
- [x] T024 Run the 19-item automated suite, syntax check, dependency lock check, Git whitespace check, and sensitive-data scan against `test_magpie_lcd.py`, `magpie_lcd.py`, and repository documentation (covers FR-015, SC-006, SC-008).
- [x] T025 Verify the target device receives consecutive frames and record user-visible recovery evidence in `问题档案.md` in the project knowledge base (covers FR-009, SC-003, SC-004).
- [x] T026 Establish the project constitution and active feature baseline in `.specify/memory/constitution.md` and `specs/001-magpie-lcd-bridge/` (covers FR-016, SC-007).
- [ ] T027 Run a multi-hour low-pressure LCD soak test while logging concurrent EPD activity using `magpie_lcd.py run --interval 300` (validates residual risk for FR-009).
- [ ] T028 Verify real Windows logout/login autostart behavior using `scripts/install-autostart.ps1` and `scripts/status-magpie-lcd.ps1` (validates FR-013).

## Dependencies & Execution Strategy

- **Story Order**: Phase 1 -> Phase 2 -> US1 and US2 (MVP) -> US3 -> US4 -> Polish.
- **Parallel Opportunities**: T001/T002, T010/T016, T022/T023, and independent test authoring may run in parallel when files do not overlap.
- **MVP Scope**: US1 plus US2 provides the local dashboard and configurable quota display.
- **Remaining Validation**: T027 and T028 are operational verification tasks; their incompleteness does not describe new unimplemented product behavior.
