$ErrorActionPreference = "Stop"

$taskName = "Magpie LCD Bridge"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "Autostart task not found. Run scripts\install-autostart.ps1 first."
}

Start-ScheduledTask -TaskName $taskName
Write-Host "Started: $taskName"

