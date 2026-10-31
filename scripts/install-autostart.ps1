$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$script = Join-Path $projectRoot "magpie_lcd.py"
$taskName = "Magpie LCD Bridge"
$userId = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python. Run 'uv sync' first."
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "Bridge script not found: $script"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$script`" --log-file `"logs\magpie-lcd.log`" run --interval 60" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
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
    -Description "Read Magpie usage and quotas and display them on the DA14585 BLE LCD." `
    -Force | Out-Null

Write-Host "Installed: $taskName"
Write-Host "It will start automatically at the next Windows logon."
Write-Host "Use scripts\start-magpie-lcd.ps1 to start it now."

