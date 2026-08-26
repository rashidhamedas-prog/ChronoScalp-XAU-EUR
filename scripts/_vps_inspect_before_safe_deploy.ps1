# Read-only pre-deploy inspection. Changes nothing.
#
# Run before scripts/_vps_safe_code_update.ps1 so the safe update knows exactly
# what local state it must preserve: the live overlay diverges from the repo
# copy, and the STOP_TRADING kill-switch marker must survive.
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

Write-Output "===== HEAD ====="
Write-Output ("HEAD=" + (& $git rev-parse --short HEAD))
Write-Output ("BRANCH=" + (& $git rev-parse --abbrev-ref HEAD))
Write-Output ("LOG=" + (& $git log -1 --oneline))

Write-Output "`n===== LOCAL MODIFICATIONS (tracked) ====="
$status = & $git status --porcelain
if ($status) { $status | ForEach-Object { Write-Output $_ } } else { Write-Output "(clean)" }

Write-Output "`n===== KILL SWITCH ====="
$marker = Join-Path $root "data\state\STOP_TRADING"
Write-Output ("MARKER_PATH=" + $marker)
Write-Output ("MARKER_EXISTS=" + (Test-Path $marker))
Write-Output ("ENV_STOP_TRADING=" + $env:CHRONOSCALP_STOP_TRADING)

Write-Output "`n===== LIVE OVERLAY (config/runtime_overrides.yaml) ====="
$overlay = Join-Path $root "config\runtime_overrides.yaml"
if (Test-Path $overlay) {
    Write-Output ("SHA256=" + (Get-FileHash $overlay -Algorithm SHA256).Hash)
    Get-Content $overlay
}
else { Write-Output "(overlay missing)" }

Write-Output "`n===== RUNNING PROCESSES ====="
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, @{n = "Cmd"; e = { $_.CommandLine } } |
    Format-Table -AutoSize -Wrap | Out-String | Write-Output

Write-Output "`n===== HISTORY DATA AVAILABLE FOR BACKTEST ====="
foreach ($dir in @("data\historical", "data\history", "data\ohlcv")) {
    $p = Join-Path $root $dir
    if (Test-Path $p) {
        Write-Output ("DIR " + $dir)
        Get-ChildItem $p -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 20 Name, Length, LastWriteTime |
            Format-Table -AutoSize | Out-String | Write-Output
    }
}

Write-Output "INSPECT_DONE"
