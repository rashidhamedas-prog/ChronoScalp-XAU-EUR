# Project Status

- Last verified: 2026-08-23T11:15:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: TASK-002 Bugbot follow-up — comparison paper tickets are namespaced and journal/meta/heat look up by `(symbol, strategy)`. Independent security closed the restart-heat medium on `5f6672f`. `xau_vwap_pullback` stays **not** live-enabled (`live_ready: false`). Do **not** merge until independent functional review of this follow-up plus `44b62a2`.
- Telegram: simultaneous-OR strategy picker; `پولبک VWAP (طلا)` off/shadow only while `live_ready` is false.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail. Live readiness **not** established.
- Next milestone: independent functional review of comparison-ticket isolation + `44b62a2` (security closed the restart-heat medium on `5f6672f`); denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
