# Project Status

- Last verified: 2026-08-12T22:50:00Z
- Primary branch: main (TASK-001 research continues on `ai/TASK-001-strategy-audit-redesign`)
- Current release/state: Accounting fixes + MistakeMemory + Telegram risk toggles deployed. Live readiness **not** established.
- Working build/test commands: `.venv/Scripts/python.exe -m pytest -q`; ruff on touched paths.
- Known risks / VPS evidence:
  - AUSCommercial-Demo native symbols: `XAUUSD` / `EURUSD` (not LiteFinance `_o`).
  - Limited 45d cost-stress **complete** (2026-06-27→2026-08-11 UTC):
    - XAUUSD: 46 trades, E[R] 0.354→0.353 @1.5×, PF 2.11, max DD ~2.0% — survives stress on this window.
    - EURUSD: 17 trades, E[R] −0.15→−0.206, PF 0.59→0.48 — **fails**; redesign before any EUR enable.
  - Limited walk-forward next; independent security/review before live.
- Next milestone: limited WF OOS folds; EURUSD strategy redesign path; do not enable live.
- Invariants: 1% per-trade / 3% daily intact. VPS may still run live mode from prior deploy — not a validation pass.
- Telegram: Settings → Risk exposes Mistake Memory on/off.
