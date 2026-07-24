# ChronoScalp — full bootstrap on NEW Windows VPS (Frankfurt)
# Run ONCE in PowerShell as Administrator after RDP login.
# Usage:
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   irm https://raw.githubusercontent.com/rashidhamedas-prog/ChronoScalp-XAU-EUR/main/scripts/vps_bootstrap_win2019.ps1 | iex
# Or with env already prepared: copy this file and run .\vps_bootstrap_win2019.ps1

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git"
$InstallDir = "C:\ChronoScalp\ChronoScalp-XAU-EUR"

Write-Host "=== ChronoScalp Windows bootstrap ===" -ForegroundColor Cyan

# --- Prefer English UI (best-effort; may need reboot for full UI) ---
try {
    $LangList = New-WinUserLanguageList -Language "en-US"
    Set-WinUserLanguageList $LangList -Force
    Set-WinSystemLocale -SystemLocale en-US
    Set-WinUILanguageOverride -Language en-US
    Set-Culture en-US
    Write-Host "Language preference set to en-US (sign out/in may be required)." -ForegroundColor Green
} catch {
    Write-Host "Language change skipped: $_" -ForegroundColor Yellow
}

# --- OpenSSH ---
try {
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue | Out-Null
    Start-Service sshd -ErrorAction SilentlyContinue
    Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 `
        -ErrorAction SilentlyContinue | Out-Null
    Write-Host "OpenSSH enabled on port 22." -ForegroundColor Green
} catch {
    Write-Host "OpenSSH step: $_" -ForegroundColor Yellow
}

# --- Firewall Streamlit ---
New-NetFirewallRule -DisplayName "ChronoScalp Panel 8501" -Direction Inbound `
    -Protocol TCP -LocalPort 8501 -Action Allow -ErrorAction SilentlyContinue | Out-Null

# --- TLS ---
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Ensure-Winget {
    if (Get-Command winget -ErrorAction SilentlyContinue) { return $true }
    return $false
}
$hasWinget = Ensure-Winget

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    if ($hasWinget) {
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    } else {
        $gitSetup = "$env:TEMP\Git-64-bit.exe"
        Invoke-WebRequest -Uri "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe" -OutFile $gitSetup -UseBasicParsing
        Start-Process $gitSetup -ArgumentList "/VERYSILENT","/NORESTART" -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    }
}

# Python 3.11+
$py = $null
foreach ($c in @("py -3.12","py -3.11","python","py")) {
    try {
        $v = & cmd /c "$c --version" 2>$null
        if ("$v" -match "Python 3\.(1[1-9]|[2-9]\d)") { $py = $c; break }
    } catch {}
}
if (-not $py) {
    if ($hasWinget) {
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $py = "py -3.12"
    } else {
        $pySetup = "$env:TEMP\python-3.12.4-amd64.exe"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe" -OutFile $pySetup -UseBasicParsing
        Start-Process $pySetup -ArgumentList "/quiet","InstallAllUsers=1","PrependPath=1","Include_test=0" -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $py = "py -3.12"
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
if (-not (Test-Path "$InstallDir\.git")) {
    git clone $RepoUrl $InstallDir
} else {
    Push-Location $InstallDir
    git fetch origin
    git reset --hard origin/main
    Pop-Location
}

Push-Location $InstallDir
$venvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Invoke-Expression "$py -m venv .venv"
}
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

# .env — filled if MT5_* env vars provided; else from example
if (-not (Test-Path ".env")) {
    if ($env:MT5_LOGIN -and $env:MT5_PASSWORD -and $env:MT5_SERVER) {
        @"
MT5_LOGIN=$($env:MT5_LOGIN)
MT5_PASSWORD=$($env:MT5_PASSWORD)
MT5_SERVER=$($env:MT5_SERVER)
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
CHRONOSCALP_CONFIRM_LIVE=no
CHRONOSCALP_STOP_TRADING=no
LICENSE_ADMIN_SECRET=chrono-local-dev-only
NEWS_API_KEY=$($env:NEWS_API_KEY)
CHRONOSCALP_ENV=production
LOG_LEVEL=INFO
"@ | Set-Content ".env" -Encoding UTF8
    } else {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from example — fill MT5_* before paper trading." -ForegroundColor Yellow
    }
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
"@ | Set-Content "config\runtime_overrides.yaml" -Encoding UTF8

New-Item -ItemType Directory -Force -Path data\state, data\spread_history, data\reports, logs | Out-Null

# Desktop launcher
$desktop = [Environment]::GetFolderPath("Desktop")
@"
@echo off
cd /d $InstallDir
set PYTHONPATH=$InstallDir\src
".venv\Scripts\python.exe" -m streamlit run scripts\app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
"@ | Set-Content (Join-Path $desktop "ChronoScalp-Open.bat") -Encoding ASCII

# Stop old panel
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and ($_.CommandLine -match "streamlit")
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$env:PYTHONPATH = Join-Path $InstallDir "src"
Start-Process -FilePath $venvPython -ArgumentList @(
    "-m","streamlit","run","scripts\app.py",
    "--server.address","0.0.0.0",
    "--server.port","8501",
    "--browser.gatherUsageStats","false"
) -WorkingDirectory $InstallDir `
  -RedirectStandardOutput (Join-Path $InstallDir "logs\panel_stdout.log") `
  -RedirectStandardError (Join-Path $InstallDir "logs\panel_stderr.log") `
  -WindowStyle Hidden

Pop-Location

$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } | Select-Object -First 1 -ExpandProperty IPAddress)
Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Green
Write-Host "Panel: http://$ip`:8501  (also try the public IPv4 from hosting panel)"
Write-Host "Next: install MetaTrader 5, login LiteFinance demo, then paper:"
Write-Host "  cd $InstallDir"
Write-Host "  .\.venv\Scripts\python.exe scripts\run_live.py --mode paper"
