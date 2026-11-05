$ErrorActionPreference = "Stop"

$runValue = "Magpie LCD Bridge Control"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

Remove-ItemProperty -Path $runKey -Name $runValue -ErrorAction SilentlyContinue
Write-Host "Removed current-user autostart: $runValue"
