# Strategy Delta (XAUUSD; EURUSD redesign pending)

Delta is an explainable, multi-timeframe, cost-aware strategy. It is a research
strategy, not a promise of profit or a claim that one rule set is universally
"best". Its edge must be demonstrated separately for each broker, symbol, and
market regime using out-of-sample and forward demo results.

**Broker-native evidence (AUSCommercial-Demo, 2026-08):** XAUUSD limited 45d
cost-stress/WF was directionally positive but OOS samples are thin. EURUSD
failed cost-stress and limited WF OOS — `allowed_symbols` is **XAUUSD-only**
until a separate EUR redesign clears the gates in `docs/STRATEGY_RESEARCH.md`.

## Decision stack

1. **M15 + M5 regime:** both frames must agree on price/EMA50 location, EMA
   slope, and a non-extreme RSI regime. Delta rejects extended price (>2.5 ATR
   from EMA) instead of chasing it.
2. **M1 location/event:** price must sweep and reclaim the recent 12-bar range,
   or break it and successfully retest it.
3. **M1 confirmation:** a directional close with body at least 45% of candle
   range and relative volume >=1.15.
4. **Execution economics:** the stop is beyond local structure plus 0.2 ATR,
   never tighter than 0.8 ATR or 2x current spread, and never wider than 2.5
   ATR. Target defaults to 1.8R (hard floor remains 1.5R).
5. **Existing bot gates still apply:** session, high-impact news, spread,
   stale-data, portfolio/daily loss, three-strikes, and 1% maximum risk.

## Why these constraints

- Bid/ask spread is a direct execution cost and liquidity changes through the
  day; CME's liquidity material explicitly treats spread and depth as core
  execution-quality measures: <https://www.cmegroup.com/education/courses/trading-and-analysis/liquidity-and-immediacy>.
- Gold trades nearly around the clock and has meaningful liquidity outside US
  hours, so Delta does not encode the false assumption that Asia is always
  illiquid. ChronoScalp's configured London/New York windows remain the initial
  conservative deployment choice: <https://www.cmegroup.com/education/articles-and-reports/trading-comex-gold-and-silver>.
- Macroeconomic releases can abruptly change volatility and liquidity. Delta
  therefore relies on the existing high-impact-news veto rather than attempting
  to predict release outcomes. Official calendars should be the operational
  source of truth: <https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm>
  and <https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html>.

## Configuration

`config/settings.yaml -> strategy.delta` contains only defensible execution and
signal-quality parameters. Do not optimize the 1% risk ceiling or 1.5R floor.
Tune XAUUSD and EURUSD separately; never select parameters on the same period
used to report performance.

### Stop scale (revised 2026-08-26)

Delta originally scaled its stop from the **trigger-bar** ATR. Measured live on
2026-08-26 (`data/_analysis/vps_atr_probe.txt`), that produced stops narrower
than one average M1 candle on both symbols:

| Symbol | M1 ATR(14) | median M1 bar range | old stop band (0.8–2.5x M1 ATR) |
|---|---|---|---|
| XAUUSD | $1.573 | $1.495 | $1.258 – $3.932 |
| EURUSD | 0.94 pip | 0.90 pip | 0.75 – 2.34 pip |

A stop that small is inside the ordinary noise band, so the outcome of a trade
was decided by the next tick rather than by the setup. Two keys change that:

- `stop_atr_source: htf` scales the stop (and `stop_buffer_atr`) from a higher
  timeframe. `stop_atr_htf_index` picks which one, counted along
  `timeframes.higher_trend` — currently `["M15", "M5"]`, so index `1` is M5.
  Falls back to the trigger ATR if that frame has no usable ATR.
- `max_cost_fraction_of_risk` caps round-trip spread as a share of the money at
  risk. A setup whose cost floor will not fit under `max_stop_atr` is rejected
  with reason `cost_exceeds_stop_cap` rather than taken at a bad cost ratio.

`symbol_overrides.<ROOT>` overrides any Delta key per symbol, matched on the
root so broker suffixes (`XAUUSD_o`) resolve correctly. Widening a stop lowers
lot size through `calculate_position_size`; it never increases risk.

## Telegram control

Open `تنظیمات → استراتژی‌ها`, toggle `دلتا`, then tap
`ذخیره استراتژی‌ها`. Delta is currently gold-only (`allowed_symbols: [XAUUSD]`).
The choice is persisted in
`config/runtime_overrides.yaml` and appears in `/status` and the settings
summary. Restart a running trading process after changing strategy selection;
Telegram never bypasses the live-confirmation or risk gates.

## Required validation before live use

1. Import at least two years of broker-native M1 data including spread.
2. Use walk-forward splits (train/tune, validation, untouched test).
3. Report net profit factor, expectancy in R, max drawdown, trade count,
   exposure, and results by symbol/session/setup—not win rate alone.
4. Run Monte Carlo trade-order and cost stress tests (spread/slippage >=1.5x).
5. Forward-test on demo for at least 100 trades per symbol and four weeks.
6. Keep `CHRONOSCALP_CONFIRM_LIVE` disabled until all gates pass.
7. The backtest must model the gates that actually fire live. **Closed
   2026-08-29** for the stop-management gap and four of the guards:
   `backtest/engine.py` now walks each bar as monotonic legs
   (`intrabar_stop_management`) and applies `spread_ma_guard`,
   `volatility_guard`, `three_strikes`, and a bar-time `daily_loss_limit`
   (`model_live_gates`). `LIVE_ONLY_GATES` still excludes `circuit_breaker`,
   `correlation_guard`, `kill_switch`, `mistake_memory`,
   `mt5_netting_fail_closed`, `portfolio_heat_live_shared`, and `stale_stops`,
   which need live account or cross-symbol state. Check a report's
   `stop_management` field before comparing it with anything older.

Prior EURUSD results (`data/_analysis/validate_EURUSD_last45d.json`,
`wf_limited_EURUSD.json`) were produced with trigger-ATR stops and the
pre-fix unconditional trailing stop. They do not transfer to the current
geometry in either direction — re-measure rather than cite them.

### Measured 2026-08-29 (window 2026-06-27 → 2026-08-11)

Both engines, same code and same broker-native data. Check a report's
`stop_management` field to know which produced it.

| Symbol | engine | n | win% | PF | E[R] | maxDD | return |
|---|---|---|---|---|---|---|---|
| XAUUSD | `bar_close` | 50 | 50.0 | 1.942 | +0.358 | 7.94% | +9.44% |
| XAUUSD | `intrabar_ohlc_path` | 48 | **62.5** | 1.754 | +0.284 | 6.14% | +7.00% |
| EURUSD | `bar_close` | 4 | 0.0 | 0.00 | −1.00 | 4.05% | −2.03% |
| EURUSD | `intrabar_ohlc_path` | 4 | 0.0 | 0.00 | −1.00 | 4.05% | −2.03% |

At 1.5× costs the gold parity run holds at PF 1.751 / E[R] +0.283, so the edge
is not a cost artefact.

The gold win rate *rising* to 62.5% while expectancy *falls* to +0.284R is the
live signature reproduced: with intrabar stop management the trail closes more
trades early for small gains instead of letting them reach full TP. That is
what the live journal showed and what the bar-close engine could not express.
Positive expectancy surviving that engine is the first defensible evidence
Delta has had for XAUUSD.

EURUSD is identical under both engines because all four trades hit their
initial stop before ever reaching 1R, so the trailing logic never engaged. The
result is not sensitive to stop management at all — the entries simply did not
work.

**EURUSD Delta is not live-eligible.** Four trades in 46 days, every one a full
stop-out, expectancy exactly −1.00R — no trade reached breakeven or the trail.
That is not a small negative edge, it is an absence of any measurable edge on a
sample far too small to size a position from. Treat gate 5 (100 demo trades per
symbol) as unstarted for EURUSD, and investigate whether the entry filters are
adversely selecting the survivors before adjusting parameters.

## Data needed from the operator

- Broker name and exact symbol specifications/screenshots for XAUUSD and EURUSD.
- Broker-native M1 history with spread, ideally tick data.
- Commission, swap, minimum stop distance, lot step, and typical/worst spread.
- Demo journal exports after each 25–50 trades.
