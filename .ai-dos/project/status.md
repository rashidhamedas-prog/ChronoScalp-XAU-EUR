# Project Status

- Last verified: 2026-08-22T17:15:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: TASK-002 merge-blocking review fixes implemented (news heat reservation before place, fair batch risk, VWAP stop-pending, live_ready fail-closed, comparison books, HTF no-lookahead, max_concurrent re-check, incomplete-heat fail-closed, TradingBot.tick tests). `xau_vwap_pullback` stays **not** live-enabled (`live_ready: false`). Do **not** merge until a new independent review passes.
- Telegram: simultaneous-OR strategy picker; `پولبک VWAP (طلا)` off/shadow only while `live_ready` is false.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail. Live readiness **not** established.
- Next milestone: independent reviewer + security on the new commit; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
