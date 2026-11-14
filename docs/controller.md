# Windows 托盘控制器

托盘控制器是日常使用的轻量入口。它只负责启动、停止和配置现有的 `magpie_lcd.py run` 子进程，不修改 BLE 协议、图片渲染或固件。

控制器同时提供本机 BLE 租约接口。墨笺等已接入该协议的程序可以在扫描或连接前请求控制器暂停 LCD，完成后恢复。协议见 [跨项目 BLE 租约](ble-coordination.md)。

## 运行结构

```text
Magpie LCD Bridge 托盘
        |
        +-- magpie_lcd.py run --interval 60
                |
                +-- Magpie 本地 HTTP 接口
                +-- BLE 320x240 LCD
```

停止显示会结束 worker 并释放 BLE。LCD 可能回到固件时钟模式，这是设备的预期行为。

## 启动

先完成 [完整使用说明](usage.md) 中的依赖和预览检查，然后执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start-controller.ps1
```

启动后不显示控制台窗口，只在 Windows 通知区域显示 `Magpie LCD Bridge` 图标。重复执行启动脚本不会创建第二个控制器；已有控制器会打开设置窗口。

## 托盘菜单

- 状态行：显示运行状态、刷新间隔和最近的刷新时间；外部租约期间显示 BLE 占用方。
- `立即刷新`：重启 worker，让它立即读取 Magpie 并发送一帧。期间可能短暂断开 BLE。
- `启动显示` / `停止显示`：启动或停止现有 worker。
- `设置`：打开刷新间隔、登录自启、启动行为和额度显示设置。
- `创建桌面快捷方式`：创建或更新带项目图标的桌面入口。
- `打开最新预览`：打开根目录的 `last-frame.png`。
- `打开额度配置`：打开 `config.json`；文件不存在时提示参考 `config.example.json`，不会覆盖本地配置。
- `退出控制器`：先停止 worker，再退出托盘。

## 设置

设置保存在：

```text
%LOCALAPPDATA%\MagpieLcdBridge\settings.json
```

它不是项目文件，不会进入 Git。刷新间隔允许 `30` 到 `3600` 秒，默认仍为 `60` 秒。

“额度显示”会从 Magpie `/v1/magpie/quotas` 读取当前非空的供应商和窗口。勾选后保存到项目根目录的本机 `config.json`，沿用现有两行额度卡、每行最多三个圆环的容量。最多选择两个供应商；每个供应商最多选择三个窗口。Magpie 暂时不可用时显示读取错误，不会清空或覆盖已有配置。

保存额度选择时，如果 worker 正在运行且没有外部 BLE 租约，控制器会重启 worker 让新配置立即生效；BLE 正由其他项目占用时，配置仍会保存，并在租约释放后的正常恢复过程中读取。

保存成功后，窗口底部显示“设置已保存”，不会弹出阻塞式确认框。保存执行期间按钮会暂时禁用，避免连续点击造成重复保存或多个弹窗。

设置窗口的 Tk 事件循环固定运行在控制器主线程，托盘在后台线程运行；状态刷新和保存动作使用后台任务回填结果，不会因为 worker 停止或租约等待而阻塞窗口按钮和关闭操作。

托盘菜单和设置窗口都可以创建 `Magpie LCD Bridge.lnk`，并写入 `assets\magpie-lcd.ico` 作为图标。点击快捷方式时，控制器未运行则启动控制器并打开设置；控制器已运行时只打开设置窗口。重复创建会覆盖同一个快捷方式。

「登录 Windows 后自动启动控制器」使用当前用户的隐藏登录计划任务 `Magpie LCD Bridge Controller`，以交互用户、普通权限运行。设置中的勾选状态读取任务是否启用；取消勾选只移除下次登录的启动配置，当前控制器仍可继续使用。若任务注册失败，会提示错误并保留原启动项。

启用前必须先移除旧的 worker 计划任务 `Magpie LCD Bridge`，避免两个启动源同时拉起两个 worker。新任务启动的是托盘控制器，由控制器管理唯一的 worker。

## 安装与迁移

如果之前安装过隐藏计划任务：

```powershell
.\scripts\uninstall-autostart.ps1
```

`start-controller.ps1` 会在检测到旧 `Magpie LCD Bridge` 计划任务仍存在时拒绝启动，避免两个 worker 同时占用 BLE。

确认旧的 `Magpie LCD Bridge` 计划任务已经从任务计划程序中消失，再安装控制器登录自启：

```powershell
.\scripts\install-controller-autostart.ps1
.\scripts\start-controller.ps1
```

取消控制器登录自启：

```powershell
.\scripts\uninstall-controller-autostart.ps1
```

此前使用注册表 Run 的用户，重新执行 `install-controller-autostart.ps1` 即可迁移：先注册任务，成功后再删除本项目旧的 `Magpie LCD Bridge Control` Run 值，不改其他应用的启动项。安装自启不会立即启动程序；当前会话使用 `start-controller.ps1`。

`install-controller-autostart.ps1` 首次安装或重新安装时会创建桌面快捷方式；`uninstall-controller-autostart.ps1` 会同时移除该快捷方式。只需重建快捷方式时，可单独执行 `.\scripts\create-controller-shortcut.ps1`。

任务设置为当前用户登录触发、隐藏、允许电池运行、忽略重复实例，运行时限为 3650 天。任务的动作明确保存 `.venv\Scripts\pythonw.exe`、控制器绝对路径和项目工作目录；不保存用户密码。默认刷新间隔仍由控制器设置决定。

排查自启：

```powershell
.\scripts\status-controller.ps1
Get-ScheduledTask -TaskName "Magpie LCD Bridge Controller"
Get-ScheduledTaskInfo -TaskName "Magpie LCD Bridge Controller"
```

`Ready` 表示等待触发，`Running` 表示任务正在运行；任务注册成功与真正登录后启动是两项独立验证。安装后需要在方便时注销并重新登录，确认只有一个托盘控制器且 worker 恢复发送。睡眠唤醒不会触发这里的登录自启。

本机 2026-11-06 的现场结果：Windows 登录时没有执行原 Run 项；普通用户 `schtasks.exe /Create` 返回拒绝访问，而 `Register-ScheduledTask` 配合当前用户的交互令牌成功。因此脚本和托盘开关均使用 PowerShell ScheduledTasks 接口。Windows 跳过 Run 项的内部原因尚未查明。

回退时先取消新任务，再从已知良好的源码版本恢复 Run 启动配置；也可用 `start-controller.ps1` 手动启动。旧 worker 任务仅用于独立回退，不能与新控制器任务同时开启，否则会绕过控制器的 BLE 租约协调。

## PowerShell 兼容控制

如果托盘没有启动、需要排查，或希望通过自动化脚本管理控制器，可使用：

```powershell
.\scripts\status-controller.ps1
.\scripts\stop-controller.ps1
```

`stop-controller.ps1` 会结束当前项目的托盘控制器、worker 及其子进程，包括父控制器已退出后遗留的 worker；不会结束旧的计划任务或无关 Python 程序。

## 日志

- worker：`logs\magpie-lcd.log`
- 控制器：`logs\controller.log`

日志目录已被 Git 忽略。重新打开托盘或切换间隔后，先查看控制器日志；屏幕没有更新时再查看 worker 日志。

## 已知限制

- 首版是 Python 托盘版本，尚未打包成独立 EXE。
- “立即刷新”通过重启 worker 实现，会有几秒 BLE 重连窗口。
- 托盘只管理自己的 worker，不会接管旧计划任务或其他 BLE 程序。
- 与墨笺的蓝牙竞争通过本机命名管道租约协调；不遵守该协议的其他 BLE 程序仍可能竞争适配器。
- 快捷方式保存当前仓库的绝对路径；移动仓库后需要在设置窗口重新创建。
