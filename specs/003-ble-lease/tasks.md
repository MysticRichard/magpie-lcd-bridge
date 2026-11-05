# 实施任务：跨项目 BLE 租约

## 阶段 1：LCD 租约基础设施

- [x] T001 [P] [US1] 在 `ble_lease.py` 实现租约数据模型、TTL、token、owner 冲突和恢复语义（覆盖 FR-001、FR-002、FR-003、FR-004、FR-005、FR-006）。
- [x] T002 [P] [US1] 在 `ble_lease.py` 实现认证命名管道服务与客户端请求契约（覆盖 FR-001、FR-002、FR-011）。
- [x] T003 [US1] 在 `test_magpie_lcd_control.py` 添加申请、冲突、心跳、释放、超时与错误 token 测试（覆盖 SC-001）。

## 阶段 2：托盘集成

- [x] T004 [US2] 在 `magpie_lcd_control.py` 启动/停止租约服务，并在托盘状态中显示外部占用（覆盖 FR-007）。
- [x] T005 [US2] 在 `magpie_lcd_control.py` 阻止外部租约期间手动启动或重启 worker（覆盖 FR-007）。
- [x] T006 [P] [US2] 在 `test_magpie_lcd_control.py` 添加托盘阻断测试（覆盖 SC-001）。

## 阶段 3：墨笺客户端

- [x] T007 [P] [US3] 在 `src/inkmemo/ble/lease.py` 实现租约上下文、心跳、busy 和不可用语义（覆盖 FR-008、FR-009、FR-010）。
- [x] T008 [US3] 在 `src/inkmemo/ble/client.py` 将全部 BLE 重试包在租约内（覆盖 FR-008、FR-009）。
- [x] T009 [US3] 在 `src/inkmemo/__main__.py` 将扫描命令包在租约内（覆盖 FR-008）。
- [x] T010 [US3] 在 `src/inkmemo/runtime.py` 区分 busy 并通知用户（覆盖 FR-010）。
- [x] T011 [P] [US3] 在 `tests/test_ble_lease.py` 添加成功、busy、不可用、心跳和 finally 释放测试（覆盖 SC-002、SC-003）。

## 阶段 4：文档与收口

- [x] T012 [P] 在 `docs/ble-coordination.md` 和 `docs/controller.md` 记录协议、配置、限制和排障（覆盖 FR-011）。
- [x] T013 [P] 在墨笺 `docs/user-guide.md` 记录与 LCD 共用蓝牙时的行为（覆盖 FR-010、FR-011）。
- [x] T014 运行两个项目完整自动测试、语法检查、依赖检查和敏感数据扫描，并确认 BLE 图片协议、固件和刷新间隔未改变（覆盖 FR-012、SC-006）。
- [x] T015 连续执行 3 次墨笺校准并记录 LCD 未出现非计划超时（覆盖 SC-004）；2026-11-05 完成，三次 `calibrate` 均退出码 0，租约申请/释放和 LCD worker 恢复正常，日志未出现 BLE 超时。
- [ ] T016 终止墨笺进程验证 TTL 后 LCD 自动恢复，并记录实体屏恢复（覆盖 SC-005）；2026-11-05 已完成进程层验证：异常结束后约 120 秒 TTL 到期，LCD worker 自动恢复并于 16:16:41 完成发送；实体屏最终画面仍待用户目视确认。

## 依赖与执行顺序

- T001 -> T002 -> T003 -> T004/T005 -> T006。
- T007 可与 T001-T006 并行，但端到端测试依赖 T002。
- T008/T009/T010 依赖 T007。
- T012/T013 依赖稳定接口；T014-T016 最后执行。
