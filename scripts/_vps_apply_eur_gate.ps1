# Apply research evidence gates on VPS runtime_overrides (gitignored).
$ErrorActionPreference = "Stop"
Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$env:PYTHONPATH = "src"
$py = ".\.venv\Scripts\python.exe"
& $py scripts\apply_eur_gate_overrides.py
if ($LASTEXITCODE -ne 0) { throw "apply_eur_gate_overrides failed" }
Write-Host "EUR_GATE_DONE"
# Restart trading bot so overrides are loaded.
& $py scripts\_vps_restart_live.py
Write-Host "BOT_RESTARTED"
