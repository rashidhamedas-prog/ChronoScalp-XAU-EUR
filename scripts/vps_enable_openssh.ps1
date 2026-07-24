# ChronoScalp — enable OpenSSH Server on Windows VPS (run as Administrator).
# Usage:
#   irm https://raw.githubusercontent.com/rashidhamedas-prog/ChronoScalp-XAU-EUR/main/scripts/vps_enable_openssh.ps1 | iex
# Or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\vps_enable_openssh.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Enable OpenSSH Server ===" -ForegroundColor Cyan

foreach ($svc in @("wuauserv", "BITS", "CryptSvc", "TrustedInstaller")) {
    try {
        Set-Service -Name $svc -StartupType Manual -ErrorAction SilentlyContinue
        Start-Service -Name $svc -ErrorAction SilentlyContinue
    } catch {
        Write-Host "WARN: could not start $svc — $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Get-Service wuauserv, BITS, CryptSvc -ErrorAction SilentlyContinue |
    Format-Table Name, Status, StartType -AutoSize

$cap = Get-WindowsCapability -Online -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "OpenSSH.Server*" } |
    Select-Object -First 1

if ($null -eq $cap -or $cap.State -ne "Installed") {
    Write-Host "Installing OpenSSH.Server capability..." -ForegroundColor Cyan
    try {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    } catch {
        Write-Host "Capability install failed: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "Falling back to Win32-OpenSSH zip..." -ForegroundColor Yellow

        $ver = "v9.5.0.0p1-Beta"
        $url = "https://github.com/PowerShell/Win32-OpenSSH/releases/download/$ver/OpenSSH-Win64.zip"
        $zip = Join-Path $env:TEMP "OpenSSH-Win64.zip"
        $dest = "C:\Program Files\OpenSSH"

        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath "C:\Program Files" -Force

        if (Test-Path "C:\Program Files\OpenSSH-Win64") {
            if (Test-Path $dest) {
                Remove-Item $dest -Recurse -Force
            }
            Rename-Item "C:\Program Files\OpenSSH-Win64" "OpenSSH"
        }

        & "$dest\install-sshd.ps1"
    }
} else {
    Write-Host "OpenSSH.Server already installed." -ForegroundColor Green
}

if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
    throw "sshd service still not found after install attempts."
}

Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

$pub = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGohXwb35zlVIJaZkZPBFeKp1w6uhTWFkjn0Utamr6OY chronoscalp-vps"
$dir = "C:\ProgramData\ssh"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$authKeys = Join-Path $dir "administrators_authorized_keys"
if (-not (Test-Path $authKeys) -or -not (Select-String -Path $authKeys -Pattern "chronoscalp-vps" -Quiet -ErrorAction SilentlyContinue)) {
    Add-Content -Path $authKeys -Value $pub -Encoding ascii
}
icacls $authKeys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null

if (-not (Get-NetFirewallRule -Name "sshd" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name "sshd" -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}

Get-Service sshd | Format-List Name, Status, StartType
Write-Host "DONE. From laptop test:" -ForegroundColor Green
Write-Host '  ssh -i C:\Users\DayaTech\.ssh\chronoscalp_vps Administrator@45.90.98.99'
