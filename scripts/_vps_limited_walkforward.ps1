# LIMITED walk-forward on VPS for XAUUSD / EURUSD only.
# Uses last ~45 calendar days of available M1 history (≈30–45 trading days)
# and folds=2 with metric expectancy_r. Does NOT enable live or change risk.
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"
$env:LOG_LEVEL = "WARNING"
$py = ".\.venv\Scripts\python.exe"

Write-Host "HEAD=$((git rev-parse --short HEAD))"
New-Item -ItemType Directory -Force -Path "data\reports" | Out-Null

# Window length: ~45 calendar days ≈ 30–35 trading days (limited, not full history).
$WindowDays = 45

foreach ($sym in @("XAUUSD", "EURUSD")) {
  $report = "data/reports/wf_limited_$sym.json"

  # Probe M1 CSV end so --from/--to cover roughly the last window of available data.
  # load_history_csv indexes by time; run_optimize filters df.index with these strings.
  $probeScript = @"
from pathlib import Path
import pandas as pd
from chronoscalp.utils.types import Timeframe
from chronoscalp.data.mt5_connector import history_csv_path

path = history_csv_path(Path('data/history'), '$sym', Timeframe.M1)
if not path.exists():
    print('MISSING')
    raise SystemExit(0)
df = pd.read_csv(path, usecols=['time'], parse_dates=['time'])
if df.empty:
    print('EMPTY')
    raise SystemExit(0)
end = pd.Timestamp(df['time'].max())
start = end - pd.Timedelta(days=$WindowDays)
fmt = '%Y-%m-%d'
print(start.strftime(fmt) + '|' + end.strftime(fmt))
"@
  $probe = & $py -c $probeScript

  if ($LASTEXITCODE -ne 0 -or -not $probe -or $probe -match '^(MISSING|EMPTY)$') {
    Write-Host "WARNING: could not probe M1 range for $sym ($probe). Falling back to folds=2 without date filter — full M1 may be slow."
    Write-Host "WALKFORWARD_LIMITED_BEGIN $sym (no date filter)"
    & $py scripts/run_optimize.py `
      --symbol $sym `
      --mode walk-forward `
      --folds 2 `
      --metric expectancy_r `
      --report $report
  }
  else {
    $parts = ($probe | Select-Object -Last 1).ToString().Trim().Split("|")
    $dateFrom = $parts[0]
    $dateTo = $parts[1]
    Write-Host "WALKFORWARD_LIMITED_BEGIN $sym from=$dateFrom to=$dateTo folds=2 metric=expectancy_r"
    & $py scripts/run_optimize.py `
      --symbol $sym `
      --mode walk-forward `
      --folds 2 `
      --metric expectancy_r `
      --from $dateFrom `
      --to $dateTo `
      --report $report
  }

  Write-Host "WALKFORWARD_LIMITED_EXIT_$sym=$LASTEXITCODE"
  if (Test-Path $report) {
    $len = (Get-Item $report).Length
    Write-Host "REPORT_SIZE_$sym=$len $report"
  }
  else {
    Write-Host "REPORT_SIZE_$sym=MISSING $report"
  }
}

Write-Host "REPORTS"
Get-ChildItem "data\reports\wf_limited_*.json" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1}" -f $_.Length, $_.Name) }
Write-Host "DONE"
