Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
git fetch origin
git checkout main
git reset --hard origin/main
Write-Output ("HEAD=" + (git rev-parse --short HEAD))
Write-Output ("ORIGIN=" + (git rev-parse --short origin/main))
Write-Output ("ENV_EXISTS=" + (Test-Path .\.env))
Select-String -Path .\.env -Pattern 'CHRONOSCALP_CONFIRM_LIVE' -ErrorAction SilentlyContinue | ForEach-Object { $_.Line }
Write-Output ("HAS_enable_live=" + (Select-String -Path .\src\chronoscalp\saas\broker_wizard.py -Pattern 'enable_live_confirm' -Quiet))
Write-Output ("HAS_live_ui=" + (Select-String -Path .\scripts\app.py -Pattern 'live_confirm' -Quiet))
Write-Output ("HAS_gate_check=" + (Select-String -Path .\src\chronoscalp\saas\process_control.py -Pattern 'live gate check' -Quiet))

# Restart panel
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'streamlit') } |
  ForEach-Object {
    Write-Output ("Stopping streamlit PID=$($_.ProcessId)")
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Start-Sleep -Seconds 2
$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$log = Join-Path (Get-Location) 'logs\panel_stdout.log'
$err = Join-Path (Get-Location) 'logs\panel_stderr.log'
$argList = @('-m','streamlit','run','scripts\app.py','--server.port','8501','--server.address','0.0.0.0','--server.headless','true')
Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err
Start-Sleep -Seconds 5
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'streamlit') } |
  ForEach-Object { Write-Output ("PANEL_PID=$($_.ProcessId)") }

# Bot running?
$pidFile = 'data\user\bot.pid'
if (Test-Path $pidFile) {
  $botPid = (Get-Content $pidFile -Raw).Trim()
  $alive = $false
  try { Get-Process -Id ([int]$botPid) -ErrorAction Stop | Out-Null; $alive = $true } catch { $alive = $false }
  Write-Output ("BOT_PID_FILE=$botPid ALIVE=$alive")
} else {
  Write-Output 'BOT_PID_FILE=none'
}
Write-Output 'DONE'
