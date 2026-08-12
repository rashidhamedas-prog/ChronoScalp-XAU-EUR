# Baseline + 1.5x cost stress only (skip full walk-forward grid; too slow on 100k M1).
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$env:PYTHONPATH = "src"
$py = ".\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path "data\reports" | Out-Null
Write-Host "HEAD=$((git rev-parse --short HEAD))"
Write-Host "HISTORY_FILES"
Get-ChildItem -Recurse "data\history" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1}" -f $_.Length, $_.FullName) }
Write-Host "COST_STRESS_BEGIN"
& $py scripts/run_cost_stress_validate.py --symbols XAUUSD EURUSD
Write-Host "COST_STRESS_EXIT=$LASTEXITCODE"
Write-Host "REPORTS"
Get-ChildItem "data\reports\validate_*.json","data\reports\cost_stress_1p5x_summary.json" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1}" -f $_.Length, $_.Name) }
Write-Host "DONE"
