# Keep ChronoScalp control API alive on Windows VPS.

$ErrorActionPreference = 'Continue'
Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$env:CHRONOSCALP_API_TOKEN = 'Hamed95240'

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

Write-Output 'API_DOWN_RESTARTING'
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_api\.py|uvicorn') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

New-Item -ItemType Directory -Path 'logs' -Force | Out-Null

# Fully detached — do NOT redirect stdio from this session (kills child when SSH ends).
$p = Start-Process -FilePath $py `
  -ArgumentList @('scripts\run_api.py','--host','0.0.0.0','--port','8510') `
  -WorkingDirectory (Get-Location) `
  -WindowStyle Hidden `
  -PassThru
Write-Output ("SPAWN_PID=" + $p.Id)
Start-Sleep -Seconds 6

if (Test-ApiUp) { Write-Output 'API_STARTED_OK' } else { Write-Output 'API_START_FAIL' }
