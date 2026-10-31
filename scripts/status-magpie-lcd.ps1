$taskName = "Magpie LCD Bridge"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($task) {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
    [pscustomobject]@{
        TaskName = $taskName
        TaskState = $task.State
        LastRunTime = $taskInfo.LastRunTime
        NextRunTime = $taskInfo.NextRunTime
        LastTaskResult = $taskInfo.LastTaskResult
    } | Format-List
} else {
    Write-Host "Autostart task is not installed."
}

$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @("python.exe", "pythonw.exe") -and
    $_.CommandLine -like "*magpie-lcd-bridge*magpie_lcd.py*run*"
}
if ($processes) {
    $processes | Select-Object ProcessId, CreationDate, CommandLine | Format-List
} else {
    Write-Host "Bridge process is not running."
}

