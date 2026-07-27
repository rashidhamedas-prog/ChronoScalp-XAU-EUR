# AGENTS.md

Project context, conventions, and workflow rules live in `CLAUDE.md` and
`.cursor/rules/project.mdc` (they mirror each other). Standard lint/test/run
commands are documented in `README.md` §5 and §8. Read those first.

## Cursor Cloud specific instructions

Durable, non-obvious notes for working on this repo inside a Cursor Cloud VM.
The startup update script already creates `.venv/` and installs
`requirements.txt`, so you normally just need to activate it:
`source .venv/bin/activate`.

### Services and how to run them (all from repo root, venv active)

- Backtest CLI (`python scripts/run_backtest.py --symbol <SYM> --from <D> --to <D>`)
  runs anywhere with no broker. It reads CSV history from
  `data/history/<SYMBOL>/<TIMEFRAME>.csv`. `scripts/fetch_history.py` only works
  on Windows+MT5, so on Linux you must drop/generate compatible CSVs yourself
  (columns: `time,open,high,low,close,tick_volume,spread`). With the default
  `settings.yaml` a symbol needs `M15`, `M5`, and `M1` files.
- Streamlit control panel (main end-user app):
  `streamlit run scripts/app.py --server.port 8501 --server.headless true`.
- FastAPI control API: `python scripts/run_api.py --host 127.0.0.1 --port 8510`.
  In `CHRONOSCALP_ENV=development` (the `.env.example` default) the API needs no
  bearer token; `/health` and `/status` work immediately.
- Tests/lint/format: `pytest -q`, `ruff check src tests`, `black --check src tests`
  (see README §8). Tests are hermetic; no services needed.

### Non-obvious gotchas

- The paper/live trading LOOP cannot run in this Linux VM out of the box.
  With `execution.broker: paper` + `data_source: auto` (the shipped default),
  `resolve_data_source` picks `mt5`, and the `MetaTrader5` package is
  Windows-only, so `run_live.py --mode paper` raises a clear `RuntimeError`.
  To actually run the loop on Linux you must set `execution.data_source: oanda`
  in `config/settings.yaml` and provide `OANDA_API_TOKEN` + `OANDA_ACCOUNT_ID`
  (OANDA practice account) in `.env`. Backtest, panel, and API do NOT need this.
- `MetaTrader5` is intentionally NOT installed on Linux (it is platform-gated in
  `requirements.txt`). Do not add it to the Linux dependency set.
- Starting the bot (panel "Start" button, or API `POST /bot/start`) first
  requires an ACTIVE LICENSE. Issue one from the panel "License admin (seller)"
  page using the `LICENSE_ADMIN_SECRET` from `.env`, then activate the key on the
  "License" page. License + activation + runtime state persist under `data/`
  (all git-ignored: `data/licenses/`, `data/user/`, `data/state/`).
- `.env` is required for the panel/API/bot; create it once with
  `cp .env.example .env`. It is git-ignored — never commit it.
- Config lives in `config/settings.yaml`; the loader (`get_settings`) is cached,
  so the panel calls `get_settings.cache_clear()` after writes. If you change
  YAML/`.env` while a long-running process is up, restart it.
