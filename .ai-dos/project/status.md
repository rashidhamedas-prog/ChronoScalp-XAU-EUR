# Project Status

- Last verified: 2026-08-12T21:20:00Z
- Primary branch: main (TASK-001 research / VPS cost-stress in progress on feature branch)
- Current release/state: Accounting fixes + MistakeMemory + Telegram risk toggles deployed. Live readiness **not** established.
- Working build/test commands: `.venv/Scripts/python.exe -m pytest -q --basetemp .tmp_pytest_merge1` FULL_EXIT=0; ruff RUFF_EXIT=0.
- Known risks / VPS evidence:
  - AUSCommercial-Demo native symbols: `XAUUSD` / `EURUSD` (not LiteFinance `_o`).
  - Chunked `fetch_ohlcv_range` needed (tz-aware + large range → Invalid params).
  - History depth: ~100k M1/M5 XAU+EUR (broker cap); ~47–50k M15.
  - Full WF grid on 100k M1 too slow interactively; TZ date-filter bug fixed (`_to_utc_timestamp`).
  - Prior full-history XAUUSD cost-stress (2026-08-11): 85 trades, expectancy_r 0.219→0.218 @1.5×, PF 1.654→1.652, max DD ~4.4%. EURUSD summary stale/`missing_history` — not trusted.
  - Limited `--last-days 45` cost-stress for XAU+EUR **IN PROGRESS** on VPS (~30 min/backtest); live trading bots left alone.
  - Live journal historical rows not rewritten; MistakeMemory needs trading-bot restart after Telegram toggle.
- Next milestone: finish limited cost-stress JSON; limited walk-forward; independent security/review before live.
- Invariants: live disabled for strategy acceptance; 1% per-trade / 3% daily intact. (VPS may still run live mode from prior deploy — do not treat as validation pass.)
- Telegram: Settings → Risk exposes Mistake Memory on/off; status/config show `mistake_memory=on|off`.
