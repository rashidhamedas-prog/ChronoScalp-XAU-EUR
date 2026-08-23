# Project Status

- Last verified: 2026-08-23T10:30:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: TASK-002 security follow-up — pending-order heat is restored after restart/reconcile (news OCO uses max-leg, unreadable geometry or pending-list failure fail-closes new entries). Previous merge-blocking review fixes remain. `xau_vwap_pullback` stays **not** live-enabled (`live_ready: false`). Do **not** merge until a new independent security/reviewer pass lands on this commit.
- Telegram: simultaneous-OR strategy picker; `پولبک VWAP (طلا)` off/shadow only while `live_ready` is false.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail. Live readiness **not** established.
- Next milestone: independent reviewer + security on the restart-heat commit; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
