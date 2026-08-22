# Project Status

- Last verified: 2026-08-22T16:40:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: Independent multi-strategy kernel + `xau_vwap_pullback` (disabled, shadow_only) in progress on TASK-002. Strategy is **not** live-enabled. Independent reviewer + security still required before merge.
- Telegram: simultaneous-OR strategy picker; `پولبک VWAP (طلا)` off/shadow/on; `/status` shows overlay source + `multi_strategy_mode`; `/pnl` per-strategy.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail. Live readiness **not** established.
- Next milestone: TASK-002 gates (pytest/ruff/black) then independent review; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
