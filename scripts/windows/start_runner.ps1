# Start the runner in paper mode. Live is not started from the logon task.
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$homeDir = Get-ChronoScalpHome
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir "logs") | Out-Null
$env:CHRONOSCALP_HOME = $homeDir
$env:CHRONOSCALP_CONFIG_DIR = Join-Path $homeDir "config"
$env:CHRONOSCALP_CONFIRM_LIVE = "no"

$stopped = Join-Path $homeDir "data\user\bot.stopped"
if (Test-Path -LiteralPath $stopped) {
    Remove-Item -LiteralPath $stopped -Force
}

$already = Get-Process -Name "ChronoScalpRunner" -ErrorAction SilentlyContinue
if ($already) {
    Write-Output "ChronoScalpRunner is already running."
    exit 0
}

$runner = Get-ChronoScalpRunnerExe
if ($runner) {
    $env:CHRONOSCALP_RUNNER = $runner
    Start-Process -FilePath $runner -ArgumentList @("--mode", "paper") -WorkingDirectory $homeDir -WindowStyle Minimized
    Write-Output "Started $runner --mode paper"
    exit 0
}

$repo = Get-ChronoScalpInstallRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}
$entry = Join-Path $repo "scripts\windows\runner_entry.py"
Start-Process -FilePath $python -ArgumentList @($entry, "--mode", "paper") -WorkingDirectory $homeDir -WindowStyle Minimized
Write-Output "Started source runner --mode paper"
