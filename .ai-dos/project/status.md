# Project Status

- Last verified: 2026-08-24T21:25:00Z
- Primary branch: main. Active implementer branch: `ai/TASK-002-xau-vwap-multistrat`.
- Current release/state: Local overlay was a demo/shadow leftover (`broker: paper`, strategies=`delta`+`liquidity_volume`, `max_concurrent=1`) so live could not place MT5 orders and VWAP/SMC never evaluated. Live mode now ignores overlay `broker: paper`. Local overlay restored to settings.yaml strategies + MT5 + 3% heat. Session still `london_ny` (NY overlay 13:30–16:30 America/New_York). 1%/1.5R/3% and `CHRONOSCALP_CONFIRM_LIVE` unchanged.
- Telegram: simultaneous-OR picker; `پولبک VWAP (طلا)` cycles off → shadow → live.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail.
- Next milestone: VPS is on `ccff6ea` live; merge to origin/main before the next `_vps_full_deploy`; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
