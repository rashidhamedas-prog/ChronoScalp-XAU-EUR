# Kill duplicate cost-stress pythons; keep newest venv one if multiple.
$ErrorActionPreference = "Continue"
$matches = @(Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'run_cost_stress_validate' })
Write-Host ("FOUND={0}" -f $matches.Count)
if ($matches.Count -le 1) {
  Write-Host "NO_DUP"
  exit 0
}
# Prefer keeping .venv\Scripts\python.exe; kill others.
$keep = $matches | Where-Object { $_.CommandLine -match '\\.venv\\Scripts\\python' } | Select-Object -First 1
if (-not $keep) { $keep = $matches | Select-Object -First 1 }
foreach ($p in $matches) {
  if ($p.ProcessId -eq $keep.ProcessId) {
    Write-Host ("KEEP {0}" -f $p.ProcessId)
    continue
  }
  Write-Host ("KILL_DUP {0}" -f $p.ProcessId)
  Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host "DEDUP_DONE"
