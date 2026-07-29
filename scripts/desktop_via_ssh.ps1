# ChronoScalp Desktop via SSH tunnel (use when ports 8510/8501 are blocked).
# Opens local 8510 -> VPS 127.0.0.1:8510 over SSH, then starts the desktop client.
#
# Credentials come from env / .env — never hardcode tokens in this file.
# Optional overrides:
#   $env:CHRONOSCALP_SSH_HOST, CHRONOSCALP_SSH_USER, CHRONOSCALP_SSH_KEY
#   $env:CHRONOSCALP_API_TOKEN, CHRONOSCALP_REPO

$ErrorActionPreference = "Stop"

$HostName = if ($env:CHRONOSCALP_SSH_HOST) { $env:CHRONOSCALP_SSH_HOST } else { "45.90.98.99" }
$User = if ($env:CHRONOSCALP_SSH_USER) { $env:CHRONOSCALP_SSH_USER } else { "Administrator" }
$Key = if ($env:CHRONOSCALP_SSH_KEY) {
    $env:CHRONOSCALP_SSH_KEY
} else {
    Join-Path $env:USERPROFILE ".ssh\chronoscalp_vps"
}
$LocalPort = 8510

$Repo = if ($env:CHRONOSCALP_REPO) {
    $env:CHRONOSCALP_REPO
} else {
    Split-Path -Parent $PSScriptRoot
}

$token = $env:CHRONOSCALP_API_TOKEN
$envCandidates = @(
    (Join-Path $Repo ".env"),
    (Join-Path $PWD ".env")
)
foreach ($envFile in $envCandidates) {
    if (-not $token -and (Test-Path $envFile)) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*CHRONOSCALP_API_TOKEN\s*=\s*(.+)\s*$') {
                $token = $Matches[1].Trim()
            }
        }
    }
}
if (-not $token) {
    throw "CHRONOSCALP_API_TOKEN missing. Set it in .env or the environment before launching."
}

Write-Host "Checking existing tunnel on localhost:$LocalPort ..." -ForegroundColor Cyan
$busy = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if (-not $busy) {
    Write-Host "Starting SSH tunnel..." -ForegroundColor Cyan
    $sshArgs = @(
        "-i", $Key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ExitOnForwardFailure=yes",
        "-N", "-L", "${LocalPort}:127.0.0.1:8510",
        "${User}@${HostName}"
    )
    Start-Process -FilePath "ssh" -ArgumentList $sshArgs -WindowStyle Minimized
    Start-Sleep -Seconds 2
} else {
    Write-Host "Tunnel already listening." -ForegroundColor Green
}

$cfgPath = Join-Path $env:USERPROFILE ".chronoscalp_desktop.json"
@{
    base_url = "http://127.0.0.1:$LocalPort"
    ssh_host = $HostName
    ssh_user = $User
    ssh_key  = $Key
    token    = $token
    proxy    = ""
} | ConvertTo-Json | Set-Content -Path $cfgPath -Encoding utf8

Write-Host "Config -> http://127.0.0.1:$LocalPort (token from env/.env)" -ForegroundColor Green
Write-Host "Starting desktop client..." -ForegroundColor Cyan
Set-Location $Repo
python "$Repo\scripts\desktop_client.py"
