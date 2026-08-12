# Run on VPS: fetch broker-native history then validate (research only).
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$env:PYTHONPATH = "src"
$py = ".\.venv\Scripts\python.exe"

Write-Host "HEAD=$((git rev-parse --short HEAD))"
Write-Host "FETCH_XAU_BEGIN"
& $py scripts/fetch_history.py --symbol XAUUSD_o --timeframes M1 M5 M15 --years 2
Write-Host "XAU_EXIT=$LASTEXITCODE"
Write-Host "FETCH_EUR_BEGIN"
& $py scripts/fetch_history.py --symbol EURUSD_o --timeframes M1 M5 M15 --years 2
Write-Host "EUR_EXIT=$LASTEXITCODE"

Write-Host "HISTORY_FILES"
Get-ChildItem -Recurse "data\history" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1}" -f $_.Length, $_.FullName) }

New-Item -ItemType Directory -Force -Path "data\reports" | Out-Null

foreach ($sym in @("XAUUSD_o", "EURUSD_o")) {
  Write-Host "WALKFORWARD_BEGIN $sym"
  & $py scripts/run_optimize.py --symbol $sym --mode walk-forward --folds 3 --metric expectancy_r --report ("data/reports/wf_{0}.json" -f $sym)
  Write-Host "WALKFORWARD_EXIT_$sym=$LASTEXITCODE"
}

Write-Host "COST_STRESS_BEGIN"
& $py scripts/run_cost_stress_validate.py
Write-Host "COST_STRESS_EXIT=$LASTEXITCODE"

Write-Host "REPORTS"
Get-ChildItem "data\reports\*.json" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1}" -f $_.Length, $_.Name) }
Write-Host "DONE"
