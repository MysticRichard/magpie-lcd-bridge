$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$script = Join-Path $projectRoot "magpie_lcd_control.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Windowless Python runtime not found: $python. Run 'uv sync' first."
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "Controller script not found: $script"
}
$legacyTask = Get-ScheduledTask -TaskName "Magpie LCD Bridge" -ErrorAction SilentlyContinue
if ($legacyTask) {
    throw "The legacy scheduled task 'Magpie LCD Bridge' is still installed. Run scripts\uninstall-autostart.ps1 first."
}

Start-Process `
    -FilePath $python `
    -ArgumentList "`"$script`"" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden

Write-Host "Controller started. Look for the Magpie LCD Bridge tray icon."
