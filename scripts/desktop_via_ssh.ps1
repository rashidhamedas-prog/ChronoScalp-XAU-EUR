# ChronoScalp Desktop via SSH tunnel (use when ports 8510/8501 are blocked).
# Opens local 8510 -> VPS 127.0.0.1:8510 over SSH, then starts the desktop client.

$ErrorActionPreference = "Stop"
$Key = "C:\Users\DayaTech\.ssh\chronoscalp_vps"
$HostName = "45.90.98.99"
$User = "Administrator"
$LocalPort = 8510
$Repo = "d:\soft\Claud\porje\ChronoScalp s3"

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

# Point desktop client at local tunnel
$cfgPath = Join-Path $env:USERPROFILE ".chronoscalp_desktop.json"
@{
    base_url = "http://127.0.0.1:$LocalPort"
    token    = "Hamed95240"
    proxy    = ""
} | ConvertTo-Json | Set-Content -Path $cfgPath -Encoding utf8

Write-Host "Config -> http://127.0.0.1:$LocalPort  token=Hamed95240" -ForegroundColor Green
Write-Host "Starting desktop client..." -ForegroundColor Cyan
Set-Location $Repo
python "$Repo\scripts\desktop_client.py"
