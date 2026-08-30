# Pull origin/main and run the full deploy with the kill switch preserved.
#
# Exists as its own file because nested quoting through `ssh powershell -Command`
# mangles both the git path and the -KeepHalt switch. Upload and run this
# instead of composing the command remotely.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$git = "C:\Program Files\Git\cmd\git.exe"
if (-not (Test-Path $git)) {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { $git = $cmd.Source } else { throw "git not found on VPS" }
}

$overlay = Join-Path $root "config\runtime_overrides.yaml"
$overlayHashBefore = ""
if (Test-Path $overlay) {
    $overlayHashBefore = (Get-FileHash $overlay -Algorithm SHA256).Hash
}
$killFile = Join-Path $root "data\state\STOP_TRADING"
Write-Output ("KILL_SWITCH_BEFORE=" + (Test-Path $killFile))
Write-Output ("HEAD_BEFORE=" + (& $git rev-parse --short HEAD))

& $git fetch origin
& $git reset --hard origin/main
Write-Output ("HEAD_AFTER=" + (& $git rev-parse --short HEAD))

if ($overlayHashBefore -ne "") {
    $overlayHashAfter = (Get-FileHash $overlay -Algorithm SHA256).Hash
    Write-Output ("OVERLAY_UNCHANGED=" + ($overlayHashBefore -eq $overlayHashAfter))
}

Write-Output "===== DEPLOY (KeepHalt) ====="
& (Join-Path $root "scripts\_vps_full_deploy.ps1") -KeepHalt
Write-Output "DEPLOY_KEEP_HALT_DONE"
