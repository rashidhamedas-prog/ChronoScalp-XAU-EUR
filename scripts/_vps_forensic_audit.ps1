# Read-only forensic audit: per-strategy / per-symbol behaviour of the live bot.
# Runs ON the Windows VPS. Answers: which strategies fired, on which symbols,
# what the outcomes were, and which gate blocks EURUSD.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

Write-Output ("NOW_LOCAL=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Output ("NOW_UTC=" + ((Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss")))
Write-Output ("HEAD=" + (& git rev-parse --short HEAD 2>$null))
Write-Output ("BRANCH=" + (& git branch --show-current 2>$null))

Write-Output "=== PROCESSES ==="
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_live|telegram_control_bot|streamlit|run_api') } |
  ForEach-Object {
    $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
    Write-Output ("PROC pid=" + $_.ProcessId + " start=" + $p.StartTime)
  }
Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Output ("MT5 pid=" + $_.Id + " wsMB=" + [math]::Round($_.WorkingSet64/1MB) + " privMB=" + [math]::Round($_.PrivateMemorySize64/1MB) + " start=" + $_.StartTime)
}

Write-Output "=== OVERLAY (runtime_overrides.yaml) ==="
if (Test-Path "config\runtime_overrides.yaml") {
  Get-Content "config\runtime_overrides.yaml" -Raw
} else { Write-Output "NO OVERLAY" }

Write-Output "=== TRADE JOURNAL FILES ==="
Get-ChildItem "data" -Recurse -File -Include "trade_journal*.json","*journal*.json" -ErrorAction SilentlyContinue |
  Select-Object FullName, Length, LastWriteTime | Format-Table -AutoSize | Out-String -Width 220

Write-Output "=== STATE FILES ==="
Get-ChildItem "data\state","data\user" -File -ErrorAction SilentlyContinue |
  Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize | Out-String -Width 200

Write-Output "=== LOG FILES (last 8) ==="
Get-ChildItem "logs\chronoscalp_*.log" | Sort-Object LastWriteTime -Descending |
  Select-Object -First 8 Name, Length, LastWriteTime | Format-Table -AutoSize | Out-String -Width 200

# Analyse the last 3 days of logs together.
$logs = Get-ChildItem "logs\chronoscalp_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 3
Write-Output ("ANALYSED_LOGS=" + (($logs | ForEach-Object { $_.Name }) -join ","))
$lines = @()
foreach ($l in ($logs | Sort-Object LastWriteTime)) { $lines += Get-Content $l.FullName }
Write-Output ("TOTAL_LINES=" + $lines.Count)

Write-Output "=== STARTUP / GATE PROFILE (last 25) ==="
$lines | Select-String -Pattern 'ChronoScalp started|Entry gate profile|Entry guards|Runtime overrides|Connected to MT5|Multi-strategy|enabled_strateg|Strategies:|shadow' |
  Select-Object -Last 25 | ForEach-Object { $_.Line }

Write-Output "=== ALL 'Opened' / FILL LINES ==="
$lines | Select-String -Pattern 'Opened |OPENED|filled|Filled|trade_opened|notify_trade' | ForEach-Object { $_.Line }

Write-Output "=== ALL CLOSE LINES ==="
$lines | Select-String -Pattern 'Closed |CLOSED|closed_|record_close|exit_type|r_multiple' | ForEach-Object { $_.Line }

Write-Output "=== ORDER ATTEMPTS / RETCODES ==="
$lines | Select-String -Pattern 'place_order|order_send|retcode|Pending placed|pending_place|rejected|invalid stops|Invalid' |
  Select-Object -Last 60 | ForEach-Object { $_.Line }

Write-Output "=== SKIP HEARTBEAT (all) ==="
$lines | Select-String -Pattern 'skip heartbeat|Entry skip|skip_reason' | ForEach-Object { $_.Line }

Write-Output "=== SKIP REASON TALLY (aggregated) ==="
$tally = @{}
foreach ($ln in $lines) {
  # match reason tokens of the form SYMBOL:reason  e.g. XAUUSD:spread_ma
  foreach ($m in [regex]::Matches($ln, '([A-Z]{3,10}(?:USD|EUR|JPY|\.[a-z]{1,3})?):([a-z0-9_]{3,40})')) {
    $k = $m.Groups[1].Value + ":" + $m.Groups[2].Value
    if ($tally.ContainsKey($k)) { $tally[$k] = $tally[$k] + 1 } else { $tally[$k] = 1 }
  }
}
$tally.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 60 |
  ForEach-Object { Write-Output ("TALLY " + $_.Key + " = " + $_.Value) }

Write-Output "=== EURUSD-SPECIFIC LINES (last 120) ==="
$lines | Select-String -Pattern 'EURUSD' | Select-Object -Last 120 | ForEach-Object { $_.Line }

Write-Output "=== PER-STRATEGY MENTIONS TALLY ==="
foreach ($s in @('delta','liquidity_volume','smc_confluence','xau_vwap_pullback','news_straddle','ultra_scalp','multi_timeframe','confluence')) {
  $c = ($lines | Select-String -Pattern $s -AllMatches).Count
  Write-Output ("STRATEGY_MENTIONS " + $s + " = " + $c)
}

Write-Output "=== ERRORS (last 40) ==="
$lines | Select-String -Pattern 'ERROR|CRITICAL|Traceback|Exception' | Select-Object -Last 40 | ForEach-Object { $_.Line }

Write-Output "=== WARNINGS TALLY ==="
$wt = @{}
foreach ($ln in ($lines | Select-String -Pattern 'WARNING' | ForEach-Object { $_.Line })) {
  # strip timestamps/numbers so similar warnings group
  $k = ($ln -replace '^\S+\s+\S+\s+', '') -replace '[0-9]+(\.[0-9]+)?', 'N'
  if ($k.Length -gt 130) { $k = $k.Substring(0,130) }
  if ($wt.ContainsKey($k)) { $wt[$k] = $wt[$k] + 1 } else { $wt[$k] = 1 }
}
$wt.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 30 |
  ForEach-Object { Write-Output ("WARN x" + $_.Value + "  " + $_.Key) }

Write-Output "=== TAIL 80 ==="
$lines | Select-Object -Last 80

Write-Output "=== SYMBOL AVAILABILITY / SPREAD SNAPSHOT ==="
Get-ChildItem "data\spread_history" -File -ErrorAction SilentlyContinue |
  Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize | Out-String -Width 200

Write-Output "AUDIT_DONE"
