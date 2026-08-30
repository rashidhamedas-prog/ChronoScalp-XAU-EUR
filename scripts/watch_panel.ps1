# ChronoScalp Streamlit panel watchdog - single process tree.
#
# The panel was the only component without a watchdog, so any deploy that
# started it over SSH lost it again the moment that session closed, and nothing
# brought it back. Mirrors watch_telegram.ps1; register with
# scripts\install_panel_watchdog.ps1.
$ErrorActionPreference = "Continue"
$Root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Output "PANEL_NO_VENV"
    exit 1
}
$env:PYTHONPATH = Join-Path $Root "src"

function Get-PanelRoots {
    $all = @(Get-CimInstance Win32_Process | Where-Object {
            $_.CommandLine -and ($_.CommandLine -match 'streamlit')
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

$roots = @(Get-PanelRoots)
if ($roots.Count -gt 1) {
    foreach ($p in $roots | Select-Object -Skip 1) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Output ("PANEL_DEDUPE_KEPT={0}" -f $roots[0].ProcessId)
    exit 0
}
if ($roots.Count -eq 1) {
    Write-Output ("PANEL_ALREADY_UP pid={0}" -f $roots[0].ProcessId)
    exit 0
}

New-Item -ItemType Directory -Path "logs" -Force | Out-Null
Start-Process -FilePath $Py `
    -ArgumentList @("-m", "streamlit", "run", "scripts\app.py",
    "--server.port", "8501", "--server.address", "0.0.0.0",
    "--server.headless", "true") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Root "logs\panel_stdout.log") `
    -RedirectStandardError (Join-Path $Root "logs\panel_stderr.log")

Start-Sleep -Seconds 8
$after = @(Get-PanelRoots)
if ($after.Count -ge 1) {
    Write-Output ("PANEL_STARTED_OK pid={0}" -f $after[0].ProcessId)
} else {
    Write-Output "PANEL_START_FAIL"
}
