# Register PDAgent as a logon scheduled task so calls are answered whenever
# this PC is on and Scott is logged in. Run once, elevated not required:
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$launch = Join-Path $root "scripts\launch.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launch`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Days 30) -StartWhenAvailable
Register-ScheduledTask -TaskName "PDAgent voice assistant" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Sophie answers forwarded calls (Twilio + Grok voice)" -Force
Write-Output "Task 'PDAgent voice assistant' registered (runs at logon)."
