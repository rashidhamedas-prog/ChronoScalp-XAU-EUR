# Phase 1 Pro — Quant Validation Framework

**Date:** 2026-11-12 (Asia/Tehran)  
**Branch:** `cursor/pro-phase1-validation-b46a`  
**Depends on:** Phase 0 merged (`main` @ PR #12)

## Verdict

Phase 1 core validation plane is implemented and unit-tested. Synthetic CLI
smoke is green. Full historical re-claims (P1-7 on live broker CSVs) remain an
operator job once VPS history is mounted — CI uses the synthetic path.

## Delivered

| Area | Artifact |
|---|---|
| Metrics | `validation/metrics.py` — Sharpe, DSR, PBO (CSCV) |
| CPCV | `validation/cpcv.py` — combinatorial purged paths |
| Walk-forward | `validation/walkforward.py` — expanding + embargo |
| Reports | `validation/reports.py` — net-of-cost machine JSON |
| Governance | `validation/governance.py` — geometry change needs DSR>0 |
| Portfolio | `validation/portfolio.py` — summed equity + DD |
| CLI | `python -m chronoscalp.validation.run --all` |
| Costs | session multipliers, news slip, overnight swap helpers |
| Optimizer | `clone_settings_with()` deep copy |

## Gates run

- `pytest tests/test_phase1_validation.py` — green
- Risk 1%/1.5R/3% and `CHRONOSCALP_CONFIRM_LIVE` unchanged

## Residual

- Re-run historical strategy claims on VPS broker CSVs through the new plane
- RVOL prior-N hardening (P1-6) follow-up if live logs still show volume gaps
- VPS deploy of Phase 0 still blocked from this agent (SSH key rejected)
