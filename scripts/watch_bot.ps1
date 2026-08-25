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
# Windows trims the WORKING SET of an idle background terminal down to
# ~20-30 MB within minutes, so working set cannot distinguish "loaded" from
# "hollow" and recycling on it kills a healthy terminal every few minutes.
# Private bytes (commit charge) is not trimmed: a loaded terminal sits well
# above 40 MB, a session-0 zombie stays under 20 MB.
$HollowPrivMb = 20
# Never recycle a terminal that only just came up — it is still loading.
$Mt5MinAgeSec = 300
$Mt5FailurePattern = 'IPC timeout|-10005|MT5 initialize\(\) failed|MT5 connect exhausted retries|terminal_info\(\) is None'
$Mt5HealthyPattern = 'Connected to MT5|ChronoScalp started'

function Get-NewestBotLog {
  return Get-ChildItem -Path $LogDir -Filter 'chronoscalp_*.log' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime | Select-Object -Last 1
}

function Get-LogLineTime([string]$line) {
  if ($line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
    try {
      return [datetime]::ParseExact($matches[1], 'yyyy-MM-dd HH:mm:ss', $null)
    } catch {
      return $null
    }
  }
  return $null
}

# Last line matching $Pattern wins; returns $null when the newer $ResolvedBy
# line proves the condition already cleared.
function Get-UnresolvedLogLine([string]$Pattern, [string]$ResolvedBy, [int]$TailLines = 600) {
  $log = Get-NewestBotLog
  if (-not $log) { return $null }
  $tail = @(Get-Content -Path $log.FullName -Tail $TailLines -ErrorAction SilentlyContinue)
  if ($tail.Count -eq 0) { return $null }
  $hitIdx = -1
  $hitLine = $null
  $resolvedIdx = -1
  for ($i = 0; $i -lt $tail.Count; $i++) {
    if ($tail[$i] -match $Pattern) {
      $hitIdx = $i
      $hitLine = $tail[$i]
    }
    if ($tail[$i] -match $ResolvedBy) {
      $resolvedIdx = $i
    }
  }
  if ($hitIdx -lt 0 -or $resolvedIdx -gt $hitIdx) { return $null }
  return $hitLine
}

function Test-Mt5FailingInLog([int]$WithinSeconds = 600) {
  $line = Get-UnresolvedLogLine -Pattern $Mt5FailurePattern -ResolvedBy $Mt5HealthyPattern
  if (-not $line) { return $false }
  $stamp = Get-LogLineTime $line
  if (-not $stamp) { return $false }
  return (((Get-Date) - $stamp).TotalSeconds -le $WithinSeconds)
}

# A connect is only hung when no "Connected"/"started"/"exhausted" line follows
# it. Matching on a log tail alone false-positives as soon as routine chatter
# pushes the startup banner out of view.
function Test-LiveConnectHung([int]$MinAgeSeconds = 120) {
  $line = Get-UnresolvedLogLine `
    -Pattern 'Connecting to MT5 attempt' `
    -ResolvedBy 'Connected to MT5|ChronoScalp started|MT5 connect exhausted retries'
  if (-not $line) { return $false }
  $stamp = Get-LogLineTime $line
  if (-not $stamp) { return $false }
  return (((Get-Date) - $stamp).TotalSeconds -ge $MinAgeSeconds)
}

function Get-Mt5State {
  $proc = @(Get-Process -Name terminal64 -ErrorAction SilentlyContinue)
  if (-not $proc) {
    return [pscustomobject]@{ Running = $false; PrivMb = 0; WsMb = 0; AgeSec = 0; Hollow = $true }
  }
  $privMb = [math]::Round((($proc | Measure-Object PrivateMemorySize64 -Maximum).Maximum / 1MB), 1)
  $wsMb = [math]::Round((($proc | Measure-Object WorkingSet64 -Maximum).Maximum / 1MB), 1)
  $ageSec = 0
  try {
    $oldest = ($proc | Sort-Object StartTime | Select-Object -First 1)
    $ageSec = ((Get-Date) - $oldest.StartTime).TotalSeconds
  } catch {
    $ageSec = 0
  }
  return [pscustomobject]@{
    Running = $true
    PrivMb  = $privMb
    WsMb    = $wsMb
    AgeSec  = $ageSec
    Hollow  = ($privMb -lt $HollowPrivMb)
  }
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
      Write-Watch ("mt5 loaded priv_mb={0} ws_mb={1}" -f $state.PrivMb, $state.WsMb)
      return $true
    }
    Start-Sleep -Seconds 5
  }
  $state = Get-Mt5State
  Write-Watch ("mt5 not loaded running={0} priv_mb={1}" -f $state.Running, $state.PrivMb)
  return $false
}

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

# --- MT5 terminal health -----------------------------------------------------
# Recycling MT5 tears down the live bot's IPC link, so it needs real evidence
# of a dead terminal, not a memory reading that Windows changes on its own.
$botRunning = (@(Get-LiveRoots)).Count -ge 1
$mt5 = Get-Mt5State
$recycleReason = $null
if (-not $mt5.Running) {
  $recycleReason = 'missing'
} elseif ($mt5.AgeSec -lt $Mt5MinAgeSec) {
  $recycleReason = $null
} elseif (Test-Mt5FailingInLog) {
  $recycleReason = 'ipc-failure-in-log'
} elseif ((-not $botRunning) -and $mt5.Hollow) {
  $recycleReason = ('hollow priv_mb={0}' -f $mt5.PrivMb)
}

$recycled = $false
if ($recycleReason) {
  Write-Watch ("recycling MT5 reason={0} priv_mb={1} ws_mb={2}" -f $recycleReason, $mt5.PrivMb, $mt5.WsMb)
  Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  Start-Mt5Detached
  $recycled = $true
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

$roots = @(Get-LiveRoots)
if ($roots.Count -gt 1) {
  foreach ($p in $roots | Select-Object -Skip 1) {
    Write-Watch "kill extra live root pid=$($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  $roots = @($roots[0])
}
# A recycle just severed the link on purpose; let the bot reconnect before
# judging it hung, otherwise the watchdog kills what it just disturbed.
if ($roots.Count -eq 1 -and -not $recycled) {
  $procAgeSec = 0
  try {
    $gp = Get-Process -Id $roots[0].ProcessId -ErrorAction Stop
    $procAgeSec = ((Get-Date) - $gp.StartTime).TotalSeconds
  } catch {
    $procAgeSec = 0
  }
  if ((Test-LiveConnectHung) -and $procAgeSec -ge 90) {
    Write-Watch ("kill hung MT5 connect pid={0} procAgeSec={1:N0}" -f $roots[0].ProcessId, $procAgeSec)
    Stop-Process -Id $roots[0].ProcessId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $roots = @()
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
