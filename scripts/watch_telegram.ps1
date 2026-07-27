# ChronoScalp Telegram control bot watchdog — prefer single .venv instance.
$ErrorActionPreference = "Continue"
$Root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  Write-Output "TG_NO_VENV"
  exit 1
}
$env:PYTHONPATH = Join-Path $Root "src"

# Kill non-venv duplicates first.
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and
  ($_.CommandLine -match 'telegram_control_bot\.py') -and
  ($_.CommandLine -match 'Python312\\python\.exe')
} | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

$venvTg = @(Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and
  ($_.CommandLine -match 'telegram_control_bot\.py') -and
  ($_.CommandLine -match '\\.venv\\Scripts\\python\.exe')
})
if ($venvTg.Count -gt 0) {
  foreach ($p in $venvTg | Select-Object -Skip 1) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Write-Output ("TG_ALREADY_UP pid={0}" -f $venvTg[0].ProcessId)
  exit 0
}

New-Item -ItemType Directory -Path "logs" -Force | Out-Null
Start-Process -FilePath $Py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory $Root `
  -WindowStyle Hidden

Start-Sleep -Seconds 5
$after = @(Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and
  ($_.CommandLine -match 'telegram_control_bot\.py') -and
  ($_.CommandLine -match '\\.venv\\Scripts\\python\.exe')
})
if ($after.Count -ge 1) {
  Write-Output ("TG_STARTED_OK pid={0}" -f $after[0].ProcessId)
} else {
  Write-Output "TG_START_FAIL"
}
