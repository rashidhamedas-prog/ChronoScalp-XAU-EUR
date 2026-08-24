# Keep ChronoScalp live bot running (single process tree).
# On Windows, .venv\Scripts\python.exe often spawns the base Python312.exe as
# a child with the same script args — do NOT treat that as a duplicate.
$ErrorActionPreference = 'Continue'
$Root = 'C:\ChronoScalp\ChronoScalp-XAU-EUR'
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Script = Join-Path $Root 'scripts\run_live.py'
$LogDir = Join-Path $Root 'logs'
$WatchLog = Join-Path $LogDir 'bot_watchdog.log'
$PidFile = Join-Path $Root 'data\user\bot.pid'
$StopMarker = Join-Path $Root 'data\user\bot.stopped'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $PidFile) | Out-Null

function Write-Watch([string]$msg) {
  $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
  Add-Content -Path $WatchLog -Value $line -Encoding utf8
}

if (Test-Path $StopMarker) {
  Write-Watch 'operator stop marker present — not starting'
  exit 0
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

function Get-LiveRoots {
  $all = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -match 'run_live\.py')
  })
  $ids = @{}
  foreach ($p in $all) { $ids[$p.ProcessId] = $p }
  $roots = @()
  foreach ($p in $all) {
    if ($ids.ContainsKey($p.ParentProcessId)) {
      continue  # child of another run_live process (venv launcher pattern)
    }
    $roots += $p
  }
  return $roots
}

$roots = @(Get-LiveRoots)
if ($roots.Count -gt 1) {
  foreach ($p in $roots | Select-Object -Skip 1) {
    Write-Watch "kill extra live root pid=$($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  $roots = @($roots[0])
}
if ($roots.Count -eq 1) {
  $latest = Get-ChildItem -Path $LogDir -Filter 'chronoscalp_*.log' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime | Select-Object -Last 1
  if ($latest) {
    $tail = @(Get-Content -Path $latest.FullName -Tail 20 -ErrorAction SilentlyContinue)
    $joined = $tail -join "`n"
    $ageMin = ((Get-Date) - $latest.LastWriteTime).TotalMinutes
    $stuckConnect = ($joined -match 'Connecting to MT5|IPC timeout') -and ($joined -notmatch 'ChronoScalp started')
    if ($stuckConnect -and $ageMin -ge 4) {
      Write-Watch ("kill hung MT5 connect pid={0} logAgeMin={1:N1}" -f $roots[0].ProcessId, $ageMin)
      Stop-Process -Id $roots[0].ProcessId -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 2
      $roots = @()
    }
  }
}
if ($roots.Count -eq 1) {
  Set-Content -Path $PidFile -Value $roots[0].ProcessId -Encoding ascii
  Write-Watch "already running pid=$($roots[0].ProcessId)"
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
