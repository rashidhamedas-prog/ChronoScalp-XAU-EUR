# Project Status

- Last verified: 2026-08-31T21:35:00Z
- TASK-004: live books are Delta + M1 scalp for XAUUSD and EURUSD. SMC,
  liquidity, news straddle, and VWAP are off the catalog. Telegram/panel
  no longer mention those engines. Overlay `enabled_strategies` is still
  ignored while `derive_strategies_from_symbols` is true.
- Live 2026-08-31 (VPS 45.90.98.99, HEAD `fb4f016`, kill off): still zero
  opens. Dominant skips were `news_straddle_place_blocked` (Finnhub 403),
  `delta:regime_neutral`, SMC/liquidity `low_rvol`, scalp `weak_impulse`,
  occasional EUR `spread_ma` (4.5–4.9 vs median 0.60). Catalog slim removes
  the news/SMC/VWAP noise; it does not force Delta to fire in a neutral
  regime.
- Primary branch: main (`fb4f016`). Implementer branch
  `ai/TASK-004-delta-scalp-only`.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
