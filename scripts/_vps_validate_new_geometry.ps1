# Baseline + 1.5x cost-stress backtest for XAUUSD and EURUSD on the NEW Delta
# stop geometry, over the exact window used by the pre-fix baselines so the
# only thing that changed is the code.
#
# Pre-fix reference (data/_analysis/*_last45d.json, window 2026-06-27..2026-08-11):
#   XAUUSD  46 trades  PF 2.114  E[R] +0.354  return +17.08%
#   EURUSD  17 trades  PF 0.591  E[R] -0.150  return  -2.99%
#
# Runs quietly and writes JSON next to the previous reports. Does not touch the
# live bot, the overlay, or the STOP_TRADING marker.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"
$env:LOG_LEVEL = "WARNING"

$py = Join-Path $root ".venv\Scripts\python.exe"
$outDir = Join-Path $root "data\reports"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$log = Join-Path $outDir "newgeom_validate.log"
Remove-Item $log -ErrorAction SilentlyContinue

$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $git) { $git = "C:\Program Files\Git\cmd\git.exe" }

"NEWGEOM_BEGIN $(Get-Date -Format o)" | Tee-Object -FilePath $log -Append
("HEAD=" + (& $git rev-parse --short HEAD)) | Tee-Object -FilePath $log -Append
("KILL_SWITCH=" + (Test-Path (Join-Path $root "data\state\STOP_TRADING"))) |
    Tee-Object -FilePath $log -Append

& $py -u scripts/run_cost_stress_validate.py `
    --symbols XAUUSD EURUSD `
    --from 2026-06-27 --to 2026-08-11 *>> $log
$exit = $LASTEXITCODE
"NEWGEOM_EXIT=$exit $(Get-Date -Format o)" | Tee-Object -FilePath $log -Append

Get-ChildItem $outDir -Filter "*.json" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-180) } |
    ForEach-Object { ("REPORT {0} {1} bytes {2}" -f $_.Name, $_.Length, $_.LastWriteTime) |
        Tee-Object -FilePath $log -Append }

"NEWGEOM_DONE" | Tee-Object -FilePath $log -Append
exit $exit
