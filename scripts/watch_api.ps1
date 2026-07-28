# ChronoScalp API launcher — single process tree (venv may spawn base python).
$ErrorActionPreference = 'Continue'
$Root = 'C:\ChronoScalp\ChronoScalp-XAU-EUR'
Set-Location $Root
$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
  Write-Output 'API_NO_VENV'
  exit 1
}
$env:PYTHONPATH = Join-Path $Root 'src'

$envFile = Join-Path $Root '.env'
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*CHRONOSCALP_API_TOKEN\s*=\s*(.+)\s*$') {
      $env:CHRONOSCALP_API_TOKEN = $Matches[1].Trim()
    }
  }
}
if (-not $env:CHRONOSCALP_API_TOKEN) {
  Write-Output 'API_TOKEN_MISSING'
}

function Test-ApiUp {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8510/health' -UseBasicParsing -TimeoutSec 4
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Get-ApiRoots {
  $all = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -match 'run_api\.py')
  })
  $ids = @{}
  foreach ($p in $all) { $ids[$p.ProcessId] = $p }
  $roots = @()
  foreach ($p in $all) {
    if ($ids.ContainsKey($p.ParentProcessId)) { continue }
    $roots += $p
  }
  return $roots
}

if (Test-ApiUp) {
  Write-Output 'API_ALREADY_UP'
  exit 0
}

$roots = @(Get-ApiRoots)
foreach ($p in $roots) {
  Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

New-Item -ItemType Directory -Path 'logs' -Force | Out-Null
Start-Process -FilePath $Py `
  -ArgumentList @('scripts\run_api.py','--host','0.0.0.0','--port','8510') `
  -WorkingDirectory $Root `
  -WindowStyle Hidden

Start-Sleep -Seconds 5
if (Test-ApiUp) { Write-Output 'API_STARTED_OK' } else { Write-Output 'API_START_FAIL' }
