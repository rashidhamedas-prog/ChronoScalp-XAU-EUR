# Project Status

- Last verified: 2026-08-11T17:15:00Z
- Primary branch: main (merge of TASK-001 forensic + MistakeMemory + Telegram controls in progress)
- Current release/state: Accounting fixes + deterministic MistakeMemory + Telegram risk toggles on `ai/TASK-001-strategy-audit-redesign`. Live readiness **not** established.
- Working build/test commands: `.venv/Scripts/python.exe -m pytest -q --basetemp .tmp_pytest_merge1` FULL_EXIT=0; ruff RUFF_EXIT=0.
- Known risks: no broker-native history yet; live journal historical rows not rewritten; MistakeMemory needs trading-bot restart after Telegram toggle.
- Next milestone: fetch broker-native XAUUSD_o / EURUSD_o M1 (`scripts/fetch_history.py`), then walk-forward + 1.5x cost stress; independent security/review before live.
- Telegram: Settings → Risk exposes Mistake Memory on/off; status/config show `mistake_memory=on|off`.
