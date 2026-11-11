$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$allProcesses = @(Get-CimInstance Win32_Process)
$controllerIds = @(
    $allProcesses | Where-Object {
        $_.Name -in @("python.exe", "pythonw.exe") -and
        $_.CommandLine -and
        $_.CommandLine -like "*$projectRoot*magpie_lcd_control.py*"
    } | Select-Object -ExpandProperty ProcessId
)
$workerIds = @(
    $allProcesses | Where-Object {
        $_.Name -in @("python.exe", "pythonw.exe") -and
        $_.CommandLine -and
        $_.CommandLine -like "*$projectRoot*magpie_lcd.py*" -and
        $_.CommandLine -like "*run*"
    } | Select-Object -ExpandProperty ProcessId
)

$treeIds = [System.Collections.Generic.HashSet[int]]::new()
$frontier = @(@($controllerIds) + @($workerIds))
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

$targets = @($allProcesses | Where-Object {
    $treeIds.Contains([int]$_.ProcessId) -and
    $_.Name -in @("python.exe", "pythonw.exe") -and
    $_.CommandLine -like "*magpie-lcd-bridge*"
})
foreach ($process in $targets) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped the controller and project workers."
Write-Host "The LCD should return to its clock mode after BLE disconnects."
