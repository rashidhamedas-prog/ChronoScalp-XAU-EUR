# ChronoScalp Telegram control bot watchdog — single process tree.
# Windows venv may show both .venv\python.exe and base Python312.exe; the
# latter is usually a child, not a second bot.
$ErrorActionPreference = "Continue"
$Root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  Write-Output "TG_NO_VENV"
  exit 1
}
$env:PYTHONPATH = Join-Path $Root "src"

function Get-TelegramRoots {
  $all = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -match 'telegram_control_bot\.py')
  })
  $ids = @{}
  foreach ($p in $all) { $ids[$p.ProcessId] = $p }
  $roots = @()
  foreach ($p in $all) {
    if ($ids.ContainsKey($p.ParentProcessId)) { continue }
    $roots += $p
  }
  return $roots
}

$roots = @(Get-TelegramRoots)
if ($roots.Count -gt 1) {
  foreach ($p in $roots | Select-Object -Skip 1) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Write-Output ("TG_DEDUPE_KEPT={0}" -f $roots[0].ProcessId)
  exit 0
}
if ($roots.Count -eq 1) {
  Write-Output ("TG_ALREADY_UP pid={0}" -f $roots[0].ProcessId)
  exit 0
}

New-Item -ItemType Directory -Path "logs" -Force | Out-Null
Start-Process -FilePath $Py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory $Root `
  -WindowStyle Hidden

Start-Sleep -Seconds 5
$after = @(Get-TelegramRoots)
if ($after.Count -ge 1) {
  Write-Output ("TG_STARTED_OK pid={0}" -f $after[0].ProcessId)
} else {
  Write-Output "TG_START_FAIL"
}
