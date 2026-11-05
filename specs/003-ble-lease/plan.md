# 技术实施方案：跨项目 BLE 租约

## 1. 技术上下文

- 平台：Windows，Python 3.11-3.14；墨笺固定 Python 3.12。
- 传输：`multiprocessing.connection` 的 Windows 命名管道，JSON UTF-8 字节消息。
- 并发：LCD 控制器内使用现有 `worker_lock` 串行化 worker 状态与租约状态。
- 持久化：仅保存随机管道认证密钥到 `%LOCALAPPDATA%\MagpieLcdBridge\ble-lease.key`；租约本身只在内存中。
- 测试：LCD 使用 `unittest`，墨笺使用 `pytest`。

## 2. Constitution Check

- **Status**: PASS
- **Local Data and Privacy**：租约只在当前用户本机命名管道通信，不包含用户数据，不开放网络端口。
- **Preserve the Device**：仅停止/启动现有 worker，不修改 BLE 图片协议或固件。
- **Honest Data Presentation**：托盘明确显示外部 BLE 占用；不伪造连接状态。
- **Configurable, Bounded UI**：不改变 UI 配置和 60 秒默认间隔。
- **Recoverable Unattended Operation**：token、心跳、TTL 和自动恢复覆盖墨笺异常退出。
- **Evidence Before Claims**：管理器、管道、墨笺客户端和调用时机分别自动测试，再做真机连续校准。

## 3. 项目结构与触点

```text
magpie-lcd-bridge/
  ble_lease.py                    # 租约状态机、命名管道服务端、客户端契约
  magpie_lcd_control.py           # 托盘集成、外部租约阻断、生命周期
  test_magpie_lcd_control.py      # 租约和托盘状态测试
  docs/ble-coordination.md        # 协议与运维说明
  specs/003-ble-lease/

inkmemo-epd/
  src/inkmemo/ble/lease.py        # 墨笺命名管道客户端与异步心跳
  src/inkmemo/ble/client.py       # BLE 操作外层持有租约
  src/inkmemo/__main__.py         # scan 命令持有租约
  src/inkmemo/runtime.py          # busy 状态与通知
  tests/test_ble_lease.py         # 客户端行为测试
```

## 4. 协议

- 管道：`\\.\pipe\MagpieLcdBridge.BleLease.v1`
- 密钥：`%LOCALAPPDATA%\MagpieLcdBridge\ble-lease.key`
- 消息：UTF-8 JSON 字节，单连接单请求。
- 请求公共字段：`protocol=1`、`op`、`owner`、`token`（按需）、`ttl_seconds`（按需）。
- 操作：`status`、`acquire`、`heartbeat`、`release`。
- 默认 TTL：120 秒；允许 30-600 秒。
- 心跳间隔：30 秒。
- `busy` 是明确拒绝，不是可忽略错误。

## 5. 数据流

1. 控制器启动命名管道服务，并生成当前安装的随机认证密钥。
2. 墨笺在扫描或 `transfer_with_retries` 前读取密钥并发送 `acquire`。
3. 控制器在共享 worker 锁内检查现有租约；新租约先记录 worker 是否运行，再停止 worker，等待进程退出并留出 BLE 释放宽限。
4. 墨笺收到 token 后执行全部扫描/连接/重试，并每 30 秒心跳。
5. `finally` 中墨笺发送 `release`；控制器清除租约，仅在申请前 worker 运行时恢复。
6. 控制器 watchdog 每秒检查到期租约，等价执行释放恢复。

## 6. 实施阶段

### 阶段 1：LCD 租约状态机

- 实现 token 生成、owner 冲突、心跳、释放、TTL 和恢复语义。
- 使用现有 `WorkerProcess`，不移动 BLE 主循环。

### 阶段 2：命名管道与托盘集成

- 实现认证命名管道服务和客户端请求函数。
- 托盘状态显示外部占用，并阻断启动/重启。

### 阶段 3：墨笺客户端

- 实现异步友好租约上下文、心跳和 busy/不可用语义。
- 将扫描和 `transfer_with_retries` 整体包在租约内。
- 在运行状态与通知中区分 `busy`。

### 阶段 4：验证与文档

- 自动测试状态机、管道、客户端、异常释放和 busy。
- 运行两个项目的完整测试与静态检查。
- 真机连续校准至少 3 次，并做墨笺进程异常退出后的 TTL 恢复测试。

## 7. 测试策略

- LCD：`uv run python -m unittest -v`
- 墨笺：`.\.venv\Scripts\python.exe -m pytest -q`
- 两端 `py_compile` / `compileall`。
- 管道测试使用临时密钥和唯一管道名，不接触生产租约。
- 真机验收与自动测试分开记录。

## 8. 部署与已知边界

- 新控制器代码需要重启托盘控制器后生效；本轮不在自动测试阶段重启生产进程。
- 控制器不在运行时，墨笺记录“协调不可用”并保持原有独立能力。
- Busy 时墨笺中止本轮 BLE，不排队等待，避免 UI 长期悬挂。
- LCD 在外部租约期间进入时钟模式属于预期行为。
