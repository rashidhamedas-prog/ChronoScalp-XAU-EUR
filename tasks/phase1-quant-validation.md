# Phase 1 — Quant Validation Framework

**Task:** `TASK-PRO-P1`  
**Branch:** `cursor/pro-phase1-validation-b46a`  
**Depends on:** Phase 0 merged to `main` (PR #12)

## Checklist

| ID | Item | Status |
|---|---|---|
| P1-1 | Extended shared cost model (session spread mult, swap/day, news slip) | done |
| P1-2 | Documented SL-first shared resolver (already in position_logic) | done |
| P1-3 | Portfolio equity curve helper + deep clone_settings | done |
| P1-4 | `chronoscalp.validation` — WF purge/embargo, CPCV, DSR, PBO | done |
| P1-5 | Parameter freeze gate (DSR>0 report required for geometry diffs) | done |
| P1-6 | Quant defect hooks deferred residual: RVOL prior-N hardening follow-up | partial |
| P1-7 | CLI `python -m chronoscalp.validation.run --all` + synthetic CI path | done |

## Acceptance

- `python -m chronoscalp.validation.run --all` emits machine-readable JSON
- Unit tests cover DSR/PBO/CPCV + cost session multipliers
- Risk 1%/1.5R/3% and live confirm unchanged
