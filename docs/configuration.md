# 配置教程

本文说明如何配置 Magpie LCD Bridge 的数据源、额度卡片、汇率、日志和运行参数。

## 1. 哪些内容可以配置

可以通过 `config.json` 配置：

- 额度供应商 ID。
- 屏幕上显示的卡片标题。
- 额度窗口名称。
- 圆环下方的短标签。
- 最多两组供应商。
- 每组最多三个窗口。

不能通过 `config.json` 配置：

- Magpie 的账号或密钥。
- 屏幕分辨率。
- 图片协议或固件行为。
- 自启任务的刷新间隔。
- Windows 服务模式。

汇率、Magpie 地址、日志路径和部分运行参数通过环境变量或命令行参数配置。

## 2. 配置文件位置

默认配置文件：

```text
path\to\magpie-lcd-bridge\config.json
```

项目不会提交 `config.json`，因为它属于本机配置。公开仓库只提供：

```text
config.example.json
```

第一次配置时复制示例：

```powershell
cd path\to\magpie-lcd-bridge
Copy-Item config.example.json config.json
```

如果文件不存在，程序会使用默认的 Codex 和 OpenCode Go 配置。

## 3. 五分钟配置流程

### 第一步：确认 Magpie 正在运行

```powershell
Test-NetConnection 127.0.0.1 -Port 3425
```

### 第二步：查看 Magpie 返回的额度结构

```powershell
Invoke-RestMethod "http://127.0.0.1:3425/v1/magpie/quotas" |
    ConvertTo-Json -Depth 10
```

重点找到：

- `provider`：供应商 ID。
- `windows[].name`：窗口名称。
- `remaining`：剩余额度。

### 第三步：复制并编辑配置

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

### 第四步：验证 JSON 格式

```powershell
Get-Content .\config.json -Raw | ConvertFrom-Json | Out-Null
```

没有报错说明 JSON 语法有效。

### 第五步：生成预览

```powershell
uv run python magpie_lcd.py render
```

打开 `last-frame.png`，检查卡片标题、圆环数量和短标签。

### 第六步：让后台任务应用配置

程序每轮刷新都会重新读取 `config.json`。正在运行的 `run` 或计划任务会在下一轮刷新时应用修改，通常最多约 60 秒，不需要重新安装自启。

如果后台任务没有运行，先启动：

```powershell
.\scripts\start-magpie-lcd.ps1
```

## 4. 查看供应商和窗口名称

### 4.1 查看额度接口

```powershell
$quotas = Invoke-RestMethod "http://127.0.0.1:3425/v1/magpie/quotas"
$quotas.data |
    Select-Object provider, @{Name="windows";Expression={$_.windows.name}} |
    Format-Table -AutoSize
```

输出中的 `provider` 用于配置文件的 `provider` 字段。

### 4.2 查看用量接口

```powershell
Invoke-RestMethod "http://127.0.0.1:3425/v1/magpie/usage?period=today" |
    ConvertTo-Json -Depth 10
```

用量接口用于显示今日 Token、费用、缓存命中率和未定价请求数，不需要在 `config.json` 中配置。

### 4.3 名称必须完全一致

配置中的 `provider` 和 `windows[].name` 必须与 Magpie 返回的字符串一致，包括空格和大小写。

例如接口返回：

```json
{
  "provider": "codex",
  "windows": [
    { "name": "5 hours" },
    { "name": "7 days" }
  ]
}
```

配置应使用：

```json
{
  "provider": "codex",
  "windows": [
    { "name": "5 hours", "label": "5H" },
    { "name": "7 days", "label": "7D" }
  ]
}
```

## 5. 配置文件结构

日常使用可以直接打开托盘 `设置`，在“额度显示”区域从 Magpie 当前额度中勾选。设置窗口最多允许两个供应商、每个供应商最多三个窗口；保存时按短周期优先排列为 `5 hours → 7 days → Month`，同一名称前缀（例如 `Gemini`、`Claude & GPT`）分别排序。以下手工结构用于需要修改标题、短标签或明确自定义窗口顺序的场景。

根对象必须包含 `quota_groups` 数组：

```json
{
  "quota_groups": []
}
```

每组供应商支持以下字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `provider` | string | 是 | Magpie 额度接口的供应商 ID |
| `title` | string | 是 | 屏幕卡片标题 |
| `windows` | array | 是 | 额度窗口列表 |
| `windows[].name` | string | 是 | Magpie 窗口名称 |
| `windows[].label` | string | 是 | 屏幕下方短标签 |

手工编辑 `config.json` 时，`windows` 数组顺序就是屏幕圆环从左到右的显示顺序。通过设置窗口保存时，程序会按 `5H → 7D → 本月` 自动排序。

## 6. 默认配置示例

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
    },
    {
      "provider": "opencode-go",
      "title": "OpenCode Go",
      "windows": [
        { "name": "5 hours", "label": "5H" },
        { "name": "7 days", "label": "7D" },
        { "name": "Month", "label": "本月" }
      ]
    }
  ]
}
```

## 7. 常见配置示例

### 7.1 只显示一组供应商

第二行会显示空的额度卡片：

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

### 7.2 只显示一个圆环

```json
{
  "quota_groups": [
    {
      "provider": "codex",
      "title": "Codex",
      "windows": [
        { "name": "7 days", "label": "7D" }
      ]
    }
  ]
}
```

### 7.3 显示三个窗口并修改短标签

```json
{
  "quota_groups": [
    {
      "provider": "opencode-go",
      "title": "OpenCode Go",
      "windows": [
        { "name": "5 hours", "label": "5H" },
        { "name": "7 days", "label": "7D" },
        { "name": "Month", "label": "月" }
      ]
    }
  ]
}
```

### 7.4 配置其他供应商

将 `provider` 替换为 Magpie 实际返回的 ID：

```json
{
  "quota_groups": [
    {
      "provider": "your-provider-id",
      "title": "My Provider",
      "windows": [
        { "name": "5 hours", "label": "5H" },
        { "name": "7 days", "label": "7D" }
      ]
    }
  ]
}
```

`your-provider-id` 只是占位符，不能直接使用；必须换成真实接口值。

## 8. 屏幕布局规则

- 固定显示两行额度卡。
- 只读取 `quota_groups` 的前两组。
- 每组最多渲染三个圆环。
- 超出的供应商组或窗口不会显示。
- 短标签建议控制在 2–5 个字符，避免和圆环重叠。
- 某个窗口找不到数据时显示短横线。
- 某个供应商找不到时，该组圆环没有可用数据。

## 9. 环境变量和命令行参数

### 9.1 全局参数

全局参数必须放在子命令 `render`、`push` 或 `run` 之前。

| 参数 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--base-url` | `MAGPIE_BASE_URL` | `http://127.0.0.1:3425` | Magpie 本地接口 |
| `--rate` | `MAGPIE_CNY_PER_USD` | `6.68` | USD→CNY 显示汇率 |
| `--config` | `MAGPIE_LCD_CONFIG` | 项目根目录 `config.json` | 额度配置文件 |
| `--output` | 无 | `last-frame.png` | 预览图输出路径 |
| `--log-file` | `MAGPIE_LCD_LOG` | `logs\magpie-lcd.log` | 日志文件 |

命令行参数优先于环境变量，环境变量优先于默认值。

### 9.2 子命令参数

| 参数 | 适用命令 | 说明 |
| --- | --- | --- |
| `--address` | `push`、`run` | 指定 DA-LCD 蓝牙地址 |
| `--interval` | `run` | 刷新间隔，代码最小值为 10 秒 |

### 9.3 示例

临时使用另一个 Magpie 端口：

```powershell
$env:MAGPIE_BASE_URL = "http://127.0.0.1:8080"
uv run python magpie_lcd.py render
```

使用自定义配置和汇率：

```powershell
uv run python magpie_lcd.py `
    --config .\my-config.json `
    --rate 7.10 `
    render
```

持续运行时指定设备和刷新间隔：

```powershell
uv run python magpie_lcd.py run --address "DA-LCD 的蓝牙地址" --interval 120
```

## 10. 自启任务的配置限制

当前安装脚本创建的计划任务动作固定为：

```text
magpie_lcd.py --log-file "logs\magpie-lcd.log" run --interval 60
```

因此：

- 默认读取项目根目录的 `config.json`。
- 修改 `config.json` 后，下一轮刷新会自动应用。
- 自启刷新间隔固定为 60 秒。
- `config.json` 不控制 Magpie 地址或汇率。
- 自启脚本没有暴露自定义配置路径、地址、汇率或间隔参数。

如果需要让自启使用自定义地址、汇率、配置路径或间隔，需要修改 `scripts\install-autostart.ps1` 中的任务动作，然后重新执行安装脚本。修改前先用前台 `run` 验证命令可以工作。

查看当前计划任务动作：

```powershell
(Get-ScheduledTask -TaskName "Magpie LCD Bridge").Actions |
    Format-List Execute, Arguments, WorkingDirectory
```

## 11. 日志配置

默认日志：

```text
logs\magpie-lcd.log
```

查看最近日志：

```powershell
Get-Content .\logs\magpie-lcd.log -Tail 50
```

自定义日志路径只影响当前命令行运行：

```powershell
uv run python magpie_lcd.py --log-file .\logs\custom.log run --interval 60
```

自启任务的日志路径由计划任务动作决定。

## 12. 配置故障排查

### 配置没有生效

检查：

1. 文件是否在项目根目录并命名为 `config.json`。
2. 是否使用了自定义 `--config` 路径。
3. 后台任务是否正在运行。
4. 日志是否提示配置读取失败。

### JSON 语法错误

执行：

```powershell
Get-Content .\config.json -Raw | ConvertFrom-Json | Out-Null
```

如果报错，先修复逗号、引号和括号。配置解析失败时程序会记录警告并回退到默认配置。

### 圆环显示短横线

通常是以下原因：

- `provider` 写错。
- `windows[].name` 写错。
- 该供应商当前没有返回对应窗口。
- 接口字段结构发生变化。

先用 `Invoke-RestMethod` 检查真实返回值，再复制准确的字符串。

### 第二组不显示

程序只读取前两组 `quota_groups`。检查数组顺序。

### 第三个之后的窗口不显示

每组最多渲染三个窗口，这是 320×240 屏幕布局限制。

### 标签重叠

缩短 `label`，例如把“本月额度”改为“月”或“本月”。

### 修改后旧画面仍然存在

等下一轮刷新，或执行：

```powershell
.\scripts\stop-magpie-lcd.ps1
.\scripts\start-magpie-lcd.ps1
```

## 13. 恢复默认配置

临时恢复默认：

```powershell
Rename-Item .\config.json .\config.json.bak
```

程序找不到 `config.json` 时会使用内置的 Codex 和 OpenCode Go 配置。

恢复自定义配置：

```powershell
Rename-Item .\config.json.bak .\config.json
```

## 14. 配置安全检查

- 不要把 `config.json` 提交到 Git。
- 不要向配置写入账号、Cookie、API 密钥或蓝牙地址。
- `config.json` 只应包含供应商 ID、标题和窗口标签。
- 公开示例只使用通用供应商 ID 和占位符。
