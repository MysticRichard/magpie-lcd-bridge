# Functional Specification: Desktop Tray Control

## 1. Overview

This feature adds an optional Windows tray controller for the existing Magpie LCD Bridge worker. It lets a user start, stop, refresh, configure, and exit the display bridge without opening PowerShell. The controller delegates all BLE work to the existing `magpie_lcd.py run` process; it does not replace or modify the verified image-transfer path.

## 2. User Scenarios & Testing

### User Story 1 - Control the Display from the Tray (Priority: P1)

As a Windows user, I want a tray menu that shows whether the LCD bridge is running and lets me start, stop, refresh, or exit it so that I can manage the screen without a terminal.

**Acceptance Scenarios**:

- **US1/AC1**: **Given** the controller is running and the worker is healthy, **When** the tray menu opens, **Then** it shows a running state, the active refresh interval, and the last refresh time or a concise error.
- **US1/AC2**: **Given** the worker is running, **When** the user chooses stop, **Then** the worker process exits, the BLE connection is released, and the menu changes to stopped.
- **US1/AC3**: **Given** the worker is stopped, **When** the user chooses start, **Then** one worker starts with the saved interval and the menu changes to running.
- **US1/AC4**: **Given** the worker is running, **When** the user chooses immediate refresh, **Then** the worker restarts with the saved settings and attempts a fresh frame; a brief BLE reconnect is acceptable.

### User Story 2 - Configure Refresh and Autostart (Priority: P1)

As a user, I want a settings window for the refresh interval and login startup so that I do not need to edit scheduled-task arguments.

**Acceptance Scenarios**:

- **US2/AC1**: **Given** the settings window is opened, **When** the user enters an interval from 30 to 3600 seconds and saves, **Then** the value is persisted outside the repository and a running worker is restarted with the new interval.
- **US2/AC2**: **Given** login startup is enabled, **When** the user logs in, **Then** exactly one controller starts from the current user's startup entry.
- **US2/AC3**: **Given** login startup is disabled, **When** the user logs in, **Then** no controller is registered by this feature.
- **US2/AC4**: **Given** the controller starts and automatic display is enabled, **When** the tray becomes available, **Then** the worker starts; if automatic display is disabled, the tray remains in the stopped state until the user starts it.

### User Story 3 - Reach Existing Configuration and Preview (Priority: P2)

As a user, I want the tray and settings window to open the existing quota configuration and latest preview so that the controller remains a lightweight shell around the current product.

**Acceptance Scenarios**:

- **US3/AC1**: **Given** `config.json` exists, **When** the user chooses open quota configuration, **Then** the operating system opens it in the associated editor.
- **US3/AC2**: **Given** `config.json` does not exist, **When** the user chooses open quota configuration, **Then** the controller explains that the example can be copied to `config.json`; it does not silently overwrite local configuration.
- **US3/AC3**: **Given** `last-frame.png` exists, **When** the user chooses open latest preview, **Then** the operating system opens the image.

### Edge Cases & Error Handling

- A second controller launch must not create a second worker; it should request the existing controller to show settings.
- The worker may exit unexpectedly, be killed by the user, or fail to start; the tray must describe the stopped state without crashing.
- Starting, stopping, or immediately refreshing may briefly disconnect BLE and cause the LCD firmware clock mode.
- Closing the settings window must not terminate the tray or worker.
- The controller must not change the product's default 60-second interval.
- The controller must not edit `config.json` or take over the original DA LCD Studio.

## 3. Functional Requirements

- **FR-001**: The system MUST provide a Windows tray process that starts and stops the existing long-running worker without changing the BLE protocol or rendering code.
- **FR-002**: The tray MUST expose status, start/stop, immediate refresh, settings, latest preview, quota configuration, and exit actions.
- **FR-003**: The controller MUST use one process per user session using a named Win32 mutex.
- **FR-004**: A second controller launch MUST not start another worker and SHOULD request the existing controller to show settings.
- **FR-005**: Settings MUST persist in `%LOCALAPPDATA%\MagpieLcdBridge\settings.json` and MUST NOT enter Git.
- **FR-006**: The refresh interval MUST be an integer from 30 to 3600 seconds, with 60 seconds as the default.
- **FR-007**: Changing the interval while the worker is running MUST apply by restarting the worker.
- **FR-008**: The controller MUST support a current-user `Run` startup entry and MUST NOT require administrator privileges.
- **FR-009**: The controller MUST stop its worker when it exits through the tray.
- **FR-010**: Failures to start, stop, open a file, read settings, or update the startup entry MUST be reported to the user or controller log.
- **FR-011**: The existing PowerShell lifecycle scripts MUST remain usable as a fallback.
- **FR-012**: The controller implementation MUST remain optional; `magpie_lcd.py run` must continue to work independently.

## 4. Key Entities

- **Controller Settings**: interval, login startup, and automatic display preference stored per user.
- **Worker Process**: the existing `magpie_lcd.py run --interval N` process managed by the controller.
- **Controller State**: whether the worker is running, the last observed refresh/start time, and the latest error summary.
- **Startup Entry**: the current-user registry value that launches the controller after login.

## 5. Success Criteria

- **SC-001**: A user can operate the display bridge from the tray without opening PowerShell.
- **SC-002**: The controller starts at most one worker and exits cleanly enough to release the BLE connection.
- **SC-003**: Saving a valid interval changes the worker command line and persists across controller restarts.
- **SC-004**: A second controller launch does not create a second tray or worker.
- **SC-005**: The controller remains an optional shell around `magpie_lcd.py`; existing CLI and PowerShell flows still work.
- **SC-006**: The implementation has automated checks for settings validation, command construction, and single-worker lifecycle behavior.
- **SC-007**: Public documentation explains installation, start/stop, settings, autostart migration, and fallback controls.

## 6. Assumptions & Out of Scope

- **Assumptions**:
  - The target user is on Windows with an existing working Magpie and BLE setup.
  - The user accepts a short BLE reconnect for immediate refresh and interval changes.
  - The original controller must not be installed as a second login startup source at the same time.
- **Out of Scope**:
  - Editing quota provider cards inside the tray settings window.
  - Cross-project BLE leases or automatic coordination with InkMemo/EPD.
  - Multi-device management, firmware OTA, cloud control, or a Windows service.
  - Packaging an EXE in the first Python verification iteration.
