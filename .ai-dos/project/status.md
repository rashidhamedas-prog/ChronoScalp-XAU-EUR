# Project Status

- Last verified: 2026-08-31T12:15:00Z
- TASK-004: strategies are owned by the selected symbol. Telegram/panel no
  longer have a strategy picker. Live 2026-08-31 no-trade cause was the
  global 1.50 rvol gate + gold spread floor + overlay with news/SMC off.
  Telegram 2026-08-31: process was up and handled inbound status/menu, but
  sendMessage died with ConnectionError and getUpdates ReadTimeouts slept
  the poll loop — operator saw no replies. Retry + short send timeout shipped.
- Primary branch: main (`29463ec`). Implementer branch `ai/TASK-002-xau-vwap-multistrat` is merged into it; VPS `45.90.98.99` is on `main` at the same SHA, so a standard `_vps_full_deploy` no longer rolls anything back.
- Current release/state: the live bot had opened no trades since 2026-08-21 because `watch_bot.ps1` judged MT5 health by working set, which Windows trims on idle terminals. It recycled a healthy MT5 and then killed the healthy bot every ~7 minutes (137 restarts on 2026-08-24). Watchdog health now reads private bytes and only recycles on real failure evidence; a connect counts as hung only when nothing resolves it. Verified: 22 min uptime with zero recycles while MT5 sat at `ws_mb=6.4` / `priv_mb=49.3`.
- VPS overlay: symbols are `XAUUSD` + `EURUSD`. `BTCUSD` was removed because the broker lists it as `BTCUSD.ca`; re-adding crypto needs a `BTCUSD.ca` entry in `config/symbols.yaml` plus an alias, not just a symbols-list edit.
- Telegram: simultaneous-OR picker; `پولبک VWAP (طلا)` cycles off → shadow → live.
- VPS evidence (AUSCommercial-Demo, ~2026-06-27→2026-08-11) unchanged: XAUUSD cost-stress OK, EURUSD fail.
- Known noise: Finnhub calendar returns HTTP 403, so `news_straddle` has no event feed. `debug-ece9a8.log` instrumentation is still enabled.
- Next milestone: observe a full London/NY session for the first live entry; denser XAUUSD OOS; EURUSD redesign.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
