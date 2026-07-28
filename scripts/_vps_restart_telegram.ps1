# Pull latest main and force-restart Telegram control bot + refresh keyboard.
# Run as Administrator on the Windows VPS (RDP).
$ErrorActionPreference = "Stop"

$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
if (-not (Test-Path $root)) {
    throw "Repo not found at $root"
}
Set-Location $root

git fetch origin
git checkout main
git reset --hard origin/main
Write-Output ("HEAD=" + (git rev-parse --short HEAD))
Write-Output (git log -1 --oneline)

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $root "src"

# Kill all telegram_control_bot processes (watchdog only starts if none exist)
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'telegram_control_bot\.py') } |
  ForEach-Object {
    Write-Output ("Stopping telegram PID=$($_.ProcessId)")
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Start-Sleep -Seconds 2

Start-Process -FilePath $py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory $root `
  -WindowStyle Hidden
Start-Sleep -Seconds 4

# Push updated keyboard to the bound chat
& $py scripts\restore_telegram_keyboard.py

Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'telegram_control_bot\.py') } |
  ForEach-Object { Write-Output ("TG_PID=$($_.ProcessId)") }

Write-Output "DONE — open Telegram and check for «سشن لندن/آمریکا» / «۲۴ ساعته»"
