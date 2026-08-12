# Dump cost-stress stderr and full stdout.
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Write-Host "---STDOUT_FULL---"
$out = "data\reports\vps_cost_stress_stdout.txt"
if (Test-Path $out) { Get-Content $out } else { Write-Host "MISSING" }
Write-Host "---STDERR_FULL---"
$err = "data\reports\vps_cost_stress_stderr.txt"
if (Test-Path $err) { Get-Content $err } else { Write-Host "MISSING" }
Write-Host "---VALIDATE_XAU---"
if (Test-Path "data\reports\validate_XAUUSD.json") { Get-Content "data\reports\validate_XAUUSD.json" }
Write-Host "---SUMMARY---"
if (Test-Path "data\reports\cost_stress_1p5x_summary.json") { Get-Content "data\reports\cost_stress_1p5x_summary.json" }
Write-Host "DUMP_DONE"
