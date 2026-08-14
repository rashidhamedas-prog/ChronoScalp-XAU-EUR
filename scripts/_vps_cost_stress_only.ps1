# Quiet limited cost-stress; minimal console so Start-Process redirects stay small.
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"
$env:LOG_LEVEL = "WARNING"
$py = ".\.venv\Scripts\python.exe"
$LastDays = 45
$log = "data\reports\cost_stress_run.log"
New-Item -ItemType Directory -Force -Path "data\reports" | Out-Null
"HEAD=$((git rev-parse --short HEAD))" | Tee-Object -FilePath $log
"COST_STRESS_BEGIN last_days=$LastDays $(Get-Date -Format o)" | Tee-Object -FilePath $log -Append
& $py -u scripts/run_cost_stress_validate.py --symbols XAUUSD EURUSD --last-days $LastDays *>> $log
$exit = $LASTEXITCODE
"COST_STRESS_EXIT=$exit $(Get-Date -Format o)" | Tee-Object -FilePath $log -Append
Get-ChildItem "data\reports\validate_XAUUSD.json","data\reports\validate_EURUSD.json","data\reports\cost_stress_1p5x_summary.json" -ErrorAction SilentlyContinue |
  ForEach-Object { "{0} {1}" -f $_.Length, $_.Name | Tee-Object -FilePath $log -Append }
"DONE" | Tee-Object -FilePath $log -Append
exit $exit
