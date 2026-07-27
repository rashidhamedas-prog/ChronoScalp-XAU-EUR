# Apply volatility-guard fix on the Windows VPS and restart the live bot.
# Run in PowerShell as Administrator on 45.90.98.99 (RDP).
$ErrorActionPreference = "Stop"

$candidates = @(
    "C:\ChronoScalp\ChronoScalp-XAU-EUR",
    "D:\soft\Claud\porje\ChronoScalp s3",
    "D:\soft\Claud\porje\ChronoScalp-XAU-EUR"
)
$root = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $root) {
    throw "ChronoScalp repo not found. Edit `$candidates in this script."
}

Set-Location $root
Write-Host "Repo: $root" -ForegroundColor Cyan

git fetch origin
git checkout main
git pull origin main

# Prefer merged main; fall back to the fix branch if not merged yet.
$hasFix = git log --oneline -20 --grep="volatility guard" 
if (-not $hasFix) {
    Write-Host "Fix not on main yet — checking out PR branch" -ForegroundColor Yellow
    git fetch origin cursor/fix-volatility-guard-s15-0876
    git checkout cursor/fix-volatility-guard-s15-0876
    git pull origin cursor/fix-volatility-guard-s15-0876
}

Write-Host "HEAD=$(git rev-parse --short HEAD) $(git log -1 --oneline)" -ForegroundColor Green

$token = "Hamed95240"
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*CHRONOSCALP_API_TOKEN\s*=\s*(.+)\s*$') {
            $token = $Matches[1].Trim()
        }
    }
}
$headers = @{ Authorization = "Bearer $token" }

function Invoke-BotApi([string]$Method, [string]$Path, $Body = $null) {
    $uri = "http://127.0.0.1:8510$Path"
    if ($null -eq $Body) {
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -TimeoutSec 30
    }
    return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -ContentType "application/json" -Body ($Body | ConvertTo-Json) -TimeoutSec 30
}

Write-Host "Stopping bot..." -ForegroundColor Cyan
try { Invoke-BotApi "POST" "/bot/stop" | Out-Host } catch { Write-Host $_ -ForegroundColor Yellow }
Start-Sleep -Seconds 3

Write-Host "Starting live bot..." -ForegroundColor Cyan
Invoke-BotApi "POST" "/bot/start" @{ mode = "live" } | Out-Host
Start-Sleep -Seconds 5

$status = Invoke-BotApi "GET" "/status"
Write-Host ("running={0} pid={1} symbols={2}" -f $status.running, $status.pid, ($status.symbols -join ",")) -ForegroundColor Green
Write-Host "Done. Watch skip heartbeats — should no longer be blanket volatility_guard on S15." -ForegroundColor Green
