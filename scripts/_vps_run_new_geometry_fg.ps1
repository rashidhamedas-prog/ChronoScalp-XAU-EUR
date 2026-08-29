# Foreground new-geometry validation with the error visible.
# The detached wrapper died silently at the python invocation, so run it here
# without stream-redirection tricks and print everything.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"

$py = Join-Path $root ".venv\Scripts\python.exe"
Write-Output ("PY_EXISTS=" + (Test-Path $py))
Write-Output ("SCRIPT_EXISTS=" + (Test-Path (Join-Path $root "scripts\run_cost_stress_validate.py")))
Write-Output "===== RUN ====="
& $py -u scripts/run_cost_stress_validate.py --symbols XAUUSD EURUSD --from 2026-06-27 --to 2026-08-11 2>&1 |
    ForEach-Object { Write-Output $_ }
Write-Output ("EXIT_CODE=" + $LASTEXITCODE)
Write-Output "FG_DONE"
