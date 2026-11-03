# 运行与维护

## 运行模型

- `run --interval 60` 每轮读取 Magpie 用量与额度，渲染一帧并通过 BLE 发送。
- 设备和电脑之间的 BLE 连接由桥接程序保持。
- 项目固定使用 Bleak 3.0.2。重连时显式扫描一次，并把扫描得到的设备对象传给 `BleakClient`，避免按地址构造客户端时再次隐式扫描。
- Magpie 的 HTTP 读取通过后台线程执行，避免同步网络等待阻塞 BLE 事件循环。
- 每次连接使用独立代次；旧连接迟到的断线回调不会清空新连接状态。
- 单次 GATT 写入超过 10 秒会超时。清理时最多等 2 秒取消 pending 写入，再最多等 5 秒断开连接；未完成的 WinRT 操作转入后台，不阻塞主循环。
- 新连接开始前最多等待 5 秒让上一轮清理结束；仍未完成时本轮不扫描、不重连，避免两个会话重叠。
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

## BLE 并发边界

本程序会长期占用目标 LCD 的 BLE 连接，但不会与 EPD、DA LCD Studio 或其他 BLE 工具建立跨进程互斥。两个程序同时操作同一个 Windows 蓝牙适配器时，仍可能发生扫描、连接或 GATT 请求排队冲突。若复现卡死，请记录两个程序的时间点并先停止其中一个做对照；本项目不会自动关闭其他 BLE 程序。

## 低压力排查

如果设备连续运行数小时后停止广播，可以临时降低完整图片传输频率观察稳定性：

```powershell
uv run python magpie_lcd.py run --interval 300
```

这只是诊断用法，不会修改计划任务的默认 60 秒刷新间隔。若低频运行明显稳定，说明设备固件或 BLE 栈可能无法长期承受高频完整画面传输。

