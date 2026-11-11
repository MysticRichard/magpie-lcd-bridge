# 实施计划：可勾选的额度展示

## 技术方案

- 在 `magpie_lcd_control.py` 复用现有 Tkinter 设置窗口和 `_atomic_write()`。
- 使用标准库读取 Magpie 响应；不新增依赖。
- 复用 `magpie_lcd.QuotaGroup`、`DEFAULT_BASE_URL`、`load_quota_config()` 和 `fetch_json()`。
- 将 Magpie 响应规范化为可勾选选项，保存为现有 `config.json` 格式。
- 对额度窗口应用稳定排序：先按名称前缀分组，再按 `5 hours → 7 days → Month → 其他` 排序。
- 设置保存流程在配置变化且 worker 运行时重启 worker；外部 BLE 租约期间保留配置并由租约释放流程恢复。
- 保存回调期间禁用保存按钮；成功状态写入窗口底部标签，不调用阻塞式 `showinfo`。

## 影响范围

- `magpie_lcd_control.py`：额度选项读取、校验、保存和设置窗口控件。
- `test_magpie_lcd_control.py`：解析、限制、失败保护和保存回归测试。
- `README.md`、`docs/controller.md`、`docs/configuration.md`：说明新入口。

## 验证

- 固定响应的供应商和窗口解析。
- 两个供应商、每组三个窗口的边界。
- Magpie 读取失败不覆盖原配置。
- 保存后的 JSON 可被 `load_quota_config()` 正常读取。
- 运行完整 Python 自动测试、语法检查和敏感信息扫描。

## 边界

- 不改 `magpie_lcd.py` 的渲染和 BLE 传输。
- 不自动修改 Magpie 配置。
- 不在自动测试中连接真实 BLE 设备或写用户配置。
