# Project Status

- Last verified: 2026-08-11T16:45:00Z
- Primary branch: main
- Current release/state: Research scaffold on `ai/TASK-001-strategy-audit-redesign`. Live readiness is **not** established; live enablement remains frozen pending broker-native walk-forward / OOS / 1.5x cost-stress.
- Working build/test commands: `.venv/Scripts/python.exe -m pytest -q --basetemp .tmp_pytest_task001_full5` passed (FULL_EXIT=0); `.venv/Scripts/python.exe -m ruff check src tests scripts` passed; black --check on TASK-001 touched product files passed (repo-wide black still has pre-existing offenders).
- Known risks: historical live journal still contains abnormal lots / bad R / timestamp issues (not rewritten); no broker-native history dataset in repo; MistakeMemory session stamped at close time may differ from entry session.
- Technical debt: AI-DOS quality commands in ai-dos.yaml still placeholders; journal open-row SL not refreshed on trail; MT5 close path historically omitted r_multiple (now recomputed in journal when specs present).
- Next milestone: acquire broker-native XAUUSD/EURUSD M1 data; design separate scalp vs M15-H1 experiments with walk-forward + cost stress; independent reviewer/security before any live flag.
- Forensic RCA (closed for accounting bugs):
  - Huge lots: 1%-consistent with large equity × ultra-tight stops + high broker max_lot → mitigated by `operational_max_lot`.
  - |R|>10: `$pnl / price_distance` in external close → fixed to dollar-risk R + symbols_cfg wiring.
  - Blank/orphan rows: external close without open → now returns None.
  - Zero-trade XAU “backtests” in logs: synthetic off-session pytest fixtures, not engine crash.
- MistakeMemory: deterministic learn-from-mistakes veto shipped (not ML); setup bucket prefers 2nd reason token.
