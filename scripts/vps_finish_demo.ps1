# ChronoScalp — finish LiteFinance demo setup on Windows VPS (run in Admin PowerShell on the VPS)
# Usage:
#   1) Copy مهم/.env.filled.sample.txt to C:\ChronoScalp\ChronoScalp-XAU-EUR\.env  (or edit below)
#   2) .\scripts\vps_finish_demo.ps1

$ErrorActionPreference = "Stop"
$Proj = "C:\ChronoScalp\ChronoScalp-XAU-EUR"

if (-not (Test-Path $Proj)) { throw "Project not found: $Proj" }
Set-Location $Proj

Write-Host "=== git pull ===" -ForegroundColor Cyan
git fetch origin
git reset --hard origin/main

# Ensure .env exists
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from example — fill MT5_* then re-run." -ForegroundColor Yellow
}

@"
execution:
  broker: paper
  data_source: mt5
licensing:
  require_license: false
risk:
  active_risk_per_trade_pct: 1.0
  max_risk_per_trade_pct: 1.0
alerting:
  enabled: false
"@ | Set-Content -Path "config\runtime_overrides.yaml" -Encoding UTF8

New-Item -ItemType Directory -Force -Path logs, data\state, data\spread_history, data\reports | Out-Null

# Firewall for Streamlit panel
New-NetFirewallRule -DisplayName "ChronoScalp Panel 8501" -Direction Inbound `
  -Protocol TCP -LocalPort 8501 -Action Allow -ErrorAction SilentlyContinue | Out-Null

# Stop old panel/bot
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -match "streamlit|run_live.py")
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

$py = Join-Path $Proj ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$env:PYTHONPATH = Join-Path $Proj "src"

Write-Host "=== starting panel on 0.0.0.0:8501 ===" -ForegroundColor Cyan
Start-Process -FilePath $py -ArgumentList @(
    "-m", "streamlit", "run", "scripts\app.py",
    "--server.address", "0.0.0.0",
    "--server.port", "8501",
    "--browser.gatherUsageStats", "false"
) -WorkingDirectory $Proj `
  -RedirectStandardOutput (Join-Path $Proj "logs\panel_stdout.log") `
  -RedirectStandardError (Join-Path $Proj "logs\panel_stderr.log") `
  -WindowStyle Hidden

# MT5 install if missing
$mt5 = @(
    "C:\Program Files\MetaTrader 5\terminal64.exe",
    "C:\Program Files\LiteFinance MT5 Terminal\terminal64.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $mt5) {
    Write-Host "=== downloading MetaTrader 5 setup ===" -ForegroundColor Yellow
    $setup = "C:\ChronoScalp\mt5setup.exe"
    New-Item -ItemType Directory -Force -Path "C:\ChronoScalp" | Out-Null
    Invoke-WebRequest -Uri "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" `
        -OutFile $setup -UseBasicParsing
    Start-Process -FilePath $setup -ArgumentList "/auto" -Wait
    $mt5 = @(
        "C:\Program Files\MetaTrader 5\terminal64.exe",
        "C:\Program Files\LiteFinance MT5 Terminal\terminal64.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if ($mt5) {
    Write-Host "MT5 found: $mt5" -ForegroundColor Green
    # Keep .env path in sync if default MetaTrader path exists
    (Get-Content ".env") -replace 'MT5_TERMINAL_PATH=.*', "MT5_TERMINAL_PATH=$mt5" |
        Set-Content ".env" -Encoding UTF8
    Start-Process $mt5
    Write-Host "Opened MT5 — log in with LiteFinance-MT5-Demo / your demo login." -ForegroundColor Yellow
} else {
    Write-Host "MT5 still missing — download from LiteFinance portal (DOWNLOAD TERMINAL)." -ForegroundColor Red
}

Write-Host ""
Write-Host "Panel URL (from your PC browser):" -ForegroundColor Green
Write-Host "  http://89.23.103.82:8501"
Write-Host ""
Write-Host "After MT5 is logged in, start paper bot:" -ForegroundColor Cyan
Write-Host "  cd $Proj"
Write-Host "  .\.venv\Scripts\python.exe scripts\run_live.py --mode paper"
Write-Host "Or use Control page in the panel."
