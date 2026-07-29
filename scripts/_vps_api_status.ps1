# Durable VPS helper: print Control API status + recent entry-skip heartbeats.
# Reads CHRONOSCALP_API_TOKEN from the environment or the repo .env (no hardcoded secrets).
# Run on the Windows VPS from the repo root, or: powershell -File scripts\_vps_api_status.ps1

$ErrorActionPreference = "Continue"
$Root = if (Test-Path "C:\ChronoScalp\ChronoScalp-XAU-EUR") {
    "C:\ChronoScalp\ChronoScalp-XAU-EUR"
} else {
    Split-Path -Parent $PSScriptRoot
}
Set-Location $Root

$token = $env:CHRONOSCALP_API_TOKEN
$envFile = Join-Path $Root ".env"
if (-not $token -and (Test-Path $envFile)) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*CHRONOSCALP_API_TOKEN\s*=\s*(.+)\s*$') {
            $token = $Matches[1].Trim()
        }
    }
}
if (-not $token) {
    Write-Output "API_TOKEN_MISSING — set CHRONOSCALP_API_TOKEN in .env"
    exit 1
}

$h = @{ Authorization = "Bearer $token" }

Write-Output "=== BOT/STATUS ==="
try {
    $st = Invoke-RestMethod -Uri "http://127.0.0.1:8510/status" -Headers $h -TimeoutSec 15
    Write-Output ("running=" + $st.running + " pid=" + $st.pid + " mode=" + $st.mode + " broker=" + $st.broker)
    Write-Output ("symbols=" + ($st.symbols -join ","))
    Write-Output ("server_time=" + $st.server_time)
} catch {
    Write-Output ("STATUS_FAIL=" + $_.Exception.Message)
}

Write-Output "=== LOG FILES ==="
Get-ChildItem .\logs -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 12 |
    ForEach-Object {
        "{0}`t{1}`t{2}" -f $_.LastWriteTime.ToString("s"), $_.Length, $_.Name
    }

Write-Output "=== HEARTBEATS (last 40) ==="
$paths = @(Get-ChildItem .\logs -Filter "*.log" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$hits = @()
foreach ($p in $paths) {
    $hits += @(Select-String -Path $p -Pattern "Entry skip heartbeat" -ErrorAction SilentlyContinue)
}
$hits | Select-Object -Last 40 | ForEach-Object {
    "{0}:{1}: {2}" -f $_.Filename, $_.LineNumber, $_.Line.Trim()
}

Write-Output "=== LIVE PROCESSES ==="
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "run_live\.py|run_api\.py|streamlit" } |
    ForEach-Object {
        "pid=$($_.ProcessId) parent=$($_.ParentProcessId) cmd=$($_.CommandLine.Substring(0, [Math]::Min(160, $_.CommandLine.Length)))"
    }

Write-Output "DONE"
