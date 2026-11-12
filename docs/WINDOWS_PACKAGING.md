# Windows packaging (Phase 3) — operator runbook

This Linux CI host cannot build `ChronoScalpPro_Setup.exe` or compile
`mql5/chronoscalp_bridge.mq5`. Artifacts to produce on a Windows build box:

1. **Inno Setup** installer embedding the Python runtime + repo wheel.
2. **NSSM** service wrapping `scripts/run_live.py` with graceful stop via
   `scripts/stop.bat` (already Phase 0 hardened).
3. Compile `mql5/chronoscalp_bridge.mq5` in MetaEditor; wizard copies it into
   the MT5 `MQL5/Experts` data folder.
4. Secrets via Windows Credential Manager (DPAPI) — never plaintext `.env` on
   customer installs.
5. Local dashboard: FastAPI on `127.0.0.1` + tray; strings from
   `chronoscalp.saas.i18n` (FA/EN).

Acceptance (from master prompt) still requires a clean Win10/11 VM soak —
track outside this PR.
