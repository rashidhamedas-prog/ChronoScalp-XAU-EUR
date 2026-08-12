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

| Run | Window | Symbol | Trades | Expectancy R | PF | Max DD % | Notes |
|-----|--------|--------|--------|--------------|----|----------|-------|
| VPS prior (`validate_XAUUSD.json`, 2026-08-11) | full available history (pre–last-days tooling) | XAUUSD | 85 | 0.219 → 0.218 @1.5× | 1.654 → 1.652 | 4.44 → 4.45 | Copied to `data/_analysis/validate_XAUUSD_vps_prior.json` |
| VPS prior summary | — | EURUSD | — | — | — | — | `cost_stress_1p5x_summary.json` still showed `missing_history` (stale/_o-era) — **do not trust** |
| VPS limited `--last-days 45` | 2026-06-27 → 2026-08-11 (UTC) | XAUUSD + EURUSD | **IN PROGRESS** | — | — | — | Quiet `LOG_LEVEL=WARNING`; ~30 min/backtest observed |

`scripts/run_cost_stress_validate.py` now supports `--from` / `--to` / `--last-days` and slices before enrich (warmup 300 bars). VPS helpers: `_vps_cost_stress_only.ps1`, `_vps_detach_cost_stress.ps1`, `_vps_status_research.ps1`, `_vps_limited_walkforward.ps1`.

`data/history/` is gitignored. Pull from the logged-in MT5 terminal (Windows only)
via `scripts/fetch_history.py`. Output: `data/history/<symbol>/<TF>.csv`.

Operator commands on **this** VPS broker (repo root, venv active, MT5 logged in):

```powershell
$env:PYTHONPATH="src"
$env:LOG_LEVEL="WARNING"
python scripts/fetch_history.py --symbol XAUUSD --timeframes M1 M5 M15 --years 2
python scripts/fetch_history.py --symbol EURUSD --timeframes M1 M5 M15 --years 2
python -u scripts/run_cost_stress_validate.py --symbols XAUUSD EURUSD --last-days 45
```

LiteFinance-style `_o` names apply only when that broker’s Market Watch exposes them.

## Exact next action

1. Wait for in-progress VPS limited cost-stress (`--last-days 45`) to write `validate_XAUUSD.json`, `validate_EURUSD.json`, `cost_stress_1p5x_summary.json`; pull and record metrics (replace IN PROGRESS).
2. Run **limited** walk-forward via `scripts/_vps_limited_walkforward.ps1` (folds=2, `expectancy_r`, last ~45 days).
3. Do not enable live until walk-forward + OOS + cost-stress evidence exists; keep 1%/3% risk gates. Prior XAU full-history PF≈1.65 is promising but not sufficient alone.
