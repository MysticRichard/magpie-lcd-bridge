# Windows 托盘控制器

托盘控制器是日常使用的轻量入口。它只负责启动、停止和配置现有的 `magpie_lcd.py run` 子进程，不修改 BLE 协议、图片渲染或固件。

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

- 状态行：显示运行状态、刷新间隔和最近的刷新时间。
- `立即刷新`：重启 worker，让它立即读取 Magpie 并发送一帧。期间可能短暂断开 BLE。
- `启动显示` / `停止显示`：启动或停止现有 worker。
- `设置`：打开刷新间隔、登录自启和启动行为设置。
- `打开最新预览`：打开根目录的 `last-frame.png`。
- `打开额度配置`：打开 `config.json`；文件不存在时提示参考 `config.example.json`，不会覆盖本地配置。
- `退出控制器`：先停止 worker，再退出托盘。

## 设置

设置保存在：

```text
%LOCALAPPDATA%\MagpieLcdBridge\settings.json
```

它不是项目文件，不会进入 Git。刷新间隔允许 `30` 到 `3600` 秒，默认仍为 `60` 秒。

「登录 Windows 后自动启动控制器」使用当前用户注册表启动项，不需要管理员权限。启用前必须先移除旧的计划任务，避免两个启动源同时拉起两个 worker。

## 从计划任务迁移

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

## PowerShell 兼容控制

如果托盘没有启动、需要排查，或希望通过自动化脚本管理控制器，可使用：

```powershell
.\scripts\status-controller.ps1
.\scripts\stop-controller.ps1
```

`stop-controller.ps1` 只结束托盘控制器及其子进程，不会结束旧的计划任务或无关 Python 程序。

## 日志

- worker：`logs\magpie-lcd.log`
- 控制器：`logs\controller.log`

日志目录已被 Git 忽略。重新打开托盘或切换间隔后，先查看控制器日志；屏幕没有更新时再查看 worker 日志。

## 已知限制

- 首版是 Python 托盘版本，尚未打包成独立 EXE。
- “立即刷新”通过重启 worker 实现，会有几秒 BLE 重连窗口。
- 托盘只管理自己的 worker，不会接管旧计划任务或其他 BLE 程序。
- 与墨笺/EPD 项目的蓝牙适配器竞争仍没有跨进程自动协调。
