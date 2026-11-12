# Phase 0 → VPS deploy (safe code update)

Phase 0 is **merged to `main`** (PR #12, CI green). Live risk must stay halted
until an operator explicitly restarts after overlay review.

## Blocker from Cloud Agent (2026-11-12 Asia/Tehran)

This Linux agent has `VPS_SSH_KEY` but authentication to `89.23.103.82` and
`45.90.98.99` failed (`Permission denied (publickey)`). Deploy cannot be
completed remotely from this session. Run the steps below on a machine that
already SSHs into the Windows VPS.

## Safe deploy (code only — no live resume)

On the VPS (PowerShell), from a host that can reach it:

```powershell
# From an operator workstation with working VPS SSH / RDP:
cd C:\ChronoScalp\ChronoScalp-XAU-EUR
powershell -File scripts\_vps_safe_code_update.ps1
```

That script:

- `git fetch` + `reset --hard origin/main`
- preserves `config/runtime_overrides.yaml`
- preserves `data/state/STOP_TRADING` (does **not** clear the kill switch)
- does **not** restart the live process

## After code lands

1. Confirm `git log -1` shows the Phase 0 merge (`Merge pull request #12…`).
2. Keep `STOP_TRADING` until overlay catalogs / risk caps are reviewed.
3. Only then use the normal restart path (`watch_bot` / `_vps_full_deploy`
   with `-KeepHalt` if you only want code + halted process).
4. Do **not** loosen 1% / 1.5R / 3% or skip `CHRONOSCALP_CONFIRM_LIVE`.
