# Stop the desktop runner and the control panel. Does not delete user data.
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")

Get-Process -Name "ChronoScalpRunner", "ChronoScalpPanel" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match "run_live\.py|runner_entry\.py|streamlit") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$homeDir = Get-ChronoScalpHome
$pidFile = Join-Path $homeDir "data\user\bot.pid"
if (Test-Path -LiteralPath $pidFile) {
    $pidText = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pidText -match "^\d+$") {
        Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
$userDir = Join-Path $homeDir "data\user"
New-Item -ItemType Directory -Force -Path $userDir | Out-Null
Set-Content -LiteralPath (Join-Path $userDir "bot.stopped") -Value "stopped_by_shortcut" -Encoding ascii
Write-Output "ChronoScalp runner and panel were asked to stop. User data was kept."
