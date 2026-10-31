# Magpie LCD Bridge

读取本机 Magpie 的今日用量与额度，渲染为已确认的 320×240 画面，通过 BLE 发送到 DA-LCD（DA14585）。

这是一个面向 Windows 的开源个人工具。它只读取 Magpie 的本地接口，不读取账号密钥，也不修改屏幕固件。

## 致谢

感谢硬件原始控制器作者 [`tsl0922`](https://github.com/tsl0922)。本项目是独立桥接工具，只复用设备已有的 BLE 图片传输协议行为，不包含原控制器源码。详见 [`NOTICE.md`](NOTICE.md)。

## 先决条件

- Python 3.11–3.14；项目内 `.python-version` 固定为 3.12，避免 `bleak` 的 Windows 依赖在 Python 3.15 上触发本地编译。
- Windows 蓝牙已开启。
- Magpie 正在运行，默认接口为 `http://127.0.0.1:3425`。
- DA LCD Studio 已断开；该屏幕同一时间只接受一个 BLE 连接。
- 运行期间不要升级固件。

## 安装与预览

```powershell
cd path\to\magpie-lcd-bridge
uv sync
uv run python magpie_lcd.py render
```

预览写入 `last-frame.png`，不会连接设备。

## 扫描与推送

```powershell
uv run python magpie_lcd.py scan
uv run python magpie_lcd.py push
```

有多台 DA-LCD 时用 `--address` 指定：

```powershell
uv run python magpie_lcd.py push --address "DA-LCD 的蓝牙地址"
```

## 持续刷新

```powershell
uv run python magpie_lcd.py run --interval 60
```

程序保持 BLE 连接，每分钟刷新。单次 BLE 写入超过 10 秒会中止，断线后约 10 秒内进入下一次连接尝试；已有旧数据时标为“数据已过期”，首次无数据时显示空状态。后台运行日志默认写入 `logs\magpie-lcd.log`。

## Windows 开机自启与手动开关

在项目目录执行一次：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-autostart.ps1
```

它会创建当前 Windows 用户的隐藏计划任务 `Magpie LCD Bridge`，在用户登录后使用无窗口的 `pythonw.exe` 自动启动。不会修改系统服务，也不会请求管理员权限。运行日志仍写入 `logs\magpie-lcd.log`，不会弹出控制台窗口。

日常开关：

```powershell
# 手动启动
.\scripts\start-magpie-lcd.ps1

# 手动停止并释放 BLE，让设备回到时钟模式
.\scripts\stop-magpie-lcd.ps1

# 查看任务和进程状态
.\scripts\status-magpie-lcd.ps1

# 取消开机自启并停止进程
.\scripts\uninstall-autostart.ps1
```

停止后不会在当前登录会话中自行启动；下一次 Windows 登录时，已安装的登录触发器会再次启动它。DA LCD Studio 和本程序不能同时连接设备。

## 配置

```powershell
$env:MAGPIE_BASE_URL = "http://127.0.0.1:3425"
$env:MAGPIE_CNY_PER_USD = "6.68"
```

参考费用使用 USD→CNY 近似汇率。Magpie 的 `cost` 接口返回美元，界面显示人民币；汇率变化时应更新 `MAGPIE_CNY_PER_USD`。

额度卡片不是写死的。复制 `config.example.json` 为 `config.json`，即可替换两行卡片的供应商、显示名称和窗口：

```powershell
Copy-Item config.example.json config.json
```

配置结构：

- `provider`：Magpie `/v1/magpie/quotas` 返回的供应商 ID。
- `title`：屏幕上显示的卡片名称。
- `windows[].name`：接口里的窗口名称。
- `windows[].label`：屏幕下方的短标签。

屏幕仍然只有两行额度卡，这是 320×240 画布的物理限制；每行可以配置 0–3 个圆环，位置会根据数量自动排列。配置文件留在本机，已经加入 `.gitignore`，不会被提交到公开仓库。

## 实现边界

- 只读 Magpie 本地接口，不抓屏、不读取账号或密钥。
- 使用控制器已有的图片传输协议；固件不修改。
- RGB565，自动在原始、PackBits、行差分+PackBits 中选择最小结果。
- 当前没有托盘、多页面轮播、路由状态或历史曲线。
- 未验证屏幕在 BLE 断开后是否长期保留最后一帧；`run` 模式会保持连接。
- 不包含托盘图标、路由状态、历史曲线、账号信息或自动 OTA。

## 自检

```powershell
uv run python -m unittest -v
```
