# Detach cost-stress so SSH disconnect does not kill the job.
$ErrorActionPreference = "Continue"
$repo = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$out = Join-Path $repo "data\reports\vps_cost_stress_stdout.txt"
$err = Join-Path $repo "data\reports\vps_cost_stress_stderr.txt"
New-Item -ItemType Directory -Force -Path (Join-Path $repo "data\reports") | Out-Null
Remove-Item $out, $err -ErrorAction SilentlyContinue
$script = Join-Path $repo "scripts\_vps_cost_stress_only.ps1"
Start-Process -FilePath "powershell.exe" `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script) `
  -WorkingDirectory $repo `
  -RedirectStandardOutput $out `
  -RedirectStandardError $err `
  -WindowStyle Hidden
Write-Host "DETACHED_OK"
Start-Sleep -Seconds 2
Get-Process python, powershell -ErrorAction SilentlyContinue |
  Select-Object -First 10 Id, ProcessName, StartTime |
  Format-Table -AutoSize |
  Out-String |
  Write-Host
