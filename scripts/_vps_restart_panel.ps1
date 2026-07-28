# Restart Streamlit panel so new Control page code loads
$proj = 'C:\ChronoScalp\ChronoScalp-XAU-EUR'
Set-Location $proj

Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'streamlit') } |
  ForEach-Object {
    Write-Output ("Stopping streamlit PID=$($_.ProcessId)")
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Start-Sleep -Seconds 2
$py = Join-Path $proj '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$log = Join-Path $proj 'logs\panel_stdout.log'
$err = Join-Path $proj 'logs\panel_stderr.log'
$args = @('-m','streamlit','run','scripts\app.py','--server.port','8501','--server.address','0.0.0.0','--server.headless','true')
Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $proj -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err
Start-Sleep -Seconds 4
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'streamlit') } |
  ForEach-Object { Write-Output ("STARTED PID=$($_.ProcessId)") }
Write-Output 'panel restart done'
