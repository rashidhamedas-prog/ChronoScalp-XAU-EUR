# Restart Telegram only. Do not git checkout — live deploy already set HEAD.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $root "src"
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match "telegram_control_bot\.py") } |
  ForEach-Object {
    Write-Output ("STOP_TG PID=$($_.ProcessId)")
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Start-Sleep -Seconds 2
Start-Process -FilePath $py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $root "logs\telegram_stdout.log") `
  -RedirectStandardError (Join-Path $root "logs\telegram_stderr.log")
Start-Sleep -Seconds 4
if (Test-Path (Join-Path $root "scripts\restore_telegram_keyboard.py")) {
    & $py scripts\restore_telegram_keyboard.py
    Write-Output "TG_KEYBOARD_RESTORED"
}
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match "telegram_control_bot\.py") } |
  ForEach-Object { Write-Output ("RUNNING_TG PID=$($_.ProcessId)") }
Write-Output "TG_RESTART_DONE"
