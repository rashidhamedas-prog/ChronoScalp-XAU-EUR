# Report whether the live trading bot is running and on which code.
# Read-only. Used after a deploy where the bot restart reported STOP_OK=False.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$git = "C:\Program Files\Git\cmd\git.exe"
Write-Output ("HEAD=" + (& $git rev-parse --short HEAD))
Write-Output ("KILL_SWITCH=" + (Test-Path (Join-Path $root "data\state\STOP_TRADING")))

Write-Output "===== PYTHON PROCESSES ====="
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "python*" }
foreach ($p in $procs) {
    $age = "n/a"
    if ($p.CreationDate) {
        $age = [math]::Round(((Get-Date) - $p.CreationDate).TotalMinutes, 1)
    }
    $kind = "other"
    if ($p.CommandLine -match 'run_live\.py') { $kind = "BOT" }
    elseif ($p.CommandLine -match 'telegram_control_bot\.py') { $kind = "TELEGRAM" }
    elseif ($p.CommandLine -match 'run_api\.py') { $kind = "API" }
    elseif ($p.CommandLine -match 'streamlit') { $kind = "PANEL" }
    Write-Output ("kind=$kind pid=$($p.ProcessId) ppid=$($p.ParentProcessId) age_min=$age")
}

Write-Output "===== BOT COUNT ====="
$bots = @($procs | Where-Object { $_.CommandLine -match 'run_live\.py' })
Write-Output ("BOT_PROC_COUNT=" + $bots.Count)

Write-Output "===== NEWEST LIVE LOG TAIL ====="
$log = Get-ChildItem (Join-Path $root "logs") -Filter "chronoscalp_*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) {
    Write-Output ("LOG_FILE=" + $log.Name + " modified=" + $log.LastWriteTime)
    Get-Content $log.FullName -Tail 40
} else {
    Write-Output "NO_LOG_FOUND"
}
Write-Output "PROBE_DONE"
