$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$allProcesses = @(Get-CimInstance Win32_Process)
$controller = @($allProcesses | Where-Object {
    $_.Name -in @("python.exe", "pythonw.exe") -and
    $_.CommandLine -and
    $_.CommandLine -like "*$projectRoot*magpie_lcd_control.py*"
})

$controllerIds = @($controller | Select-Object -ExpandProperty ProcessId)
$treeIds = [System.Collections.Generic.HashSet[int]]::new()
$frontier = @($controllerIds)
while ($frontier.Count -gt 0) {
    $next = @()
    foreach ($id in $frontier) {
        if ($treeIds.Add([int]$id)) {
            $next += @(
                $allProcesses | Where-Object ParentProcessId -eq $id |
                    Select-Object -ExpandProperty ProcessId
            )
        }
    }
    $frontier = $next
}

$workers = @($allProcesses | Where-Object {
    $_.Name -in @("python.exe", "pythonw.exe") -and
    $_.CommandLine -and
    $_.CommandLine -like "*$projectRoot*magpie_lcd.py*" -and
    $_.CommandLine -like "*run*"
})

$startupTask = Get-ScheduledTask -TaskName "Magpie LCD Bridge Controller" -ErrorAction SilentlyContinue
[pscustomobject]@{
    Controller = if ($controller.Count -gt 0) { "Running" } else { "Stopped" }
    Worker = if ($workers.Count -gt 0) { "Running" } else { "Stopped" }
    Autostart = if ($startupTask -and $startupTask.Settings.Enabled) { "Enabled" } else { "Disabled" }
    StartupTask = if ($startupTask) { [string]$startupTask.State } else { "Not installed" }
} | Format-List

$legacyTask = Get-ScheduledTask -TaskName "Magpie LCD Bridge" -ErrorAction SilentlyContinue
if ($legacyTask) {
    Write-Host "Note: legacy scheduled task 'Magpie LCD Bridge' is installed ($($legacyTask.State))."
    Write-Host "Do not enable both the legacy task and controller autostart."
}
