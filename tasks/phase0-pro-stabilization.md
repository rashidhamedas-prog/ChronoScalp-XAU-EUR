# Phase 0 — Professional Edition Stabilization

**Task:** `TASK-PRO-P0`  
**Branch:** `cursor/pro-phase0-stabilization-b46a`  
**Gate:** Phase 1–4 blocked until this acceptance pack is verified.

## Scope

Fail-closed hardening only. No risk loosening. KEEP existing strategy/risk
strengths. Hybrid MQL5 / full CPCV / UI deferred to later phases.

## Checklist

| ID | Item | Status |
|---|---|---|
| C-01 / P0-1 | Cost-real paper (½ spread + commission/side) | done |
| C-02 / P0-2 | Shared SL-first intrabar + ML chrono split+embargo | done |
| C-03 / P0-3 | MT5 M1 freshness tick guard | done |
| C-04 / P0-4 | OANDA closed PnL via transactions | done |
| C-05 / P0-5 | Atomic JSON state (temp+fsync+replace+.bak) | done |
| C-06 / P0-6 | Broker clock ≠ UTC (offset + normalize) | done |
| P0-7 | API/Telegram fail-closed + control PIN | done |
| P0-8 | Single-instance lock | done |
| P0-9 | Circuit breaker (min trip + success threshold) | done |
| P0-10 | Reject unenforced overlay keys | done |
| P0-11 | Alert async queue + flush | done |
| P0-12 | Bounded persistence helpers | done |
| Chaos | Phase0 stabilization regression suite | done |

## Validation

- `pytest -q` — green
- `ruff check src tests` — green
- Evidence: `tests/test_phase0_stabilization.py` + updated API/Telegram/alerts/overrides tests

## Non-goals (later phases)

- Full cost-engine rewrite / CPCV
- Windows installer / MT5 EA chaos on Linux CI
- Phase 3 UI / 21st.dev surfaces
