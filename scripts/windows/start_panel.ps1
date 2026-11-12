# Open the control panel. Does not switch the bot to live.
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$homeDir = Get-ChronoScalpHome
$env:CHRONOSCALP_HOME = $homeDir
$env:CHRONOSCALP_CONFIG_DIR = Join-Path $homeDir "config"
$runner = Get-ChronoScalpRunnerExe
if ($runner) {
    $env:CHRONOSCALP_RUNNER = $runner
}

$panel = Get-ChronoScalpPanelExe
if ($panel) {
    Start-Process -FilePath $panel -WorkingDirectory $homeDir
    Write-Output "Started $panel"
    exit 0
}

$repo = Get-ChronoScalpInstallRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}
$entry = Join-Path $repo "scripts\windows\panel_entry.py"
if (Test-Path -LiteralPath $entry) {
    Start-Process -FilePath $python -ArgumentList @($entry) -WorkingDirectory $homeDir
    exit 0
}
$app = Join-Path $repo "scripts\app.py"
Start-Process -FilePath $python -ArgumentList @("-m", "streamlit", "run", $app, "--server.port", "8501") -WorkingDirectory $repo
