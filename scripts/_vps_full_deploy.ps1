# Full ChronoScalp deploy ON the Windows VPS (run as Administrator).
# Pulls origin/main, restarts panel / Control API / live bot / Telegram.
# Clears STOP_TRADING marker so entries can resume after deploy.
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

& $git fetch origin
& $git checkout main
& $git reset --hard origin/main
Write-Output ("HEAD=" + (& $git rev-parse --short HEAD))
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

# Clear sticky kill switch (env should already be CHRONOSCALP_STOP_TRADING=no)
Remove-Item (Join-Path $root "data\state\STOP_TRADING") -Force -ErrorAction SilentlyContinue
Write-Output ("KILL_FILE_GONE=" + (-not (Test-Path (Join-Path $root "data\state\STOP_TRADING"))))

New-NetFirewallRule -DisplayName "ChronoScalp Panel 8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow -ErrorAction SilentlyContinue | Out-Null
New-NetFirewallRule -DisplayName "ChronoScalp API 8510" -Direction Inbound -Protocol TCP -LocalPort 8510 -Action Allow -ErrorAction SilentlyContinue | Out-Null

# --- Panel ---
Stop-Matching 'streamlit'
Start-Sleep -Seconds 2
Start-Process -FilePath $py `
  -ArgumentList @("-m","streamlit","run","scripts\app.py","--server.port","8501","--server.address","0.0.0.0","--server.headless","true") `
  -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $root "logs\panel_stdout.log") `
  -RedirectStandardError (Join-Path $root "logs\panel_stderr.log")
Write-Output "PANEL_START_ISSUED"

# --- Control API ---
Stop-Matching 'run_api\.py'
Start-Sleep -Seconds 1
Start-Process -FilePath $py `
  -ArgumentList @("scripts\run_api.py","--host","0.0.0.0","--port","8510") `
  -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $root "logs\api_stdout.log") `
  -RedirectStandardError (Join-Path $root "logs\api_stderr.log")
Write-Output "API_START_ISSUED"

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
      $_.CommandLine -match 'streamlit' -or
      $_.CommandLine -match 'run_api\.py' -or
      $_.CommandLine -match 'run_live\.py' -or
      $_.CommandLine -match 'telegram_control_bot\.py'
    )
  } |
  ForEach-Object {
    $kind = "other"
    if ($_.CommandLine -match 'streamlit') { $kind = "panel" }
    elseif ($_.CommandLine -match 'run_api\.py') { $kind = "api" }
    elseif ($_.CommandLine -match 'run_live\.py') { $kind = "bot" }
    elseif ($_.CommandLine -match 'telegram_control_bot\.py') { $kind = "telegram" }
    Write-Output ("RUNNING kind=$kind PID=$($_.ProcessId)")
  }

Write-Output ("HAS_news_straddle=" + (Test-Path (Join-Path $root "src\chronoscalp\strategy\news_straddle_engine.py")))
Write-Output ("HAS_keyboards=" + (Test-Path (Join-Path $root "src\chronoscalp\telegram\keyboards.py")))
Write-Output ("ENV_EXISTS=" + (Test-Path (Join-Path $root ".env")))
Write-Output "DONE"
