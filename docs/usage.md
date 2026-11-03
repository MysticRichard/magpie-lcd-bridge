# 完整使用说明

本文按“第一次安装 → 预览 → 连接设备 → 后台运行 → 日常开关 → 故障排查”的顺序说明。

## 1. 运行模式怎么选

| 模式 | 命令 | 用途 | BLE 行为 |
| --- | --- | --- | --- |
| 预览 | `render` | 不连接设备，检查数据和排版 | 不占用 BLE |
| 一次性推送 | `push` | 临时发送一帧 | 发送后退出并断开 |
| 持续刷新 | `run` | 前台调试或手动常驻 | 保持连接，周期刷新 |
| 登录自启 | `install-autostart.ps1` | 日常桌面显示 | 隐藏运行，保持连接 |

日常使用推荐“登录自启”；调试画面用 `render`；临时更新用 `push`。如果希望屏幕持续显示，不要用 `push` 后手动关闭窗口。

## 2. 准备环境

### 2.1 检查 Magpie

先启动 Magpie，并确认本地接口可用。默认地址是：

```text
http://127.0.0.1:3425
```

可以在 PowerShell 中检查端口：

```powershell
Test-NetConnection 127.0.0.1 -Port 3425
```

如果 Magpie 使用了不同端口，运行时通过 `MAGPIE_BASE_URL` 或 `--base-url` 指定。

### 2.2 准备屏幕

- 给 DA-LCD 屏幕供电。
- 打开 Windows 蓝牙。
- 关闭 DA LCD Studio。
- 不要同时打开多个会连接该屏幕的程序。

### 2.3 安装 Python 依赖

进入项目目录：

```powershell
cd path\to\magpie-lcd-bridge
```

推荐先安装 uv，然后执行：

```powershell
uv sync
```

项目固定使用 Python 3.12，支持 Python 3.11–3.14。不要使用 Python 3.15 作为当前环境，因为 Windows BLE 依赖可能需要本地编译。

## 3. 先做本地预览

```powershell
uv run python magpie_lcd.py render
```

程序会读取 Magpie 并生成：

```text
last-frame.png
```

这一步不连接屏幕。检查以下内容：

- 今日 Token 是否显示。
- 参考费用是否符合预期。
- 缓存命中率是否为数字或短横线。
- Codex 和 OpenCode Go 的额度圆环是否有数据。
- 中文和数字是否完整显示。

如果预览不正确，先不要连接屏幕，按“Magpie 数据”问题排查。

## 4. 扫描设备

```powershell
uv run python magpie_lcd.py scan
```

输出应包含类似 `DA-LCD-...` 的设备名和本机 BLE 地址。不要把真实地址提交到公开仓库。

如果扫描不到：

1. 确认屏幕已上电。
2. 确认 Windows 蓝牙已开启。
3. 关闭 DA LCD Studio。
4. 关闭可能占用 BLE 的其他程序。
5. 再执行一次 `scan`。

## 5. 一次性推送

```powershell
uv run python magpie_lcd.py push
```

执行过程是：

1. 读取 Magpie。
2. 生成 320×240 图片。
3. 连接屏幕。
4. 发送图片。
5. 退出程序并断开 BLE。

因此，推送成功后屏幕回到时钟模式是正常的。`push` 不是常驻显示命令。

如果有多台 `DA-LCD-` 设备：

```powershell
uv run python magpie_lcd.py push --address "DA-LCD 的蓝牙地址"
```

## 6. 持续刷新

```powershell
uv run python magpie_lcd.py run --interval 60
```

行为：

- 每 60 秒读取一次 Magpie。
- 保持 BLE 连接并发送新画面。
- 断线后重新扫描一次，并用扫描得到的设备对象重连；正常刷新期间不重复扫描。
- 单次 GATT 写入超过 10 秒会超时。
- BLE 错误后会释放旧连接，并在约 10 秒后尝试重连。
- 正常刷新仍按 `--interval` 执行。

这个命令会在当前 PowerShell 窗口输出日志。需要后台静默运行时，使用下一节的自启方案。

## 7. 安装 Windows 登录自启

首次执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-autostart.ps1
```

安装内容：

- 计划任务名称：`Magpie LCD Bridge`。
- 触发条件：当前 Windows 用户登录。
- 执行程序：项目内 `.venv\Scripts\pythonw.exe`。
- 窗口模式：隐藏。
- 刷新间隔：60 秒。
- 日志文件：`logs\magpie-lcd.log`。

注意：这是“用户登录后启动”，不是 Windows 开机前就运行的系统服务。登录前屏幕不会由本程序更新。

## 8. 日常开关

先进入项目目录：

```powershell
cd path\to\magpie-lcd-bridge
Set-ExecutionPolicy -Scope Process Bypass
```

### 启动

```powershell
.\scripts\start-magpie-lcd.ps1
```

启动隐藏计划任务。它不会打开新的 Python 控制台窗口。

### 停止

```powershell
.\scripts\stop-magpie-lcd.ps1
```

停止计划任务和本项目自己的 `run` 进程，释放 BLE。屏幕应回到时钟模式。

停止后可以打开 DA LCD Studio。不要让 DA LCD Studio 和本桥接程序同时占用屏幕。

### 查看状态

```powershell
.\scripts\status-magpie-lcd.ps1
```

会显示任务状态、最近运行时间、最近结果和桥接进程 PID。

### 查看日志

```powershell
Get-Content .\logs\magpie-lcd.log -Tail 30
```

常见日志：

```text
桥接程序启动：run
已连接 ...，图片特征 FF01 可用
图片已发送：格式 ...，数据 ... 字节，... 包，... 秒
BLE 连接已断开
```

### 取消自启

```powershell
.\scripts\uninstall-autostart.ps1
```

停止桥接并删除计划任务，但不会删除项目、配置或日志。

## 9. 配置额度卡片

本节只给出最常用步骤；完整的字段、示例和故障排查见 [配置教程](configuration.md)。

复制示例：

```powershell
Copy-Item config.example.json config.json
```

示例结构：

```json
{
  "quota_groups": [
    {
      "provider": "codex",
      "title": "Codex",
      "windows": [
        { "name": "5 hours", "label": "5H" },
        { "name": "7 days", "label": "7D" }
      ]
    }
  ]
}
```

字段说明：

- `provider`：必须与 Magpie `/v1/magpie/quotas` 返回的供应商 ID 一致。
- `title`：屏幕左侧卡片标题。
- `windows[].name`：必须与 Magpie 返回的窗口名称一致。
- `windows[].label`：屏幕圆环下方的短标签，可以自行改名。

布局限制：

- 只渲染前两组供应商。
- 每组最多显示三个圆环。
- 屏幕高度固定，不能通过配置增加第三行额度卡。

如果配置缺失或格式错误，程序会记录警告并回退到默认配置。

## 10. 汇率和参考费用

Magpie 的费用接口以 USD 返回，屏幕使用 CNY 近似显示。默认汇率是：

```text
6.68
```

运行时可以覆盖：

```powershell
uv run python magpie_lcd.py --rate 7.10 run --interval 60
```

或设置环境变量：

```powershell
$env:MAGPIE_CNY_PER_USD = "7.10"
```

汇率是显示换算值，不代表真实结算金额。

## 11. 数据过期和断线

Magpie 读取失败时：

- 有上一次成功数据：屏幕标记“数据已过期”，保留旧数据。
- 没有成功数据：屏幕标记“暂未读到 Magpie”，显示空状态。

BLE 断线时：

- 程序清理旧连接。
- 约 10 秒后再次尝试连接。
- 设备断电或 Windows 蓝牙关闭期间，屏幕可能显示时钟模式。
- 重新连接成功后，下一轮发送会恢复用量页面。

## 12. 故障排查

### `未发现 DA-LCD-XXXX 设备`

检查屏幕供电、Windows 蓝牙、DA LCD Studio 是否已关闭，以及是否被其他程序占用。然后执行 `scan`。

### `蓝牙设备未连接`

程序检测到连接状态丢失。查看日志并等待下一轮重连；如果持续失败，执行 `stop` 后再执行 `start`。

### 屏幕显示时钟

先确认当前不是 `push` 模式。持续显示必须使用 `run` 或已安装的计划任务。

### 页面数据不动

检查 Magpie 是否运行、端口是否可访问、日志中是否有 Magpie 读取错误。额度本身可能在这段时间没有变化。

### PowerShell 拒绝运行脚本

只对当前 PowerShell 窗口临时放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

不要为了这个项目永久降低系统执行策略，除非你明确理解影响。

### 找不到中文字体

程序依赖 Windows 字体：

```text
C:\Windows\Fonts\msyh.ttc
C:\Windows\Fonts\msyhbd.ttc
C:\Windows\Fonts\segoeuib.ttf
```

缺少字体时会报错。当前没有内置字体替代方案。

## 13. 卸载

```powershell
.\scripts\uninstall-autostart.ps1
```

这只删除计划任务和停止桥接，不会删除：

- 项目源码
- `.venv`
- `config.json`
- `last-frame.png`
- `logs\magpie-lcd.log`

确认不再使用后，再手动删除项目目录。

## 14. 自检

```powershell
uv run python -m unittest -v
```

自检不会连接设备，主要用于验证协议编码、额度映射、画面生成、成本排版和 BLE 超时逻辑。
