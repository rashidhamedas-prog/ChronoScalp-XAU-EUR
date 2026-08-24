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

$Mt5Exe = 'C:\Program Files\MetaTrader 5\terminal64.exe'
$HollowWsMb = 30

function Get-Mt5State {
  $proc = @(Get-Process -Name terminal64 -ErrorAction SilentlyContinue)
  if (-not $proc) {
    return [pscustomobject]@{ Running = $false; WsMb = 0; Hollow = $true }
  }
  $wsMb = [math]::Round((($proc | Measure-Object WorkingSet64 -Maximum).Maximum / 1MB), 1)
  return [pscustomobject]@{ Running = $true; WsMb = $wsMb; Hollow = ($wsMb -lt $HollowWsMb) }
}

function Start-Mt5Detached {
  if (-not (Test-Path $Mt5Exe)) {
    Write-Watch "MT5_MISSING $Mt5Exe"
    return
  }
  $tr = '"{0}"' -f $Mt5Exe
  schtasks /Create /TN ChronoScalpMT5 /TR $tr /SC ONSTART /F | Out-Null
  schtasks /Run /TN ChronoScalpMT5 | Out-Null
}

function Wait-Mt5Loaded([int]$Seconds = 45) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    $state = Get-Mt5State
    if ($state.Running -and -not $state.Hollow) {
      Write-Watch ("mt5 loaded ws_mb={0}" -f $state.WsMb)
      return $true
    }
    Start-Sleep -Seconds 5
  }
  $state = Get-Mt5State
  Write-Watch ("mt5 not loaded running={0} ws_mb={1}" -f $state.Running, $state.WsMb)
  return $false
}

$mt5 = Get-Mt5State
if (-not $mt5.Running -or $mt5.Hollow) {
  Write-Watch ("recycling hollow/missing MT5 ws_mb={0}" -f $mt5.WsMb)
  Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  Start-Mt5Detached
  if (-not (Wait-Mt5Loaded -Seconds 20)) {
    Write-Watch 'HOLLOW_MT5 after recycle — starting bot anyway so initialize can launch terminal'
  }
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
    $procAgeSec = 0
    try {
      $gp = Get-Process -Id $roots[0].ProcessId -ErrorAction Stop
      $procAgeSec = ((Get-Date) - $gp.StartTime).TotalSeconds
    } catch {
      $procAgeSec = 0
    }
    $stuckConnect = ($joined -match 'Connecting to MT5|IPC timeout') -and ($joined -notmatch 'ChronoScalp started')
    if ($stuckConnect -and $procAgeSec -ge 90) {
      Write-Watch ("kill hung MT5 connect pid={0} procAgeSec={1:N0}" -f $roots[0].ProcessId, $procAgeSec)
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
