# Phases 2–4 Pro — Intelligence / Packaging scaffold / RL shadow

**Date:** 2026-11-12 (Asia/Tehran)  
**Branch:** `cursor/pro-phase2-4-intelligence-b46a`

## Verdict

Code scaffolds for Phases 2–4 are in place and unit-tested. Full product
acceptance (Windows installer soak, SB3 beat-baseline, 30/30/30 RL ladder)
**cannot** be marked done from this Linux Cloud Agent — those gates need a
Windows VPS/build box and broker history.

## Delivered here

| Phase | Artifact |
|---|---|
| 2 | `intelligence/regime.py`, `expectancy.py`, `model_card.py` |
| 3 | `bridge/protocol.py`, `mql5/chronoscalp_bridge.mq5`, `saas/i18n.py`, API `/i18n` + `/diagnostics/bridge`, `docs/WINDOWS_PACKAGING.md` |
| 4 | `intelligence/rl_manager.py` shadow + kill-path |

## Not claimed done

- Win10/11 zero→installed <10 min / 7-day unattended soak
- HMM live wiring into `main.py` tick loop (helpers ready; default off)
- Stable-Baselines3 trained policy with DSR>0 multi-regime report
- Live news_straddle enablement
