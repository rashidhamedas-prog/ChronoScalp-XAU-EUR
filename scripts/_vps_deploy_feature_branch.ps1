# Deploy the TASK-002 feature branch ON the Windows VPS (not origin/main).
# Restarts live bot + Telegram. Does not touch gitignored overlay contents
# except by whatever was already on disk; overlay is copied separately.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$gitCandidates = @(
    "C:\Program Files\Git\cmd\git.exe",
    "C:\Program Files (x86)\Git\cmd\git.exe",
    "git"
)
$git = $null
foreach ($g in $gitCandidates) {
    if ($g -eq "git") {
        $cmd = Get-Command git -ErrorAction SilentlyContinue
        if ($cmd) { $git = $cmd.Source; break }
    } elseif (Test-Path $g) {
        $git = $g
        break
    }
}
if (-not $git) { throw "git not found on VPS" }
Write-Output ("GIT=" + $git)

$branch = "ai/TASK-002-xau-vwap-multistrat"
& $git fetch origin $branch
& $git checkout -B $branch "origin/$branch"
& $git reset --hard "origin/$branch"
Write-Output ("HEAD=" + (& $git rev-parse --short HEAD))
Write-Output ("BRANCH=" + (& $git branch --show-current))
Write-Output ("LOG=" + (& $git log -1 --oneline))

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = Join-Path $root "src"
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null

function Stop-Matching([string]$pattern) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and ($_.CommandLine -match $pattern) } |
      ForEach-Object {
        Write-Output ("STOP pattern=$pattern PID=$($_.ProcessId)")
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
      }
}

Remove-Item (Join-Path $root "data\state\STOP_TRADING") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root "data\user\bot.stopped") -Force -ErrorAction SilentlyContinue

# --- Trading bot ---
Write-Output "BOT_RESTART_BEGIN"
try {
    & $py scripts\_vps_restart_live.py
} catch {
    Write-Output ("BOT_RESTART_ERR=" + $_.Exception.Message)
}
Write-Output "BOT_RESTART_END"

# --- Telegram ---
Stop-Matching 'telegram_control_bot\.py'
Start-Sleep -Seconds 2
Start-Process -FilePath $py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $root "logs\telegram_stdout.log") `
  -RedirectStandardError (Join-Path $root "logs\telegram_stderr.log")
Start-Sleep -Seconds 4
if (Test-Path (Join-Path $root "scripts\restore_telegram_keyboard.py")) {
    try {
        & $py scripts\restore_telegram_keyboard.py
        Write-Output "TG_KEYBOARD_RESTORED"
    } catch {
        Write-Output ("TG_KEYBOARD_ERR=" + $_.Exception.Message)
    }
}

Start-Sleep -Seconds 3
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -and (
      $_.CommandLine -match 'run_live\.py' -or
      $_.CommandLine -match 'telegram_control_bot\.py'
    )
  } |
  ForEach-Object {
    $kind = "other"
    if ($_.CommandLine -match 'run_live\.py') { $kind = "bot" }
    elseif ($_.CommandLine -match 'telegram_control_bot\.py') { $kind = "telegram" }
    Write-Output ("RUNNING kind=$kind PID=$($_.ProcessId)")
  }

Write-Output "DONE"
