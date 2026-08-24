# Project Status

- Last verified: 2026-08-24T09:37:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: TASK-002 kernel plus operator live-enable of `xau_vwap_pullback`. VPS live loop reconnected 2026-08-24 after restarting a hollow `terminal64` (IPC timeout -10005). Telegram Positions/Logs no longer call `mt5.initialize`. 1%/1.5R/3% and `CHRONOSCALP_CONFIRM_LIVE` unchanged. VWAP walk-forward still thin — operator override, not a guarantee.
- Telegram: simultaneous-OR picker; `پولبک VWAP (طلا)` cycles off → shadow → live.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail.
- Next milestone: merge to main, deploy VPS, confirm overlay includes VWAP live; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
