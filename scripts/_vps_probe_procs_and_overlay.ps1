# Read-only. Two questions before any code update:
#   1. Are there genuinely two live bot processes (double order risk), or is the
#      duplicate listing a venv-launcher artefact? Parent PIDs answer it.
#   2. Is config/runtime_overrides.yaml tracked by git? If it is, `reset --hard`
#      would clobber the live overlay; if ignored/skip-worktree it is safe.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $git) {
    foreach ($c in @("C:\Program Files\Git\cmd\git.exe", "C:\Program Files (x86)\Git\cmd\git.exe")) {
        if (Test-Path $c) { $git = $c; break }
    }
}

Write-Output "===== PYTHON PROCESS TREE ====="
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, ParentProcessId, CreationDate,
    @{n = "Exe"; e = { $_.ExecutablePath } },
    @{n = "Cmd"; e = { $_.CommandLine } } |
    Sort-Object ProcessId |
    Format-List | Out-String | Write-Output

Write-Output "===== DISTINCT run_live INSTANCES ====="
$live = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*run_live.py*" }
Write-Output ("run_live_process_count=" + @($live).Count)
foreach ($p in $live) {
    $parent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $p.ParentProcessId) -ErrorAction SilentlyContinue
    $parentName = "<gone>"
    if ($parent) { $parentName = $parent.Name }
    Write-Output ("pid=" + $p.ProcessId + " ppid=" + $p.ParentProcessId +
        " parent=" + $parentName + " exe=" + $p.ExecutablePath)
}

Write-Output "`n===== OVERLAY GIT TRACKING ====="
$rel = "config/runtime_overrides.yaml"
Write-Output ("ls_files=" + (& $git ls-files -- $rel))
Write-Output ("check_ignore=" + (& $git check-ignore -v -- $rel))
Write-Output ("skip_worktree_or_assume_unchanged=" + (& $git ls-files -v -- $rel))
& $git diff --quiet HEAD -- $rel
Write-Output ("diff_vs_head_exit=" + $LASTEXITCODE + " (0=same as HEAD, 1=differs)")

Write-Output "`n===== HISTORY DATA DETAIL ====="
Get-ChildItem (Join-Path $root "data\history") -Recurse -File -ErrorAction SilentlyContinue |
    Select-Object @{n = "Rel"; e = { $_.FullName.Replace($root, "") } }, Length, LastWriteTime |
    Format-Table -AutoSize | Out-String | Write-Output

Write-Output "PROBE_DONE"
