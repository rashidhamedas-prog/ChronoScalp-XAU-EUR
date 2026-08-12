# Project Status

- Last verified: 2026-08-12T15:57:00Z
- Primary branch: main (TASK-001 research / VPS history in progress)
- Current release/state: Accounting fixes + MistakeMemory + Telegram risk toggles deployed. Live readiness **not** established.
- Working build/test commands: `.venv/Scripts/python.exe -m pytest -q --basetemp .tmp_pytest_merge1` FULL_EXIT=0; ruff RUFF_EXIT=0.
- Known risks / VPS evidence:
  - AUSCommercial-Demo native symbols: `XAUUSD` / `EURUSD` (not LiteFinance `_o`).
  - Chunked `fetch_ohlcv_range` needed (tz-aware + large range → Invalid params).
  - History depth: ~100k M1/M5 XAU+EUR (broker cap); ~47–50k M15.
  - Full WF grid on 100k M1 too slow interactively; earlier WF also hit tz bug in `run_backtest` date filter.
  - Cost-stress metrics: UNKNOWN pending shell agent.
  - Live journal historical rows not rewritten; MistakeMemory needs trading-bot restart after Telegram toggle.
- Next milestone: finish VPS cost-stress on `XAUUSD`/`EURUSD`; then limited walk-forward (fewer folds / shorter window) after TZ fix; independent security/review before live.
- Invariants: live disabled; 1% per-trade / 3% daily intact.
- Telegram: Settings → Risk exposes Mistake Memory on/off; status/config show `mistake_memory=on|off`.
