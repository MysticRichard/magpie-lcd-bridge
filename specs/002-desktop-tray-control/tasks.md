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

## 2026-11-06 登录自启修复

- 批准：用户明确批准隐藏登录任务迁移；InkMemo 已交由其独立窗口处理，当前窗口仅修改 LCD。
- 已知良好基线：`8bb65ef checkpoint: 部署跨项目 BLE 租约`；保留 60 秒间隔、UI、worker 和租约协议。
- [x] T017 [FR-008, FR-010, SC-006, SC-007] 统一托盘及安装/卸载脚本的 PowerShell ScheduledTasks 实现；隔离验证注册、读取、禁用、删除及失败保留旧 Run 值。完成日期：2026-11-06；38 项测试、语法和 PowerShell 解析通过；隔离真实任务未启动，验证缺失→启用→禁用→删除→重复关闭。已修正“查询不存在任务”误报非零退出码；注册失败保留旧 Run 的回归通过。
- [ ] T018 [US2/AC2, US2/AC3, FR-008] 部署新版 LCD 控制器，核对唯一启动源和实际发送；在用户方便时完成真实注销/登录验收。状态：部署和手动运行已通过，真实登录验收待执行；系统本次启动早于任务注册，不能以手动启动任务代替登录验收。

### T018 现场记录

- 2026-11-06：正式任务已注册并手动启动；旧 `Magpie LCD Bridge Control` Run 值和旧 worker 任务均不存在。正式任务 Hidden/Enabled、Interactive/Limited、LogonTrigger 和工作目录均核对通过。
- 09:26:49—09:41:52 日志连续发送；之后出现外部暂停。租约状态查询收到认证失败，已告知负责 InkMemo 的窗口；当前窗口不改租约协议或对方工程。
- 09:55:26 已重启 LCD 控制器加载新代码，09:55:37 新 worker 完成图片发送；手动任务拉起和 BLE 发送通过，真实注销/登录仍未验证，T018 不勾选。
- 租约 `status` 认证失败在此次重启后仍可复现，属于独立待排查项，不能以本次发送成功宣称跨项目共存已通过；未修改租约实现，已将现场信息交给负责 InkMemo 的窗口。
- 2026-11-09 09:27：正式任务 `Magpie LCD Bridge Controller` 为 Running、Enabled、Hidden、Interactive/Limited，唯一触发器为 `AtLogOn`；旧 Run 值和旧 worker 任务均不存在。
- 2026-11-09 09:18:27—09:27:17 日志连续发送成功；控制器与 worker 均为 Running，用户反馈“目前没有任何问题了”。
- 当前 Windows 自 2026-11-07 启动，任务于 2026-11-09 注册并手动启动；因此本次没有发生任务注册后的真实注销/登录，T018 继续保持未完成。
