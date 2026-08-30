# Read-only: show the risk block of the live runtime overlay and the merged
# effective risk settings, so the guards reported at startup can be traced to a
# config source. Never prints secrets.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

Write-Output "===== OVERLAY risk BLOCK ====="
$overlay = Join-Path $root "config\runtime_overrides.yaml"
if (Test-Path $overlay) {
    $inRisk = $false
    foreach ($line in Get-Content $overlay) {
        if ($line -match '^\S') { $inRisk = ($line -match '^risk:') }
        if ($inRisk) { Write-Output $line }
    }
} else {
    Write-Output "NO_OVERLAY"
}

Write-Output "===== EFFECTIVE RISK (merged) ====="
$env:PYTHONPATH = Join-Path $root "src"
& (Join-Path $root ".venv\Scripts\python.exe") -c @"
import json
from chronoscalp.config import Settings
risk = Settings().risk
keys = [
    'max_risk_per_trade_pct', 'active_risk_per_trade_pct', 'min_reward_risk_ratio',
    'max_daily_loss_pct', 'daily_loss_limit_enabled', 'max_portfolio_heat_pct',
    'trailing_start_r_multiple', 'trailing_stop_atr_multiple',
]
print(json.dumps({k: risk.get(k) for k in keys}, indent=2))
print('daily_risk_block=' + json.dumps(risk.get('daily_risk') or {}, indent=2))
"@
Write-Output "SHOW_RISK_DONE"
