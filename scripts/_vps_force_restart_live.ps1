# Force-kill leftover run_live PIDs then start live. Run on VPS.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $root "src"

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match "run_live\.py") } |
  ForEach-Object {
    Write-Output ("KILL_LIVE PID=$($_.ProcessId)")
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Start-Sleep -Seconds 3
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match "run_live\.py") } |
  ForEach-Object {
    Write-Output ("KILL_LIVE_RETRY PID=$($_.ProcessId)")
    & taskkill.exe /F /PID $_.ProcessId | Out-Null
  }
Start-Sleep -Seconds 2
Remove-Item (Join-Path $root "data\user\bot.stopped") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root "data\state\STOP_TRADING") -Force -ErrorAction SilentlyContinue
Write-Output "STARTING_LIVE"
& $py scripts\_vps_restart_live.py
Start-Sleep -Seconds 4
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match "run_live\.py") } |
  ForEach-Object { Write-Output ("RUNNING_LIVE PID=$($_.ProcessId)") }
Write-Output ("HEAD=" + (git rev-parse --short HEAD))
Write-Output ("HAS_PAPER_GUARD=" + (Select-String -Path "src\chronoscalp\orchestration\bootstrap.py" -Pattern "Live mode ignoring execution.broker=paper" -Quiet))
Write-Output "FORCE_RESTART_DONE"
