$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$script = Join-Path $projectRoot "magpie_lcd_control.py"
$taskName = "Magpie LCD Bridge Controller"

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

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`"" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start the Magpie LCD Bridge tray controller after the current user logs in." `
    -Force | Out-Null

Remove-ItemProperty `
    -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
    -Name "Magpie LCD Bridge Control" `
    -ErrorAction SilentlyContinue

& (Join-Path $PSScriptRoot "create-controller-shortcut.ps1")

Write-Host "Installed current-user logon task: $taskName"
Write-Host "The hidden controller will start after the next Windows logon."
