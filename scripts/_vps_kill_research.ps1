Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'run_optimize|fetch_and_validate|run_cost_stress|run_backtest' } |
  ForEach-Object {
    Write-Host ("KILL {0} {1}" -f $_.ProcessId, $_.Name)
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Write-Host "KILL_DONE"
