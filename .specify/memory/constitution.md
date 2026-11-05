<!--
Sync Impact Report
- Version change: N/A -> 1.0.0
- Modified principles: initial ratification
- Added sections: project vision, core principles, design constraints, development workflow, governance
- Removed sections: none
- Follow-up items: none
-->

# Project Constitution: Magpie LCD Bridge

## 1. Project Vision

Magpie LCD Bridge converts usage and quota data from Magpie's local interface into a compact dashboard for a DA14585-based 320x240 BLE TFT display. The project MUST remain a local, independently maintained bridge rather than a replacement controller or firmware project.

## 2. Core Principles

### Local Data and Privacy

The application MUST read only the configured local Magpie interface. It MUST NOT collect Magpie credentials, cookies, account identity, or API keys. It MUST NOT upload usage data to an external service. Public repository content MUST NOT contain real BLE addresses, user configuration, runtime logs, or generated user frames.

### Preserve the Device

The application MUST use the existing image-transfer protocol exposed by the device firmware. It MUST NOT flash, modify, or replace firmware as part of normal operation, and it MUST NOT claim ownership of the original controller or firmware implementation.

### Honest Data Presentation

Every rendered value MUST come from a successful local data read or an explicitly identified cached snapshot. Missing quota values MUST be shown as unavailable rather than inferred or fabricated. Failed refreshes MUST keep the previous snapshot visibly marked as stale instead of presenting it as current.

### Configurable, Bounded UI

Quota providers, titles, window names, and short labels MUST be configuration-driven. The implemented screen contract is two quota rows with at most three windows per row. Layout changes MUST preserve readable spacing, accurate percentage rings, and the current 320x240 target.

### Recoverable Unattended Operation

The default long-running mode MUST keep one BLE connection while healthy, recover from disconnects, bound individual BLE write and cleanup waits, and keep the worker alive for later retries. Windows login startup, manual start, stop, status, and uninstall MUST remain available without requiring a visible console.

### Evidence Before Claims

Code changes MUST include applicable automated checks. Changes to rendering, BLE behavior, autostart, or packaging MUST additionally be checked on the target Windows environment when available. Unit tests, a running process, and a successful BLE frame are separate evidence levels. Long-term hardware stability MUST NOT be inferred from a short successful run.

## 3. Design Constraints

- Target platform: Windows with a working BLE/WinRT stack.
- Runtime: Python 3.11 through 3.14; the repository pins Python 3.12 for development.
- Device target: DA14585, 320x240 TFT, image characteristic `0000ff01-0000-1000-8000-00805f9b34fb`.
- Default local data source: `http://127.0.0.1:3425`.
- Default refresh interval: 60 seconds. Changing this product default requires explicit approval.
- The project MUST remain usable without a tray application or external database.
- The original controller and firmware author, and the hardware source, MUST remain acknowledged in the public project documentation.
- The screen MAY return to firmware clock mode after BLE disconnect or process exit; retaining the final frame is not a guaranteed capability.

## 4. Development Workflow and Quality Gates

- Every feature or behavior change MUST identify its functional requirements and acceptance evidence.
- Non-trivial logic MUST have a repeatable automated test or an explicit target-device check when automation is not practical.
- Before completion, the applicable subset of unit tests, syntax checks, dependency-lock checks, documentation-link checks, sensitive-data scans, and target-device checks MUST be recorded.
- Infrastructure and device actions MUST be separated from code verification: a successful build does not prove a BLE transfer, a BLE transfer does not prove user-visible correctness, and a user-visible success does not prove long-term stability.
- Changes to hardware behavior MUST preserve a safe fallback such as stopping the bridge, restarting the Windows Bluetooth stack, or power-cycling the display; automatic driver changes or firmware writes are outside the normal workflow.

## 5. Governance and Amendments

- **Constitution Version**: 1.0.0
- **Ratification Date**: 2026-11-04
- **Last Amended Date**: 2026-11-04
- **Amendment Process**: A constitution change MUST state the affected principle, rationale, migration impact, and verification plan. Breaking changes increment MAJOR, new principles or sections increment MINOR, and wording-only changes increment PATCH.
- **Compliance Review**: Every feature plan MUST include a Constitution Check. Any deviation from a MUST principle blocks implementation until the principle is amended or the plan is changed.
