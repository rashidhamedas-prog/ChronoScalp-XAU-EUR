# Phases 2–4 — Intelligence, packaging scaffold, RL shadow

**Branch:** `cursor/pro-phase2-4-intelligence-b46a` (stacked on Phase 1)

## Phase 2
- [x] Regime detector (hmmlearn or GMM fallback) + model card
- [x] Net-of-cost expectancy ranking helpers
- [x] ML remains off by default; scorer population unchanged
- [x] news_straddle stays out of live until validated (catalog unchanged; docs)

## Phase 3
- [x] Bridge protocol schema + `mql5/chronoscalp_bridge.mq5` skeleton
- [x] FA/EN i18n catalog + `/i18n/{lang}` + `/diagnostics/bridge`
- [x] Windows packaging runbook (`docs/WINDOWS_PACKAGING.md`)
- [ ] Inno/NSSM/tray binary build (requires Windows build box)

## Phase 4
- [x] RL position manager shadow stub + kill-path revert
- [x] Size multiplier hard-capped at ≤1.0
- [ ] SB3 training + OOS beat-baseline (blocked until Phase 1 historical claims)

## Gates
- `tests/test_phase2_4_intelligence.py`
- Risk 1%/1.5R/3% and live confirm unchanged
