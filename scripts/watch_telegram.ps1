# ChronoScalp Telegram control bot watchdog — run as SYSTEM via Scheduled Task.
$ErrorActionPreference = "Continue"
Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR

$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = (Resolve-Path ".\src").Path

function Test-TelegramBotRunning {
  $hit = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'telegram_control_bot\.py') }
  return [bool]$hit
}

if (Test-TelegramBotRunning) {
  Write-Output "TG_ALREADY_UP"
  exit 0
}

New-Item -ItemType Directory -Path "logs" -Force | Out-Null
$log = Join-Path (Get-Location) "logs\telegram_bot_stdout.log"
$err = Join-Path (Get-Location) "logs\telegram_bot_stderr.log"

Start-Process -FilePath $py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory (Get-Location) `
  -WindowStyle Hidden `
  -RedirectStandardOutput $log `
  -RedirectStandardError $err

Start-Sleep -Seconds 4
if (Test-TelegramBotRunning) {
  Write-Output "TG_STARTED_OK"
} else {
  Write-Output "TG_START_FAIL"
  if (Test-Path $err) { Get-Content $err -Tail 30 }
}
