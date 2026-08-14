# Apply research evidence gates on VPS runtime_overrides (gitignored).
# Removes EURUSD / EURUSD_o from active symbols; sets Delta allowlist to XAUUSD.
$ErrorActionPreference = "Stop"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root
$env:PYTHONPATH = "src"
$py = ".\.venv\Scripts\python.exe"
$path = "config\runtime_overrides.yaml"

$script = @'
from __future__ import annotations
from pathlib import Path
import yaml

path = Path("config/runtime_overrides.yaml")
data = {}
if path.exists():
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

symbols = list(data.get("symbols") or [])
blocked = {"EURUSD", "EURUSD_o"}
new_symbols = [s for s in symbols if str(s) not in blocked]
if not new_symbols:
    # AUSCommercial-Demo native gold name.
    new_symbols = ["XAUUSD"]
data["symbols"] = new_symbols

strategy = dict(data.get("strategy") or {})
delta = dict(strategy.get("delta") or {})
delta["allowed_symbols"] = ["XAUUSD"]
strategy["delta"] = delta
data["strategy"] = strategy

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)
print("OVERRIDES_WRITTEN", path)
print("SYMBOLS", new_symbols)
print("DELTA_ALLOWED", delta["allowed_symbols"])
'@

& $py -c $script
Write-Host "EUR_GATE_DONE"
