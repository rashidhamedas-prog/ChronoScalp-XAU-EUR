# Poll cost-stress status on VPS.
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Write-Host "---PROCS---"
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'run_cost_stress|_vps_cost_stress' } |
  ForEach-Object { Write-Host ("PID={0} CMD={1}" -f $_.ProcessId, $_.CommandLine) }
Write-Host "---STDOUT_TAIL---"
$out = "data\reports\vps_cost_stress_stdout.txt"
if (Test-Path $out) { Get-Content $out -Tail 40 } else { Write-Host "MISSING $out" }
Write-Host "---LOG_TAIL---"
$log = "data\reports\cost_stress_run.log"
if (Test-Path $log) { Get-Content $log -Tail 30 } else { Write-Host "MISSING $log" }
Write-Host "---REPORTS---"
Get-ChildItem "data\reports\validate_*.json","data\reports\cost_stress_1p5x_summary.json" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1} {2}" -f $_.Length, $_.Name, $_.LastWriteTime) }
Write-Host "POLL_DONE"
