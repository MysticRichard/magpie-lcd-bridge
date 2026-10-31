$ErrorActionPreference = "Stop"

$taskName = "Magpie LCD Bridge"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
}

$projectMarker = "magpie-lcd-bridge"
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and
    $_.CommandLine -like "*$projectMarker*magpie_lcd.py*run*"
}
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped: $taskName"
Write-Host "The LCD should return to its clock mode after BLE disconnects."

