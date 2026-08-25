# Read-only: confirm the live bot now survives past the old ~7 minute cycle.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

Write-Output ("NOW_LOCAL=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Output ("HEAD=" + (& git rev-parse --short HEAD 2>$null))

Write-Output "=== OVERLAY PROVENANCE ==="
$ov = "config\runtime_overrides.yaml"
Write-Output ("overlay_mtime=" + (Get-Item $ov).LastWriteTime)
Get-ChildItem "config\runtime_overrides.yaml.bak-*" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Output ("backup=" + $_.Name + " mtime=" + $_.LastWriteTime) }
(Get-Content $ov | Select-String -Pattern '^symbols:' -Context 0, 6) | ForEach-Object { $_ }

Write-Output "=== LIVE BOT UPTIME ==="
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_live\.py') } |
  ForEach-Object {
    $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
    $age = [math]::Round(((Get-Date) - $p.StartTime).TotalMinutes, 1)
    Write-Output ("BOT pid=" + $_.ProcessId + " uptime_min=" + $age)
  }
Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
  $age = [math]::Round(((Get-Date) - $_.StartTime).TotalMinutes, 1)
  Write-Output ("MT5 pid=" + $_.Id + " priv_mb=" + [math]::Round($_.PrivateMemorySize64 / 1MB, 1) +
    " ws_mb=" + [math]::Round($_.WorkingSet64 / 1MB, 1) + " uptime_min=" + $age)
}

Write-Output "=== WATCHDOG DECISIONS SINCE FIX (tail 40) ==="
Get-Content "logs\bot_watchdog.log" -Tail 40

Write-Output "=== BOT STARTS TODAY ==="
$f = Get-ChildItem "logs\chronoscalp_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$l = Get-Content $f.FullName
($l | Select-String -SimpleMatch "ChronoScalp started in live mode") | Select-Object -Last 8 |
  ForEach-Object { $_.Line.Substring(0, 23) }

Write-Output "=== BTCUSD NOISE (should be zero after restart) ==="
$lastStart = ($l | Select-String -SimpleMatch "ChronoScalp started in live mode" | Select-Object -Last 1).LineNumber
$since = $l[$lastStart..($l.Count - 1)]
Write-Output ("lines_since_last_start=" + $since.Count)
Write-Output ("btc_warnings=" + (@($since | Select-String -SimpleMatch "BTCUSD")).Count)

Write-Output "=== SKIP HEARTBEAT (last 3) ==="
($l | Select-String -SimpleMatch "Entry skip heartbeat") | Select-Object -Last 3 | ForEach-Object { $_.Line }

Write-Output "=== SPREAD GUARD / ORDERS SINCE LAST START ==="
Write-Output ("spread_guard_blocks=" + (@($since | Select-String -SimpleMatch "spread guard")).Count)
@($since | Select-String -Pattern "Opened |Pending |order_send|retcode") | Select-Object -Last 10 |
  ForEach-Object { $_.Line }

Write-Output "DONE"
