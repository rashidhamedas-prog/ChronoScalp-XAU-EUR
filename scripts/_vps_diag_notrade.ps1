# Read-only diagnosis: why has the live bot not opened a trade recently?
# Runs ON the Windows VPS. Prints process state, MT5 health, kill-switch
# markers, overlay, and the entry-skip reasons from the newest log.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

Write-Output ("NOW_LOCAL=" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Output ("NOW_UTC=" + ((Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss")))
Write-Output ("HEAD=" + (& git rev-parse --short HEAD 2>$null))
Write-Output ("BRANCH=" + (& git branch --show-current 2>$null))

Write-Output "=== PROCESSES ==="
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_live|telegram_control_bot|streamlit') } |
  ForEach-Object {
    $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
    Write-Output ("PROC pid=" + $_.ProcessId + " start=" + $p.StartTime + " cmd=" + $_.CommandLine)
  }

Write-Output "=== MT5 TERMINAL ==="
Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Output ("MT5 pid=" + $_.Id + " wsMB=" + [math]::Round($_.WorkingSet64/1MB) + " start=" + $_.StartTime)
}

Write-Output "=== KILL SWITCH MARKERS ==="
foreach ($m in @("data\state\STOP_TRADING", "data\user\bot.stopped", "data\user\bot.pid")) {
  if (Test-Path $m) {
    $i = Get-Item $m
    Write-Output ("MARKER " + $m + " mtime=" + $i.LastWriteTime + " content=" + ((Get-Content $m -Raw -ErrorAction SilentlyContinue) -replace "\r?\n", " "))
  } else {
    Write-Output ("MARKER " + $m + " ABSENT")
  }
}

Write-Output "=== OVERLAY (runtime_overrides.yaml) ==="
if (Test-Path "config\runtime_overrides.yaml") {
  Get-Content "config\runtime_overrides.yaml" -Raw
} else {
  Write-Output "NO OVERLAY"
}

Write-Output "=== LOG FILES ==="
Get-ChildItem logs -File | Sort-Object LastWriteTime -Descending |
  Select-Object -First 6 Name, Length, LastWriteTime |
  Format-Table -AutoSize | Out-String -Width 200

$f = Get-ChildItem "logs\chronoscalp_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Output ("NEWEST_LOG=" + $f.Name + " mtime=" + $f.LastWriteTime)
$lines = Get-Content $f.FullName

Write-Output "=== STARTUP / GATE PROFILE (last 6) ==="
$lines | Select-String -Pattern 'ChronoScalp started|Entry gate profile|Entry guards|Runtime overrides|Connected to MT5|Multi-strategy mode' |
  Select-Object -Last 12 | ForEach-Object { $_.Line }

Write-Output "=== SKIP HEARTBEAT (last 15) ==="
$lines | Select-String -Pattern 'skip heartbeat|Entry skip' | Select-Object -Last 15 | ForEach-Object { $_.Line }

Write-Output "=== OPENED / ORDER ATTEMPTS (last 15) ==="
$lines | Select-String -Pattern 'Opened |place_order|Pending |order_send|retcode' | Select-Object -Last 15 | ForEach-Object { $_.Line }

Write-Output "=== ERRORS (last 25) ==="
$lines | Select-String -Pattern 'ERROR|CRITICAL|Traceback|Exception' | Select-Object -Last 25 | ForEach-Object { $_.Line }

Write-Output "=== WARNINGS (last 20 unique-ish) ==="
$lines | Select-String -Pattern 'WARNING' | Select-Object -Last 20 | ForEach-Object { $_.Line }

Write-Output "=== TAIL 60 ==="
$lines | Select-Object -Last 60

Write-Output "=== YESTERDAY LOG SUMMARY ==="
$prev = Get-ChildItem "logs\chronoscalp_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 1 -First 1
if ($prev) {
  Write-Output ("PREV_LOG=" + $prev.Name + " mtime=" + $prev.LastWriteTime)
  $pl = Get-Content $prev.FullName
  Write-Output ("prev_lines=" + $pl.Count)
  $pl | Select-String -Pattern 'ChronoScalp started|Opened |ERROR|CRITICAL' | Select-Object -Last 20 | ForEach-Object { $_.Line }
}

Write-Output "DONE"
