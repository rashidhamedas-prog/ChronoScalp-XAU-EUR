Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR

$env:PYTHONPATH = (Resolve-Path '.\src').Path
$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'

# Stop managed bot + any stray live runners
& $py -c "from chronoscalp.saas.process_control import stop_bot; print(stop_bot())"

Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -and (
      $_.CommandLine -match 'run_live' -or
      $_.CommandLine -match 'chronoscalp.main' -or
      $_.CommandLine -match 'scripts\\run_'
    ) -and $_.CommandLine -notmatch 'streamlit' -and $_.CommandLine -notmatch 'run_api' -and $_.CommandLine -notmatch 'telegram'
  } |
  ForEach-Object {
    Write-Output ("KILL_PID=" + $_.ProcessId)
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Start-Sleep -Seconds 2
Remove-Item .\data\user\bot.pid -Force -ErrorAction SilentlyContinue

# Ensure no open tickets are re-reconciled into daily PnL on boot
$statePath = '.\data\state\trading_state_live.json'
if (Test-Path $statePath) {
  try {
    $j = Get-Content $statePath -Raw | ConvertFrom-Json
    $j.open_tickets = @{}
    $j.updated_at = (Get-Date).ToUniversalTime().ToString('o')
    # utf8NoBOM — Set-Content -Encoding utf8 on Windows PowerShell 5 writes a BOM
    # that breaks json.loads(..., encoding="utf-8") in the Streamlit panel.
    $json = $j | ConvertTo-Json -Depth 8
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText((Resolve-Path $statePath).Path, $json, $utf8NoBom)
    Write-Output 'STATE_OPEN_TICKETS_CLEARED'
  } catch {
    Write-Output ('STATE_CLEAR_FAIL=' + $_.Exception.Message)
  }
}

Write-Output 'STARTING'
& $py scripts\_vps_restart_live.py
Start-Sleep -Seconds 6
Write-Output '--- tail ---'
Get-Content .\logs\bot_stdout.log -Tail 15 -ErrorAction SilentlyContinue
