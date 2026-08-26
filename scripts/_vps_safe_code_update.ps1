# Update the VPS working copy to origin/main WITHOUT touching live state.
#
# Deliberately does NOT do what scripts/_vps_full_deploy.ps1 does:
#   * no process restart - the running bot keeps its already-imported modules,
#     so new code only takes effect on a later, explicit restart;
#   * no `Remove-Item data\state\STOP_TRADING` - the kill switch must survive,
#     because the new geometry is not validated yet.
#
# config/runtime_overrides.yaml is gitignored and untracked, so `reset --hard`
# leaves it alone; it is backed up anyway and hash-verified afterwards.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $git) {
    foreach ($c in @("C:\Program Files\Git\cmd\git.exe", "C:\Program Files (x86)\Git\cmd\git.exe")) {
        if (Test-Path $c) { $git = $c; break }
    }
}
if (-not $git) { throw "git not found on VPS" }

$overlay = Join-Path $root "config\runtime_overrides.yaml"
$marker = Join-Path $root "data\state\STOP_TRADING"

$overlayHashBefore = $null
if (Test-Path $overlay) {
    $overlayHashBefore = (Get-FileHash $overlay -Algorithm SHA256).Hash
    $stamp = Get-Date -Format "yyyyMMddTHHmmssZ"
    $backup = Join-Path $root ("config\runtime_overrides.safeupdate.bak-" + $stamp + ".yaml")
    Copy-Item $overlay $backup -Force
    Write-Output ("OVERLAY_BACKUP=" + $backup)
}
$markerBefore = Test-Path $marker

Write-Output ("HEAD_BEFORE=" + (& $git rev-parse --short HEAD))
& $git fetch origin
& $git checkout main
& $git reset --hard origin/main
Write-Output ("HEAD_AFTER=" + (& $git rev-parse --short HEAD))
Write-Output ("LOG=" + (& $git log -1 --oneline))

# Restore the overlay only if the reset somehow disturbed it.
$overlayHashAfter = $null
if (Test-Path $overlay) { $overlayHashAfter = (Get-FileHash $overlay -Algorithm SHA256).Hash }
if ($overlayHashBefore -and $overlayHashAfter -ne $overlayHashBefore) {
    Copy-Item $backup $overlay -Force
    $overlayHashAfter = (Get-FileHash $overlay -Algorithm SHA256).Hash
    Write-Output "OVERLAY_RESTORED_FROM_BACKUP=True"
}
Write-Output ("OVERLAY_HASH_BEFORE=" + $overlayHashBefore)
Write-Output ("OVERLAY_HASH_AFTER=" + $overlayHashAfter)
Write-Output ("OVERLAY_UNCHANGED=" + ($overlayHashAfter -eq $overlayHashBefore))

if ($markerBefore -and -not (Test-Path $marker)) {
    New-Item -ItemType File -Path $marker -Force | Out-Null
    Write-Output "KILL_SWITCH_RECREATED=True"
}
Write-Output ("KILL_SWITCH_BEFORE=" + $markerBefore)
Write-Output ("KILL_SWITCH_AFTER=" + (Test-Path $marker))

Write-Output "`n===== EFFECTIVE DELTA CONFIG AFTER MERGE ====="
$env:PYTHONPATH = "src"
& (Join-Path $root ".venv\Scripts\python.exe") -c @"
import json
from chronoscalp.config import get_settings
s = get_settings()
delta = (s.raw.get('strategy') or {}).get('delta') or {}
print(json.dumps(delta, indent=2, sort_keys=True))
risk = s.raw.get('risk') or {}
print('trailing_start_r_multiple =', risk.get('trailing_start_r_multiple'))
print('spread_ma_guard =', json.dumps(risk.get('spread_ma_guard')))
print('symbols =', s.symbols)
"@

Write-Output "`n===== LIVE PROCESSES STILL RUNNING (must be unchanged) ====="
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, ParentProcessId, @{n = "Cmd"; e = { $_.CommandLine } } |
    Sort-Object ProcessId | Format-Table -AutoSize -Wrap | Out-String | Write-Output

Write-Output "SAFE_UPDATE_DONE"
