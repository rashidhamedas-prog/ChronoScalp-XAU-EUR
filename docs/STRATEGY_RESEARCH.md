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

## Broker-native data (VPS evidence)

Verified on VPS MT5 broker **AUSCommercial-Demo**:

| Fact | Evidence |
|------|----------|
| Native symbols | `XAUUSD` / `EURUSD` — **not** LiteFinance `XAUUSD_o` / `EURUSD_o` |
| Fetch fix | Chunked `fetch_ohlcv_range` required; tz-aware + large range → `Invalid params` |
| History depth | ~100k bars M1/M5 for XAUUSD and EURUSD (broker depth cap); ~47–50k M15 bars |
| Full WF grid | Too slow for interactive run on 100k M1; earlier failure also from tz bug in `run_backtest` date filter |
| Live / risk | Live remains disabled; 1% per-trade / 3% daily intact |

Cost-stress (1.5×) numbers: **UNKNOWN** — pending shell agent on VPS.

`data/history/` is gitignored. Pull from the logged-in MT5 terminal (Windows only)
via `scripts/fetch_history.py`. Output: `data/history/<symbol>/<TF>.csv`.

Operator commands on **this** VPS broker (repo root, venv active, MT5 logged in):

```powershell
$env:PYTHONPATH="src"
python scripts/fetch_history.py --symbol XAUUSD --timeframes M1 M5 M15 --years 2
python scripts/fetch_history.py --symbol EURUSD --timeframes M1 M5 M15 --years 2
```

LiteFinance-style `_o` names apply only when that broker’s Market Watch exposes them.

## Exact next action

1. Finish **1.5× cost-stress** on VPS with native `XAUUSD` / `EURUSD` (record metrics when shell agent returns; leave UNKNOWN until then).
2. After TZ date-filter fix lands: run **limited** walk-forward (fewer folds / shorter window) — not a full 100k-M1 grid interactively.
3. Do not enable live until walk-forward + OOS + cost-stress evidence exists; keep 1%/3% risk gates.
