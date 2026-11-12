# Register an interactive At-logon task for the current user. Not a Windows service.
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$taskName = "ChronoScalpRunner"
$script = Join-Path $PSScriptRoot "start_runner.ps1"
$arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force -Description "Start ChronoScalp in paper mode when this user logs on. Runs only in the interactive session." | Out-Null
Write-Output "Registered scheduled task $taskName for $env:USERNAME at logon (Limited, interactive)."
