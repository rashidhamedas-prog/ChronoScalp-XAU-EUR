# Clear the deploy-debris bot.stopped marker and let the watchdog start the bot.
#
# `_vps_restart_live.py` writes data\user\bot.stopped before killing the bot and
# removes it on a successful start. When the stop reports failure the start is
# skipped, so the marker survives and watch_bot.ps1 then refuses to start the
# bot forever ("operator stop marker present"). That leaves the bot down while
# git and the watchdog both look healthy.
#
# The STOP_TRADING kill switch is never touched here: this restores the process,
# not live risk. Pass -MaxMarkerAgeMinutes to refuse a marker old enough to be a
# real operator decision rather than deploy debris.
param(
    [int]$MaxMarkerAgeMinutes = 60
)
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$marker = Join-Path $root "data\user\bot.stopped"
$killFile = Join-Path $root "data\state\STOP_TRADING"

Write-Output ("KILL_SWITCH=" + (Test-Path $killFile) + " (untouched by this script)")

if (-not (Test-Path $marker)) {
    Write-Output "MARKER_ABSENT=True"
} else {
    $age = [math]::Round(((Get-Date) - (Get-Item $marker).LastWriteTime).TotalMinutes, 1)
    Write-Output ("MARKER_AGE_MIN=" + $age)
    if ($age -gt $MaxMarkerAgeMinutes) {
        Write-Output ("REFUSING: marker older than $MaxMarkerAgeMinutes min - treat as a real operator stop, not deploy debris")
        exit 1
    }
    Remove-Item $marker -Force -ErrorAction SilentlyContinue
    Write-Output ("MARKER_REMOVED=" + (-not (Test-Path $marker)))
}

Write-Output "===== TRIGGER WATCHDOG ====="
schtasks /Run /TN ChronoScalpWatchBot 2>&1 | Out-String | Write-Output
Start-Sleep -Seconds 45

$bots = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_live\.py') })
Write-Output ("BOT_PROC_COUNT=" + $bots.Count)
foreach ($b in $bots) { Write-Output ("BOT pid=" + $b.ProcessId + " ppid=" + $b.ParentProcessId) }

Write-Output ("KILL_SWITCH_FINAL=" + (Test-Path $killFile))
Write-Output "===== WATCHDOG TAIL ====="
$wd = Join-Path $root "logs\bot_watchdog.log"
if (Test-Path $wd) { Get-Content $wd -Tail 8 }
Write-Output "START_ATTEMPT_DONE"

