# Poll limited walk-forward status on VPS.
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Write-Host "---PROCS---"
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'run_optimize|_vps_limited_walkforward' } |
  ForEach-Object {
    $cl = $_.CommandLine
    if ($cl.Length -gt 180) { $cl = $cl.Substring(0, 180) }
    Write-Host ("PID={0} CMD={1}" -f $_.ProcessId, $cl)
  }
Write-Host "---STDOUT---"
$out = "data\reports\vps_wf_stdout.txt"
if (Test-Path $out) { Get-Content $out -Tail 40 } else { Write-Host "MISSING_STDOUT" }
Write-Host "---REPORTS---"
Get-ChildItem "data\reports\wf_limited_*.json" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1} {2}" -f $_.Length, $_.Name, $_.LastWriteTime) }
Write-Host "WF_POLL_DONE"
