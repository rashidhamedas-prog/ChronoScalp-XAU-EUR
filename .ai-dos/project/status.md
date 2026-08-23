# Project Status

- Last verified: 2026-08-23T13:20:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat` (operator confirmed merge + deploy + VWAP live).
- Current release/state: TASK-002 kernel plus operator live-enable of `xau_vwap_pullback` (`enabled: true`, `shadow_only: false`, `live_ready: true`, listed on `enabled_strategies`). Independent review of the six findings closed. 1%/1.5R/3% and `CHRONOSCALP_CONFIRM_LIVE` unchanged. Walk-forward evidence for VWAP is still thin — this is an operator override, not a guarantee.
- Telegram: simultaneous-OR picker; `پولبک VWAP (طلا)` cycles off → shadow → live.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail.
- Next milestone: merge to main, deploy VPS, confirm overlay includes VWAP live; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
