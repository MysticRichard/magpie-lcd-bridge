# 跨项目 BLE 租约

## 目的

LCD 看板和墨笺 InkMemo 使用不同的 BLE 设备，但共用同一个 Windows 蓝牙适配器。墨笺扫描或连接 EPD 时，LCD 的持续连接可能短暂无法写入。

本项目提供一个仅限本机的租约接口：墨笺真正使用 BLE 前申请租约，LCD 控制器停止 worker 并释放连接；墨笺结束后释放，LCD 按申请前状态恢复。

这不是 Windows 全局蓝牙锁，也不会接管不遵守协议的蓝牙程序。

## 接口

- 命名管道：`\\.\pipe\MagpieLcdBridge.BleLease.v1`
- 认证密钥：`%LOCALAPPDATA%\MagpieLcdBridge\ble-lease.key`
- 消息：单连接、UTF-8 JSON 字节
- 协议版本：`1`
- 默认租约：120 秒
- 心跳间隔：30 秒

支持操作：

```json
{"protocol":1,"op":"status"}
{"protocol":1,"op":"acquire","owner":"inkmemo","ttl_seconds":120}
{"protocol":1,"op":"heartbeat","token":"...","ttl_seconds":120}
{"protocol":1,"op":"release","token":"..."}
```

`acquire` 成功返回随机 token。不同 owner 的有效租约返回 `busy`，不会覆盖现有租约。

墨笺的 `acquire` 请求使用 30 秒上限，覆盖 LCD worker 有界停止和进程退出等待；普通心跳与释放仍使用较短的 4 秒上限。

## 状态转换

1. 控制器启动管道服务和租约 watchdog。
2. 墨笺申请租约。
3. 控制器记录 LCD worker 当前是否运行，然后停止 worker。
4. 进程退出并等待短暂 BLE 释放宽限后，控制器返回 token。
5. 墨笺执行完整 BLE 扫描、连接、重试和传输，并每 30 秒续期。
6. 墨笺在 `finally` 中释放租约。
7. 如果申请前 worker 正在运行，控制器重新启动 worker；如果申请前已停止，则保持停止。
8. 墨笺崩溃或未释放时，租约到期后自动执行相同恢复逻辑。

租约期间 LCD 可能进入固件时钟模式，释放后会在下一个刷新周期重新连接。

## 墨笺行为

- `preview` 和内容未变化的检查不申请租约。
- `scan`、`calibrate`、正常发送和缓存失败发送会申请租约。
- 一次同步的全部五次连接重试共享同一租约。
- 控制器未运行或管道不存在时，墨笺记录协调不可用并继续独立运行。
- 控制器明确返回 `busy` 时，墨笺不连接 BLE，并向用户显示“蓝牙被占用”。

## 排查

- LCD 托盘显示 `BLE 由 inkmemo 临时占用 · LCD 已暂停`：正常租约状态。
- 长时间保持该状态：检查墨笺是否仍有 BLE 进程；正常情况下最长在 TTL 到期后自动恢复。
- 墨笺提示“蓝牙被占用”：先确认是否同时启动了第二个墨笺实例或其他租约持有者。
- 管道或密钥缺失：LCD 控制器可能未启动；墨笺会退回独立运行，跨项目竞争保护不生效。

## 已验证范围

- 2026-11-05：新版控制器和墨笺运行版已部署。
- 连续 3 次 `calibrate` 均正常退出；每次都观察到租约申请、LCD worker 停止、释放后 worker 恢复，LCD 日志未出现非计划 BLE 超时。
- 强制结束一次持有租约的墨笺校准进程后，约 120 秒 TTL 到期，watchdog 自动恢复 LCD worker，并完成一帧实际发送。
- 以上是主机进程和 BLE 发送层验证；屏幕最终画面仍需用户目视确认。

日志位置：

- LCD 租约事件：`logs\controller.log`
- 墨笺 BLE 协调：`%LOCALAPPDATA%\InkMemo\logs\inkmemo.log`

## 边界

- 仅支持当前 Windows 用户本机。
- 不修改 BLE 图片协议、固件、刷新间隔或设备写入方式。
- 不阻止 DA LCD Studio 或其他未知 BLE 程序占用适配器。
- 多适配器绑定、HCI 抓包和驱动级互斥不在当前范围。
