# Health check for the detached new-geometry validation run.
# Reports whether the backtest process is alive and consuming CPU, so a silent
# log does not get mistaken for a hang.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$reports = Join-Path $root "data\reports"

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
$backtest = $procs | Where-Object { $_.CommandLine -like "*run_cost_stress_validate*" }
Write-Output ("BACKTEST_PROC_COUNT=" + @($backtest).Count)
foreach ($p in $backtest) {
    $cpuSec = [math]::Round(($p.UserModeTime + $p.KernelModeTime) / 10000000.0, 1)
    $rssMb = [math]::Round($p.WorkingSetSize / 1MB, 1)
    $ageMin = [math]::Round(((Get-Date) - $p.CreationDate).TotalMinutes, 1)
    Write-Output ("pid=" + $p.ProcessId + " age_min=" + $ageMin +
        " cpu_sec=" + $cpuSec + " rss_mb=" + $rssMb)
}

Write-Output "`n===== REPORT FILES ====="
Get-ChildItem $reports -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "newgeom*" -or $_.Name -like "validate_*" -or $_.Name -like "cost_stress*" } |
    Select-Object Name, Length, LastWriteTime |
    Sort-Object LastWriteTime -Descending |
    Format-Table -AutoSize | Out-String | Write-Output

Write-Output "===== VALIDATE LOG ====="
$log = Join-Path $reports "newgeom_validate.log"
if (Test-Path $log) { Get-Content $log -Tail 40 }

Write-Output "`n===== STDERR ====="
$err = Join-Path $reports "newgeom_stderr.txt"
if (Test-Path $err) { Get-Content $err -Tail 25 }

Write-Output ("`nKILL_SWITCH=" + (Test-Path (Join-Path $root "data\state\STOP_TRADING")))
Write-Output "POLL_DONE"
