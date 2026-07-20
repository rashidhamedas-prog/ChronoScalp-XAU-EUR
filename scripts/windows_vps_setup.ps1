# ChronoScalp — one-shot setup on Windows VPS (run in PowerShell as Administrator)
# After RDP login:
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   irm https://raw.githubusercontent.com/rashidhamedas-prog/ChronoScalp-XAU-EUR/main/scripts/windows_vps_setup.ps1 | iex
# Or copy this file to the VPS and:  .\windows_vps_setup.ps1
#
# Target path matches the deployed Windows VPS layout.
# Requires Python 3.11+ (3.11/3.12 both OK). Disk: prefer 40GB+ (20GB fills fast).

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git"
$InstallDir = "C:\ChronoScalp\ChronoScalp-XAU-EUR"

Write-Host "=== ChronoScalp Windows VPS setup ===" -ForegroundColor Cyan

# --- basics ---
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Ensure-Winget {
    if (Get-Command winget -ErrorAction SilentlyContinue) { return $true }
    Write-Host "winget not found — install Python/Git manually if next steps fail."
    return $false
}

$hasWinget = Ensure-Winget

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    if ($hasWinget) {
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    } else {
        throw "Install Git from https://git-scm.com/download/win then re-run."
    }
}

# Python 3.11+
$py = $null
foreach ($c in @("py -3.12", "py -3.11", "python", "py")) {
    try {
        $v = Invoke-Expression "$c --version" 2>$null
        if ($v -match "Python 3\.(1[1-9]|[2-9]\d)") { $py = $c; break }
    } catch {}
}
if (-not $py) {
    if ($hasWinget) {
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
        $py = "py -3.12"
    } else {
        throw "Install Python 3.11+ from https://www.python.org/downloads/ (tick Add to PATH)."
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null

# Clone / update repo
if (-not (Test-Path "$InstallDir\.git")) {
    git clone $RepoUrl $InstallDir
} else {
    Push-Location $InstallDir
    git fetch origin
    git reset --hard origin/main
    Pop-Location
}

Push-Location $InstallDir
Write-Host "Installing Python packages (may take a few minutes)..."

$venvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Invoke-Expression "$py -m venv .venv"
}
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ""
    Write-Host ">>> Edit $InstallDir\.env :" -ForegroundColor Yellow
    Write-Host "    MT5_LOGIN=..."
    Write-Host "    MT5_PASSWORD=..."
    Write-Host "    MT5_SERVER=..."
}

# Runtime overrides: MT5 paper by default (Iran-friendly path; OANDA often blocked)
@"
execution:
  broker: paper
  data_source: mt5
licensing:
  require_license: false
risk:
  active_risk_per_trade_pct: 1.0
  max_risk_per_trade_pct: 1.0
"@ | Set-Content -Path "config\runtime_overrides.yaml" -Encoding UTF8

New-Item -ItemType Directory -Force -Path data\state, data\spread_history, data\reports, logs | Out-Null

# Desktop shortcuts
$desktop = [Environment]::GetFolderPath("Desktop")
$openBat = Join-Path $desktop "ChronoScalp-Open.bat"
@"
@echo off
cd /d $InstallDir
set PYTHONPATH=$InstallDir\src
".venv\Scripts\python.exe" -m streamlit run scripts\app.py --server.address 0.0.0.0 --server.port 8501
"@ | Set-Content -Path $openBat -Encoding ASCII

$readme = Join-Path $desktop "ChronoScalp-README.txt"
@"
ChronoScalp Windows VPS
=======================
Project: $InstallDir

1) Change the Windows password (never keep 123456).
2) Prefer 40GB+ disk — Windows + MT5 fills 20GB quickly.
3) Install MetaTrader 5, log into a demo account.
4) Edit .env: MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
5) Paper test:
   cd $InstallDir
   .venv\Scripts\python.exe scripts\run_live.py --mode paper
6) Panel: double-click ChronoScalp-Open.bat (port 8501)

SSH: ssh admin@YOUR_IP
"@ | Set-Content -Path $readme -Encoding UTF8

# OpenSSH Server (so Cursor/agent can help next time)
try {
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue | Out-Null
    Start-Service sshd -ErrorAction SilentlyContinue
    Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue | Out-Null
    Write-Host "OpenSSH enabled on port 22 (if capability install succeeded)." -ForegroundColor Green
} catch {
    Write-Host "OpenSSH optional step skipped: $_"
}

Pop-Location

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "1) Install & login MetaTrader 5 on this VPS"
Write-Host "2) Fill .env with MT5 credentials"
Write-Host "3) Start panel: double-click ChronoScalp-Open.bat on Desktop"
Write-Host "   or: $InstallDir\.venv\Scripts\python.exe -m streamlit run scripts\app.py --server.address 0.0.0.0 --server.port 8501"
Write-Host "4) Open firewall port 8501 if you want the panel from outside"
