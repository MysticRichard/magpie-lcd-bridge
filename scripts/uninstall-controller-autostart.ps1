$ErrorActionPreference = "Stop"

$taskName = "Magpie LCD Bridge Controller"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Remove-ItemProperty `
    -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
    -Name "Magpie LCD Bridge Control" `
    -ErrorAction SilentlyContinue

Write-Host "Removed current-user logon task: $taskName"
