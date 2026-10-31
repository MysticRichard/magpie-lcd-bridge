# 运行与维护

## 运行模型

- `run --interval 60` 每轮读取 Magpie 用量与额度，渲染一帧并通过 BLE 发送。
- 设备和电脑之间的 BLE 连接由桥接程序保持。
- 单次 GATT 写入超过 10 秒会超时并释放连接；设备断电、蓝牙暂不可用或 DA LCD Studio 占用连接时，程序约 10 秒后继续尝试。
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
- 当前实测空闲内存约 25 MB，空闲 CPU 接近 0%；图片传输期间会有短暂峰值。
- `run` 发生 BLE 错误时会先清理旧连接，再按短延迟重连；正常刷新仍按设置的间隔执行。
- 额度分组通过根目录 `config.json` 配置；复制 `config.example.json` 后可替换供应商和窗口。最多显示两行，每行最多三个窗口。

