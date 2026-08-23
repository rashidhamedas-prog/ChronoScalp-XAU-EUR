# Project Status

- Last verified: 2026-08-23T10:45:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: TASK-002 bugbot follow-up — comparison reconcile now reads virtual books; pending cancel keeps heat until the broker drop; VWAP stop expiry counts closed M1 bars. `xau_vwap_pullback` stays **not** live-enabled (`live_ready: false`). Do **not** merge until independent reviewer/security pass this commit.
- Telegram: simultaneous-OR strategy picker; `پولبک VWAP (طلا)` off/shadow only while `live_ready` is false.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail. Live readiness **not** established.
- Next milestone: independent reviewer + security on this commit; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
