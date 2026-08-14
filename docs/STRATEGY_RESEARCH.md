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

### Cost-stress evidence

Window for limited run: **2026-06-27 → 2026-08-11 UTC** (`--last-days 45`). Local copies under `data/_analysis/*_last45d.json`.

| Run | Symbol | Trades | Expectancy R (base → 1.5×) | PF | Max DD % | Verdict |
|-----|--------|--------|----------------------------|----|----------|---------|
| VPS limited 45d (2026-08-12) | XAUUSD | 46 | 0.354 → 0.353 | 2.114 → 2.112 | 2.02 → 2.03 | Survives cost stress on this window |
| VPS limited 45d (2026-08-12) | EURUSD | 17 | −0.150 → −0.206 | 0.591 → 0.477 | 4.75 → 5.81 | Fails — negative expectancy; redesign before any enable |
| VPS prior full hist (2026-08-11) | XAUUSD | 85 | 0.219 → 0.218 | 1.654 → 1.652 | 4.44 → 4.45 | Consistent direction with limited window |
| VPS prior summary | EURUSD | — | — | — | — | Stale `missing_history` — ignore |

### Limited walk-forward (tiny-grid, folds=2, expectancy_r)

Window ≈ last 45 calendar days; `--tiny-grid` = default EMA50/RSI14/MACD12-26 only. Copies: `data/_analysis/wf_limited_*.json`.

| Symbol | Fold | OOS trades | OOS E[R] | OOS PF | OOS return % | Notes |
|--------|------|------------|----------|--------|--------------|-------|
| XAUUSD | 1 | 5 | 1.007 | 8.002 | +5.03 | Small sample |
| XAUUSD | 2 | 4 | 0.512 | 2.268 | +1.97 | Small sample |
| XAUUSD | avg | — | — | — | +3.50 | Directionally positive OOS |
| EURUSD | 1 | 3 | −0.500 | 0.0 | −1.75 | Fail |
| EURUSD | 2 | 2 | −0.762 | 0.0 | −1.78 | Fail |
| EURUSD | avg | — | — | — | −1.76 | Confirms cost-stress fail |

`scripts/run_cost_stress_validate.py` supports `--from` / `--to` / `--last-days` and slices before enrich (warmup 300 bars). VPS helpers: `_vps_cost_stress_only.ps1`, `_vps_detach_cost_stress.ps1`, `_vps_status_research.ps1`, `_vps_limited_walkforward.ps1` (`--tiny-grid`).

`data/history/` is gitignored. Pull from the logged-in MT5 terminal (Windows only)
via `scripts/fetch_history.py`. Output: `data/history/<symbol>/<TF>.csv`.

Operator commands on **this** VPS broker (repo root, venv active, MT5 logged in):

```powershell
$env:PYTHONPATH="src"
$env:LOG_LEVEL="WARNING"
python scripts/fetch_history.py --symbol XAUUSD --timeframes M1 M5 M15 --years 2
python scripts/fetch_history.py --symbol EURUSD --timeframes M1 M5 M15 --years 2
python -u scripts/run_cost_stress_validate.py --symbols XAUUSD EURUSD --last-days 45
powershell -File scripts/_vps_limited_walkforward.ps1
```

LiteFinance-style `_o` names apply only when that broker’s Market Watch exposes them.

## Exact next action

1. **EURUSD redesign** (separate system) — current multi-TF fails cost-stress and limited WF OOS.
2. Longer-horizon / more folds XAUUSD WF once denser history or M5 trigger path is practical; OOS trade counts (4–5/fold) are too thin for live.
3. Do not enable live; keep 1%/3%. Independent reviewer/security still required before any live path.
