# Project Status

- Last verified: 2026-08-14T01:35:00Z
- Primary branch: main (TASK-001 research on `ai/TASK-001-strategy-audit-redesign`)
- Current release/state: Accounting + MistakeMemory + Telegram deployed. Live readiness **not** established.
- VPS evidence (AUSCommercial-Demo `XAUUSD`/`EURUSD`, window ~2026-06-27→2026-08-11):
  - Cost-stress 1.5×: XAUUSD OK (46 trades, E[R]≈0.35, PF≈2.11); EURUSD fail (E[R]<0).
  - Limited WF tiny-grid folds=2: XAUUSD OOS avg return +3.5% (5+4 trades — thin); EURUSD OOS avg −1.76% (fail).
- Next milestone: EURUSD redesign; denser XAUUSD OOS; independent review before live.
- Invariants: 1%/3% intact; do not treat VPS live process as validation pass.
- Telegram: Mistake Memory toggle under Settings → Risk.
