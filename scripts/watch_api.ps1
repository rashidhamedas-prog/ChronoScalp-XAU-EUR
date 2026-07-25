# ChronoScalp API launcher — intended to run as SYSTEM via Scheduled Task.
$ErrorActionPreference = 'Continue'
Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path '.\src').Path

# Load token from .env if present
$envFile = Join-Path (Get-Location) '.env'
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*CHRONOSCALP_API_TOKEN\s*=\s*(.+)\s*$') {
      $env:CHRONOSCALP_API_TOKEN = $Matches[1].Trim()
    }
  }
}
if (-not $env:CHRONOSCALP_API_TOKEN) { $env:CHRONOSCALP_API_TOKEN = 'Hamed95240' }

function Test-ApiUp {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8510/health' -UseBasicParsing -TimeoutSec 4
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

if (Test-ApiUp) {
  Write-Output 'API_ALREADY_UP'
  exit 0
}

Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_api\.py') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

New-Item -ItemType Directory -Path 'logs' -Force | Out-Null
Start-Process -FilePath $py `
  -ArgumentList @('scripts\run_api.py','--host','0.0.0.0','--port','8510') `
  -WorkingDirectory (Get-Location) `
  -WindowStyle Hidden

Start-Sleep -Seconds 5
if (Test-ApiUp) { Write-Output 'API_STARTED_OK' } else { Write-Output 'API_START_FAIL' }
