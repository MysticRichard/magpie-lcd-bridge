# 运行与维护

## 运行模型

- `run --interval 60` 每轮读取 Magpie 用量与额度，渲染一帧并通过 BLE 发送。
- 设备和电脑之间的 BLE 连接由桥接程序保持。
- 单次 GATT 写入超过 10 秒会超时并释放连接；超时不会直接取消底层 WinRT 写任务，而是等连接清理阶段结束，避免 Windows BLE 回调竞态。
- 写入超时和写入失败会记录具体的起始包、数据包或结束包，以及包序号，便于区分主机写入异常和设备停止广播。
- 设备在 BLE 断开后会回到固件自带的时钟模式。
- `push` 只发送一帧并退出，退出时会主动断开 BLE；日常使用应使用 `run` 或 Windows 自启任务。
- 隐藏任务日志写入 `logs\magpie-lcd.log`，该目录已被 Git 忽略。

## 开机自启

安装一次：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-autostart.ps1
```

计划任务名称是 `Magpie LCD Bridge`，触发条件是当前 Windows 用户登录。它使用项目自己的 `.venv\Scripts\pythonw.exe`，不会依赖当前 PowerShell 会话，也不会打开控制台窗口；运行日志写入 `logs\magpie-lcd.log`。

## 手动切换

```powershell
.\scripts\stop-magpie-lcd.ps1
# 现在可以打开 DA LCD Studio

.\scripts\start-magpie-lcd.ps1
# 现在由 Magpie LCD Bridge 占用设备
```

停止脚本只匹配本项目的 `magpie_lcd.py run` 进程，不会结束其他 Python 程序。

## 刷新与资源

- 默认刷新间隔：60 秒。
- 额度变化不是秒级推送，而是下一轮刷新后显示。
- 设备重新上电后，最多通常要等一个刷新周期加上 BLE 连接和传输时间。
- 当前实际 Python worker 工作集约 48 MB，空闲 CPU 累计占用较低；图片传输期间会有短暂峰值。
- `run` 发生 BLE 错误时会先清理旧连接，再按短延迟重连；正常刷新仍按设置的间隔执行。
- 额度分组通过根目录 `config.json` 配置；复制 `config.example.json` 后可替换供应商和窗口。最多显示两行，每行最多三个窗口。

## 低压力排查

如果设备连续运行数小时后停止广播，可以临时降低完整图片传输频率观察稳定性：

```powershell
uv run python magpie_lcd.py run --interval 300
```

这只是诊断用法，不会修改计划任务的默认 60 秒刷新间隔。若低频运行明显稳定，说明设备固件或 BLE 栈可能无法长期承受高频完整画面传输。

