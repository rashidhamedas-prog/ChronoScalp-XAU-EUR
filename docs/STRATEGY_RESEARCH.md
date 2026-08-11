# Strategy Research Notes

Working notes for ChronoScalp strategy redesign and validation. Live enablement
still requires broker-native walk-forward / out-of-sample / cost-stress evidence
and intact 1% per-trade / 3% daily risk ceilings.

## Mistake Memory

Deterministic “learn from mistakes” veto (not ML). Losing setups are fingerprinted
as `{symbol}|{strategy}|{session}|{direction}|{setup_reason_bucket}` and stored
under `state_dir/lessons_{mode}.json`. The setup bucket prefers the **second**
comma-token of the journal reason (e.g. `delta,bullish_bos,...` → `bullish_bos`)
so strategy tags alone do not over-block. When the same fingerprint repeats within
`cooldown_minutes` at least `max_repeats` times, new entries with that fingerprint
are skipped (`mistake_memory` skip reason).

Configured under `risk.mistake_memory` in `config/settings.yaml`. This gate does
not loosen risk ceilings and does not authorize live trading by itself.

## Next: broker-native data

`data/history/` is gitignored and currently absent in this worktree — no synthetic
history should be invented. Pull broker-native OHLCV from the logged-in MT5
terminal (Windows only) via `scripts/fetch_history.py`. `--symbol` is a free
string, so LiteFinance-style names (`XAUUSD_o`, `EURUSD_o`) are supported when
they exist in Market Watch. Output layout: `data/history/<symbol>/<TF>.csv`.

Operator commands (repo root, venv active, MT5 running and logged in; `.env`
credentials already configured). M1 only, two years — does **not** start live:

```powershell
$env:PYTHONPATH="src"
python scripts/fetch_history.py --symbol XAUUSD_o --timeframes M1 --years 2
python scripts/fetch_history.py --symbol EURUSD_o --timeframes M1 --years 2
```

Optional fuller set (script default TFs if `--timeframes` omitted): `M1 M3 M5 M10`.

After CSVs exist, walk-forward / OOS / 1.5× cost-stress backtests can proceed.
Fetching history alone does not enable live trading.
