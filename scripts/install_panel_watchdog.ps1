# Register the Streamlit panel watchdog as a scheduled task on the VPS.
#
# Matches the existing ChronoScalpWatchApi / WatchBot / WatchTelegram tasks:
# runs as SYSTEM every 5 minutes so it survives logoff and SSH disconnects.
# Idempotent - safe to re-run.
$ErrorActionPreference = "Stop"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$script = Join-Path $root "scripts\watch_panel.ps1"
$name = "ChronoScalpWatchPanel"

if (-not (Test-Path $script)) { throw "missing $script" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $script)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Output ("REGISTERED=" + $name)
$info = Get-ScheduledTask -TaskName $name
Write-Output ("state=" + $info.State)
& schtasks /Run /TN $name 2>&1 | Out-String | Write-Output
Start-Sleep -Seconds 15
$panel = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'streamlit') })
Write-Output ("PANEL_PROC_COUNT=" + $panel.Count)
Write-Output "INSTALL_PANEL_WATCHDOG_DONE"
