# Detach the new-geometry validation so an SSH disconnect does not kill it.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$reports = Join-Path $root "data\reports"
New-Item -ItemType Directory -Force -Path $reports | Out-Null
$out = Join-Path $reports "newgeom_stdout.txt"
$err = Join-Path $reports "newgeom_stderr.txt"
Remove-Item $out, $err -ErrorAction SilentlyContinue

$script = Join-Path $root "scripts\_vps_validate_new_geometry.ps1"
if (-not (Test-Path $script)) { throw "missing $script" }

Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script) `
    -WorkingDirectory $root `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -WindowStyle Hidden

Write-Output "DETACHED_OK"
Start-Sleep -Seconds 8
$log = Join-Path $reports "newgeom_validate.log"
if (Test-Path $log) {
    Write-Output "--- early log ---"
    Get-Content $log -Tail 20
}
Write-Output ("KILL_SWITCH_STILL_SET=" + (Test-Path (Join-Path $root "data\state\STOP_TRADING")))
