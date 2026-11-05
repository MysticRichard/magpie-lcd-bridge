$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$script = Join-Path $projectRoot "magpie_lcd_control.py"
$runValue = "Magpie LCD Bridge Control"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Windowless Python runtime not found: $python. Run 'uv sync' first."
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "Controller script not found: $script"
}

$legacyTask = Get-ScheduledTask -TaskName "Magpie LCD Bridge" -ErrorAction SilentlyContinue
if ($legacyTask) {
    throw "The legacy scheduled task 'Magpie LCD Bridge' is still installed. Run scripts\uninstall-autostart.ps1 first, then retry."
}

$command = "`"$python`" `"$script`""
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-ItemProperty `
    -Path $runKey `
    -Name $runValue `
    -Value $command `
    -PropertyType String `
    -Force | Out-Null

Write-Host "Installed current-user autostart: $runValue"
Write-Host "The controller will start after the next Windows logon."
