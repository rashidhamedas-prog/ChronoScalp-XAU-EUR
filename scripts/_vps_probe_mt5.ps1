# Read-only: why is the MT5 terminal not up, and what is the live bot doing?
# terminal64.exe is a GUI app. Started from session 0 (no interactive desktop)
# it can launch and sit hollow, which the bot cannot attach to over IPC.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"

Write-Output "===== TERMINAL64 ====="
$t = @(Get-Process -Name terminal64 -ErrorAction SilentlyContinue)
Write-Output ("TERMINAL_COUNT=" + $t.Count)
foreach ($p in $t) {
    $priv = [math]::Round($p.PrivateMemorySize64 / 1MB, 1)
    $ws = [math]::Round($p.WorkingSet64 / 1MB, 1)
    Write-Output ("  pid=" + $p.Id + " priv_mb=" + $priv + " ws_mb=" + $ws + " session=" + $p.SessionId)
}
Write-Output ("EXE_EXISTS=" + (Test-Path "C:\Program Files\MetaTrader 5\terminal64.exe"))

Write-Output "===== INTERACTIVE SESSIONS ====="
& query.exe session 2>&1 | Out-String | Write-Output

Write-Output "===== MT5 TASK ====="
$info = Get-ScheduledTaskInfo -TaskName "ChronoScalpMT5" -ErrorAction SilentlyContinue
if ($info) {
    Write-Output ("last=" + $info.LastRunTime + " result=" + $info.LastTaskResult)
}
$task = Get-ScheduledTask -TaskName "ChronoScalpMT5" -ErrorAction SilentlyContinue
if ($task) {
    Write-Output ("state=" + $task.State + " runlevel=" + $task.Principal.RunLevel + " logontype=" + $task.Principal.LogonType + " userid=" + $task.Principal.UserId)
}

Write-Output "===== LIVE LOG TAIL (bot startup attempt) ====="
$log = Get-ChildItem (Join-Path $root "logs") -Filter "chronoscalp_*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) { Get-Content $log.FullName -Tail 25 } else { Write-Output "NO_LOG" }

Write-Output "===== BOT STDERR/STDOUT ====="
foreach ($f in @("logs\live_stderr.log", "logs\live_stdout.log", "logs\bot_stderr.log")) {
    $full = Join-Path $root $f
    if (Test-Path $full) {
        Write-Output ("--- " + $f + " (modified " + (Get-Item $full).LastWriteTime + ") ---")
        Get-Content $full -Tail 15
    }
}
Write-Output "PROBE_MT5_DONE"
