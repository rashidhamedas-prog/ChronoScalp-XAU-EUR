# Deploy ChronoScalp to the Windows VPS from this machine via SSH.
# Requires: ssh key at %USERPROFILE%\.ssh\chronoscalp_vps (or CHRONOSCALP_SSH_KEY).
#
# Optional env overrides:
#   CHRONOSCALP_SSH_HOST, CHRONOSCALP_SSH_USER, CHRONOSCALP_SSH_KEY

$ErrorActionPreference = "Stop"

$HostName = if ($env:CHRONOSCALP_SSH_HOST) { $env:CHRONOSCALP_SSH_HOST } else { "45.90.98.99" }
$User = if ($env:CHRONOSCALP_SSH_USER) { $env:CHRONOSCALP_SSH_USER } else { "Administrator" }
$Key = if ($env:CHRONOSCALP_SSH_KEY) {
    $env:CHRONOSCALP_SSH_KEY
} else {
    Join-Path $env:USERPROFILE ".ssh\chronoscalp_vps"
}
$Repo = Split-Path -Parent $PSScriptRoot
$LocalScript = Join-Path $PSScriptRoot "_vps_full_deploy.ps1"
$RemoteScript = "C:\ChronoScalp\_vps_full_deploy.ps1"

if (-not (Test-Path $Key)) { throw "SSH key not found: $Key" }
if (-not (Test-Path $LocalScript)) { throw "Deploy script missing: $LocalScript" }

Write-Host "Uploading deploy script to ${User}@${HostName} ..." -ForegroundColor Cyan
& scp -o BatchMode=yes -i $Key $LocalScript "${User}@${HostName}:C:/ChronoScalp/_vps_full_deploy.ps1"
if ($LASTEXITCODE -ne 0) { throw "scp failed ($LASTEXITCODE)" }

Write-Host "Running full deploy on VPS ..." -ForegroundColor Cyan
& ssh -o BatchMode=yes -i $Key "${User}@${HostName}" `
    powershell -NoProfile -ExecutionPolicy Bypass -File $RemoteScript
if ($LASTEXITCODE -ne 0) { throw "remote deploy failed ($LASTEXITCODE)" }

Write-Host "Deploy finished." -ForegroundColor Green
