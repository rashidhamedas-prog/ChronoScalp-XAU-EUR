# Project Status

- Last verified: 2026-08-23T10:45:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: TASK-002 bugbot follow-up on `44b62a2` — comparison reconcile, cancel-heat, VWAP M1 expiry. Independent security closed the restart-heat medium on `5f6672f`. `xau_vwap_pullback` stays **not** live-enabled (`live_ready: false`). Do **not** merge until independent functional review of `44b62a2`.
- Telegram: simultaneous-OR strategy picker; `پولبک VWAP (طلا)` off/shadow only while `live_ready` is false.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail. Live readiness **not** established.
- Next milestone: independent functional review of `44b62a2` (security closed the restart-heat medium on `5f6672f`); denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
