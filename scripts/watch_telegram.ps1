# ChronoScalp Telegram control bot watchdog — run as SYSTEM via Scheduled Task.
$ErrorActionPreference = "Continue"
Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR

$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = (Resolve-Path ".\src").Path

function Test-TelegramBotRunning {
  $hit = Get-CimInstance Win32_Process |
    Where-Object {
      $_.Name -match 'python' -and
      $_.CommandLine -and
      ($_.CommandLine -match 'telegram_control_bot\.py')
    }
  return [bool]$hit
}

if (Test-TelegramBotRunning) {
  Write-Output "TG_ALREADY_UP"
  exit 0
}

# Avoid duplicate pollers if a stale non-python match confused us earlier
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match 'python' -and
    $_.CommandLine -and
    ($_.CommandLine -match 'telegram_control_bot\.py')
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

New-Item -ItemType Directory -Path "logs" -Force | Out-Null

# No stdout redirect (can fail under SYSTEM if log handle stuck). Logging goes to chronoscalp_*.log.
Start-Process -FilePath $py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory (Get-Location) `
  -WindowStyle Hidden

Start-Sleep -Seconds 5
if (Test-TelegramBotRunning) {
  Write-Output "TG_STARTED_OK"
} else {
  Write-Output "TG_START_FAIL"
}
