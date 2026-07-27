# Keep ChronoScalp live bot running (single venv instance).
$ErrorActionPreference = 'Continue'
$Root = 'C:\ChronoScalp\ChronoScalp-XAU-EUR'
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Script = Join-Path $Root 'scripts\run_live.py'
$LogDir = Join-Path $Root 'logs'
$WatchLog = Join-Path $LogDir 'bot_watchdog.log'
$PidFile = Join-Path $Root 'data\user\bot.pid'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $PidFile) | Out-Null

function Write-Watch([string]$msg) {
  $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
  Add-Content -Path $WatchLog -Value $line -Encoding utf8
}

if (-not (Test-Path $Py)) {
  Write-Watch 'NO_VENV'
  exit 1
}

if (Test-Path (Join-Path $Root '.env')) {
  Get-Content (Join-Path $Root '.env') | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
      Set-Item -Path ("Env:" + $matches[1].Trim()) -Value $matches[2].Trim()
    }
  }
}
$env:CHRONOSCALP_CONFIRM_LIVE = 'yes'
$env:PYTHONPATH = Join-Path $Root 'src'

# Kill non-venv duplicates
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and ($_.CommandLine -match 'run_live\.py') -and ($_.CommandLine -match 'Python312\\python\.exe')
} | ForEach-Object {
  Write-Watch "kill sys-python duplicate pid=$($_.ProcessId)"
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

$venvLive = @(Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and ($_.CommandLine -match 'run_live\.py') -and ($_.CommandLine -match '\\.venv\\Scripts\\python\.exe')
})
if ($venvLive.Count -gt 0) {
  $pidLive = $venvLive[0].ProcessId
  foreach ($p in $venvLive | Select-Object -Skip 1) {
    Write-Watch "kill extra venv pid=$($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Set-Content -Path $PidFile -Value $pidLive -Encoding ascii
  Write-Watch "already running pid=$pidLive"
  exit 0
}

if (Test-Path $PidFile) {
  Write-Watch 'clearing stale pidfile'
  Remove-Item $PidFile -Force -EA SilentlyContinue
}

$p = Start-Process -FilePath $Py `
  -ArgumentList @($Script, '--mode', 'live') `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -PassThru

if (-not $p) {
  Write-Watch 'Start-Process failed'
  exit 1
}

Set-Content -Path $PidFile -Value $p.Id -Encoding ascii
Write-Watch "started pid=$($p.Id)"
Start-Sleep -Seconds 12

if ($p.HasExited) {
  Write-Watch "EARLY_EXIT code=$($p.ExitCode)"
  Remove-Item $PidFile -Force -EA SilentlyContinue
  exit 1
}

Write-Watch "healthy after 12s pid=$($p.Id)"
exit 0
