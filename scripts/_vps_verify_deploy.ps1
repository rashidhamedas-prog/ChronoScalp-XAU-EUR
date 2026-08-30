# Read-only end-to-end proof that a deploy actually reached the running bot.
#
# A repo at the right commit proves nothing: the live bleed happened while the
# checkout was current and the *process* was running older code. These checks
# read the startup lines the new code emits, so they fail if the process is
# stale even when git looks correct.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$git = "C:\Program Files\Git\cmd\git.exe"
Write-Output ("HEAD=" + (& $git rev-parse --short HEAD))
Write-Output ("KILL_SWITCH=" + (Test-Path (Join-Path $root "data\state\STOP_TRADING")))
Write-Output ("OPERATOR_STOP_MARKER=" + (Test-Path (Join-Path $root "data\user\bot.stopped")))

Write-Output "===== PROCESSES ====="
$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine })
foreach ($kind in @("run_live\.py", "telegram_control_bot\.py", "run_api\.py", "streamlit")) {
    $hits = @($procs | Where-Object { $_.CommandLine -match $kind })
    $label = switch ($kind) {
        "run_live\.py" { "BOT" }
        "telegram_control_bot\.py" { "TELEGRAM" }
        "run_api\.py" { "API" }
        default { "PANEL" }
    }
    $pids = ($hits | ForEach-Object { $_.ProcessId }) -join ","
    Write-Output ("$label count=" + $hits.Count + " pids=" + $pids)
}

Write-Output "===== NEW STARTUP LINES IN LIVE LOG ====="
$log = Get-ChildItem (Join-Path $root "logs") -Filter "chronoscalp_*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $log) {
    Write-Output "NO_LOG_FOUND"
} else {
    Write-Output ("LOG=" + $log.Name)
    $tail = @(Get-Content $log.FullName -Tail 400 -ErrorAction SilentlyContinue)
    foreach ($pat in @("Stop geometry:", "no positive broker-native evidence", "Entry gate profile:", "Entry guards:", "ChronoScalp started")) {
        # -SimpleMatch already treats the pattern literally; regex-escaping it
        # too makes every pattern with a space or colon miss.
        $hit = @($tail | Select-String -Pattern $pat -SimpleMatch) | Select-Object -Last 1
        if ($hit) {
            Write-Output ("FOUND >> " + $hit.Line.Trim())
        } else {
            Write-Output ("MISSING >> " + $pat)
        }
    }
}

Write-Output "===== WATCHDOG TAIL ====="
$wd = Join-Path $root "logs\bot_watchdog.log"
if (Test-Path $wd) { Get-Content $wd -Tail 12 } else { Write-Output "NO_WATCHDOG_LOG" }
Write-Output "VERIFY_DONE"
