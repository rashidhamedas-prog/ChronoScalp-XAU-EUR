# Strategy `xau_vwap_pullback` (XAUUSD)

`xau_vwap_pullback` is an explainable M15-regime / M5-impulse / M1-rejection
pullback candidate. Operator live-enabled it on 2026-08-23 (`enabled: true`,
`shadow_only: false`, `live_ready: true`, listed on `enabled_strategies`).
That is an operator decision, not a completed walk-forward proof — do not
describe results as guaranteed. 1% / 1.5R / 3% heat stay hard.

Implementation: `src/chronoscalp/strategy/xau_vwap_pullback.py`. Telegram label:
`پولبک VWAP (طلا)`. Selection is simultaneous OR with other engines — not
winner-takes-all.

## Decision stack

1. **M15 regime** (need ≥2/3): close vs session VWAP, EMA20 vs EMA50, EMA20
   3-bar slope. M5 must not be a hard opposite bias.
2. **M5 impulse:** 8-bar swing break, body ≥ 0.6 ATR(M5), RVOL ≥ 1.10. Expires
   after 6 M1 bars or an origin break.
3. **M1 pullback:** 30–65% retrace **or** touch of the broken level / session
   VWAP within 0.20 ATR(M1). Rejection body/range ≥ 0.45 and close in the 30%
   extreme. No close beyond impulse origin. M1 RVOL ≥ 1.10 is score-only.
4. **Entry:** BUY_STOP / SELL_STOP one tick beyond the rejection (not a market
   order). Cancel if unfilled after 2 M1 bars; no chase if price is > 0.25 ATR
   from the trigger.
5. **Geometry:** SL behind the pullback swing + 0.15 ATR(M1), clamped to
   `[max(0.70 ATR, 2×spread), 1.80 ATR]`. TP 2.0R. Gross floor remains 1.5R.
   Planned net R:R after spread+commission+slippage at **1.5× cost stress**
   must be ≥ 1.25. No trade if opposing liquidity sits before 1.5R.
6. **Score ≥ 5/8** (regime 3/3 +2, dual VWAP+level +2, RVOL +1, wick +1,
   tight spread +1, M5+M15 aligned +1). Hard gates are not scored.
7. **Existing bot gates still apply:** DST-aware London/NY sessions, news
   blackout, spread shield (cap and 1.2× rolling median), 1% risk, 3% live
   portfolio heat, netting fail-closed.

Closed bars only. HTF is as-of the last closed M1. Forming candles are not used.

## Why these constraints

Spread is an execution cost, not a tuning knob. Gold session VWAP is a location
anchor for pullbacks after an impulse, not a standalone signal. The 1% / 1.5R /
3% daily-loss ceilings are never part of the tunable set.

Forbidden: martingale, grid, averaging down, raising risk after a loss.

## Telegram control

Open `تنظیمات → استراتژی‌ها`. `پولبک VWAP (طلا)` now cycles **off → shadow → live**
because `live_ready: true`. Shadow still records candidates without orders.
Save, then **Stop then Start** the trading process. Overlay source is shown on `/status`.

## Required validation before live use

1. Import at least two years of broker-native M1/M5/M15 including spread.
2. Walk-forward (train/tune, validation, untouched test) — template only in
   `docs/validation/`; do not invent pass numbers.
3. Report net PF, expectancy in R, max DD, trade count, exposure, and splits
   by session/regime — not win rate alone.
4. Cost stress at 1.5× spread/commission/slippage. DSR/PBO remain UNKNOWN until
   computed on broker-native data.
5. Forward-test on demo (target: 8 weeks / 100+ trades) after OOS is honest.
6. Keep `CHRONOSCALP_CONFIRM_LIVE` unset until every gate above is evidence,
   not a hope.

Use the empty report template in `docs/validation/xau_vwap_pullback_report.template.md`.
Metrics in that file are **UNKNOWN** on purpose.
