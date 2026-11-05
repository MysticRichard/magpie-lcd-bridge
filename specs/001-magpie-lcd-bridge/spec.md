# Functional Specification: Magpie LCD Bridge

## 1. Overview

This feature provides a Windows-local bridge that reads AI usage and quota data from Magpie and displays a compact dashboard on a DA14585-based 320x240 BLE TFT screen. It serves users who want an always-visible desktop summary without modifying the display firmware or exposing account data.

The delivered baseline includes local rendering, one-shot and long-running BLE modes, configurable quota groups, Windows login startup, manual lifecycle controls, diagnostics, public documentation, and hardware/firmware attribution.

## 2. User Scenarios & Testing

### User Story 1 - View Local Usage and Quotas (Priority: P1)

As a Windows user running Magpie, I want the connected LCD to show today's AI usage and remaining quota so that I can understand my usage without opening another window.

**Acceptance Scenarios**:

- **US1/AC1**: **Given** Magpie is running and returns usage and quota data, **When** one refresh completes, **Then** the screen shows today's token total, reference cost, cache-hit rate, and the configured quota rings.
- **US1/AC2**: **Given** a local render succeeds, **When** the generated frame is inspected, **Then** it is 320x240, every required value and ring remains inside the frame, and quota labels do not overlap their rings.
- **US1/AC3**: **Given** Magpie cannot be read after a previous successful refresh, **When** the next frame is rendered, **Then** the prior values remain visible with a stale-data indication.

### User Story 2 - Configure Quota Providers (Priority: P1)

As a user of different AI providers, I want to map provider IDs and quota windows to two display rows so that the screen reflects my own subscriptions.

**Acceptance Scenarios**:

- **US2/AC1**: **Given** a valid local configuration, **When** the dashboard renders, **Then** provider title, window matching, order, and short labels come from that configuration.
- **US2/AC2**: **Given** more than three windows are configured for one row, **When** the dashboard renders, **Then** only the first three are shown without breaking the layout.
- **US2/AC3**: **Given** a configured provider or window is absent, **When** the dashboard renders, **Then** the affected ring shows unavailable instead of a fabricated percentage.

### User Story 3 - Run Unattended on Windows (Priority: P2)

As a user, I want the bridge to start after Windows login, run without a console window, and provide explicit start, stop, status, and uninstall controls so that it can coexist with the original controller.

**Acceptance Scenarios**:

- **US3/AC1**: **Given** autostart is installed, **When** the current user logs in, **Then** the hidden scheduled task starts the bridge with `run --interval 60`.
- **US3/AC2**: **Given** the bridge is running, **When** the user requests status, **Then** the task state, recent run time, and bridge process state are reported.
- **US3/AC3**: **Given** the user stops the bridge, **When** the process exits, **Then** the BLE connection is released and the device may return to its firmware clock mode.

### User Story 4 - Recover from BLE Failures (Priority: P2)

As a user, I want the long-running bridge to recover from ordinary disconnects and timeouts without terminating the worker so that the display can resume automatically.

**Acceptance Scenarios**:

- **US4/AC1**: **Given** a BLE write or connection fails, **When** the failure is handled, **Then** stale connection state is cleaned up and a later refresh attempts to reconnect.
- **US4/AC2**: **Given** the bridge reconnects, **When** two consecutive frames are sent successfully, **Then** the worker remains running and the user can confirm the physical display is current.
- **US4/AC3**: **Given** the display remains discoverable but GATT connection repeatedly times out, **When** local isolation has ruled out known competing processes, **Then** the documented recovery path may use a Windows Bluetooth toggle; this does not establish the root cause.

### Edge Cases & Error Handling

- Magpie is not running, returns malformed data, or times out.
- The configured provider or quota window does not exist.
- The cost grows from two digits to three or more digits.
- No DA-LCD device is found, multiple candidates are found, or an explicitly requested address is absent.
- DA LCD Studio or another BLE worker holds the device or adapter.
- The screen disconnects, remains discoverable but rejects GATT service discovery, or stops advertising.
- A write exceeds its timeout, a connection callback arrives after cleanup, or disconnect cleanup itself stalls.
- The bridge process stops; the screen may return to firmware clock mode.

## 3. Functional Requirements

- **FR-001**: The system MUST read usage and quota data only from the configured local Magpie HTTP interface; the default endpoint MUST be `http://127.0.0.1:3425`.
- **FR-002**: The dashboard MUST display today's token total, reference cost, cache-hit percentage, and quota rings in the current 320x240 layout.
- **FR-003**: The system MUST support two quota rows and MUST render at most three configured windows per row.
- **FR-004**: Quota provider IDs, titles, source window names, short labels, and row order MUST be configurable without editing application code.
- **FR-005**: Missing local data or quota values MUST be rendered as unavailable or stale; the system MUST NOT invent a value.
- **FR-006**: The system MUST generate a frame for the target 320x240 display and MUST use the existing firmware image-transfer behavior without flashing or modifying firmware.
- **FR-007**: The system MUST provide a local preview mode that writes a frame without opening a BLE connection.
- **FR-008**: The system MUST provide a one-shot push mode that sends one frame and then disconnects.
- **FR-009**: The system MUST provide a long-running mode that maintains the BLE connection while healthy, refreshes every 60 seconds by default, and keeps retrying after recoverable failures.
- **FR-010**: BLE writes and cleanup steps MUST have finite waits so that one stalled operation does not block all future refreshes indefinitely.
- **FR-011**: A late disconnect callback from an old connection MUST NOT clear the state of a newer connection.
- **FR-012**: The system MUST write actionable connection, send, timeout, and recovery events to a local log.
- **FR-013**: The system MUST provide install, start, stop, status, and uninstall scripts for a per-user hidden Windows scheduled task.
- **FR-014**: Manual start and stop MUST allow the user to release BLE before using the original controller.
- **FR-015**: The public project MUST exclude credentials, real BLE addresses, user configuration, logs, and generated user frames.
- **FR-016**: Public documentation MUST cover setup, usage, configuration, compatibility, device/protocol boundaries, operations, troubleshooting, and the original firmware/controller and hardware-source acknowledgements.

## 4. Key Entities

- **Usage Snapshot**: A local point-in-time record containing token total, cost in CNY, cache-hit rate, quota display groups, and update time.
- **Quota Group**: A display row identity containing provider ID, display title, and an ordered list of configured quota windows.
- **Quota Window Configuration**: The Magpie source name and short display label for one ring.
- **Quota Ring**: A rendered percentage or unavailable state mapped to one configured window.
- **Local Configuration**: The untracked `config.json` containing quota groups and optional runtime settings.
- **BLE Device Candidate**: A discovered device with a display name and underlying device object; its address remains local.

## 5. Success Criteria

- **SC-001**: A valid local run produces a decodable 320x240 frame containing all four required metric areas and both quota rows without overlap at representative values, including a three-digit cost.
- **SC-002**: Configuration changes can alter both rows, provider selection, window order, and labels without source edits; more than three windows per row are safely truncated.
- **SC-003**: The long-running mode reuses one connection during normal refreshes and uses a default interval of 60 seconds.
- **SC-004**: A simulated or observed write timeout does not crash the worker, and subsequent refresh attempts remain possible.
- **SC-005**: The hidden scheduled task and lifecycle scripts can start, report, stop, and remove the bridge without opening a console window.
- **SC-006**: The automated suite covers protocol encoding, quota mapping, rendering, timeout cleanup, device-object reuse, callback isolation, background reads, and retry timing; all tests pass.
- **SC-007**: Public documentation contains runnable setup and operational instructions and distinguishes firmware/controller authorship from hardware sourcing.
- **SC-008**: Repository scans find no credentials, real BLE address, local configuration, runtime log, or generated user frame.

## 6. Assumptions & Out of Scope

- **Assumptions**:
  - Magpie and the target local API are already installed and running.
  - The target display implements the verified image characteristic and transfer protocol.
  - Windows is the supported host; Python, the Windows fonts, and the required BLE stack are available.
  - The user accepts approximately 60-second refreshes rather than second-level updates.
- **Out of Scope**:
  - Modifying or replacing firmware, performing OTA, or reproducing the original controller.
  - macOS, Linux, WSL, Android, or mobile support.
  - Route status, network access history, historical charts, multi-page rotation, or a multi-device tray application; F002 defines the optional single-device controller.
  - Multiple simultaneous controllers for the same display.
  - A guarantee that the final frame remains visible after BLE disconnect.
  - Permanent elimination of DA14585 or cross-project BLE stability failures; these require continued target-device observation and, if needed, a new feature specification.
