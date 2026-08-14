# LIMITED walk-forward on VPS for XAUUSD / EURUSD only.
# Uses last ~45 calendar days of available M1 history and folds=2 with metric expectancy_r.
# Does NOT enable live or change risk.
$ErrorActionPreference = "Continue"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"
$env:LOG_LEVEL = "WARNING"
$py = ".\.venv\Scripts\python.exe"

Write-Host ("HEAD={0}" -f (git rev-parse --short HEAD))
New-Item -ItemType Directory -Force -Path "data\reports" | Out-Null

$WindowDays = 45
$sep = [char]59  # ';' delimiter from probe (avoid '|' PowerShell pipe issues)

foreach ($sym in @("XAUUSD", "EURUSD")) {
  $report = "data/reports/wf_limited_$sym.json"

  $probeCode = @(
    "from pathlib import Path"
    "import pandas as pd"
    "from chronoscalp.utils.types import Timeframe"
    "from chronoscalp.data.mt5_connector import history_csv_path"
    "path = history_csv_path(Path('data/history'), '$sym', Timeframe.M1)"
    "if not path.exists():"
    "    print('MISSING')"
    "    raise SystemExit(0)"
    "df = pd.read_csv(path, usecols=['time'], parse_dates=['time'])"
    "if df.empty:"
    "    print('EMPTY')"
    "    raise SystemExit(0)"
    "end = pd.Timestamp(df['time'].max())"
    "start = end - pd.Timedelta(days=$WindowDays)"
    "fmt = '%Y-%m-%d'"
    "print(start.strftime(fmt) + ';' + end.strftime(fmt))"
  ) -join "`n"

  $probe = & $py -c $probeCode
  $probeLine = ($probe | Select-Object -Last 1)
  if ($null -ne $probeLine) { $probeLine = $probeLine.ToString().Trim() }

  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($probeLine) -or $probeLine -match '^(MISSING|EMPTY)$') {
    Write-Host ("WARNING: could not probe M1 range for {0} ({1}). Falling back to folds=2 without date filter." -f $sym, $probeLine)
    Write-Host ("WALKFORWARD_LIMITED_BEGIN {0} (no date filter) tiny-grid" -f $sym)
    & $py scripts/run_optimize.py --symbol $sym --mode walk-forward --folds 2 --metric expectancy_r --tiny-grid --report $report
  }
  else {
    $parts = $probeLine.Split($sep)
    $dateFrom = $parts[0]
    $dateTo = $parts[1]
    Write-Host ("WALKFORWARD_LIMITED_BEGIN {0} from={1} to={2} folds=2 metric=expectancy_r tiny-grid" -f $sym, $dateFrom, $dateTo)
    & $py scripts/run_optimize.py --symbol $sym --mode walk-forward --folds 2 --metric expectancy_r --tiny-grid --from $dateFrom --to $dateTo --report $report
  }

  Write-Host ("WALKFORWARD_LIMITED_EXIT_{0}={1}" -f $sym, $LASTEXITCODE)
  if (Test-Path $report) {
    Write-Host ("REPORT_SIZE_{0}={1} {2}" -f $sym, (Get-Item $report).Length, $report)
  }
  else {
    Write-Host ("REPORT_SIZE_{0}=MISSING {1}" -f $sym, $report)
  }
}

Write-Host "REPORTS"
Get-ChildItem "data\reports\wf_limited_*.json" -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Host ("{0} {1}" -f $_.Length, $_.Name) }
Write-Host "DONE"
