# 实施计划：桌面快捷方式

## 技术方案

- 使用 Windows 自带 `WScript.Shell` COM 创建 `.lnk`，不新增依赖。
- 复用托盘图形并生成多尺寸 `assets\magpie-lcd.ico`，写入快捷方式 `IconLocation`。
- 新增 `scripts\create-controller-shortcut.ps1`，供安装脚本复用。
- 控制器设置窗口通过现有后台 action 机制调用同一创建逻辑。
- 快捷方式参数使用 `--open-settings`；单实例失败路径复用现有“请求打开设置”机制。
- 控制器首次启动且带 `--open-settings` 时，在托盘事件循环启动后打开设置。

## 影响范围

- `magpie_lcd_control.py`
- `test_magpie_lcd_control.py`
- `scripts/create-controller-shortcut.ps1`
- `scripts/install-controller-autostart.ps1`
- `scripts/uninstall-controller-autostart.ps1`
- `README.md`、`docs/controller.md`、`docs/usage.md`

## 验证

- 自动测试覆盖快捷方式参数、创建结果和安装集成。
- 实际创建桌面快捷方式并读取目标、参数、工作目录。
- 重启控制器后验证快捷方式的“启动并打开设置”和“已运行只打开设置”两条路径。

## 边界

- 不修改 worker、BLE 传输、租约、刷新间隔和额度配置。
- 不使用管理员权限，不写入系统级桌面或注册表启动项。
