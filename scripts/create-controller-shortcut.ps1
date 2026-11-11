$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$script = Join-Path $projectRoot "magpie_lcd_control.py"
$icon = Join-Path $projectRoot "assets\magpie-lcd.ico"
$desktop = [Environment]::GetFolderPath("DesktopDirectory")
$shortcutPath = Join-Path $desktop "Magpie LCD Bridge.lnk"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Windowless Python runtime not found: $python. Run 'uv sync' first."
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "Controller script not found: $script"
}
if (-not (Test-Path -LiteralPath $icon)) {
    throw "Shortcut icon not found: $icon"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = "`"$script`" --open-settings"
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "Magpie LCD Bridge controller and settings"
$shortcut.Save()

Write-Host "Created desktop shortcut: $shortcutPath"
