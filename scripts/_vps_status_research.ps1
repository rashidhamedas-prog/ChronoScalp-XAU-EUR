# List python processes + cost-stress status.
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Write-Host "---PROCS---"
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'python|powershell' -and $_.CommandLine -match 'cost_stress|run_backtest|run_optimize|_vps_cost' } |
  ForEach-Object {
    $cl = $_.CommandLine
    if ($cl.Length -gt 200) { $cl = $cl.Substring(0, 200) }
    Write-Host ("PID={0} NAME={1} CMD={2}" -f $_.ProcessId, $_.Name, $cl)
  }
Write-Host "---ALL_PYTHON---"
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'python.exe' } |
  ForEach-Object {
    $cl = $_.CommandLine
    if ($null -eq $cl) { $cl = '' }
    if ($cl.Length -gt 160) { $cl = $cl.Substring(0, 160) }
    Write-Host ("PID={0} CMD={1}" -f $_.ProcessId, $cl)
  }
Write-Host "---LOG---"
$log = "data\reports\cost_stress_run.log"
if (Test-Path $log) {
  Write-Host ("LOG_SIZE={0}" -f (Get-Item $log).Length)
  Get-Content $log -Tail 40
} else { Write-Host "MISSING_LOG" }
Write-Host "---REPORTS---"
Get-ChildItem "data\reports\validate_*.json","data\reports\cost_stress_1p5x_summary.json" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1} {2}" -f $_.Length, $_.Name, $_.LastWriteTime) }
Write-Host "STATUS_DONE"
