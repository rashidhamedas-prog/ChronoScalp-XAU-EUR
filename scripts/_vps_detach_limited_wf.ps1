# Detach limited walk-forward so SSH disconnect does not kill the job.
$ErrorActionPreference = "Continue"
$repo = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$out = Join-Path $repo "data\reports\vps_wf_stdout.txt"
$err = Join-Path $repo "data\reports\vps_wf_stderr.txt"
New-Item -ItemType Directory -Force -Path (Join-Path $repo "data\reports") | Out-Null
Remove-Item $out, $err -ErrorAction SilentlyContinue
$script = Join-Path $repo "scripts\_vps_limited_walkforward.ps1"
Start-Process -FilePath "powershell.exe" `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script) `
  -WorkingDirectory $repo `
  -RedirectStandardOutput $out `
  -RedirectStandardError $err `
  -WindowStyle Hidden
Write-Host "WF_DETACHED_OK"
Start-Sleep -Seconds 2
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'run_optimize|_vps_limited_walkforward' } |
  ForEach-Object { Write-Host ("PID={0}" -f $_.ProcessId) }
