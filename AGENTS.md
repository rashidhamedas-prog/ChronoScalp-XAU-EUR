# AGENTS.md — guidance for coding agents

This repository is **ChronoScalp**: a multi-timeframe algorithmic scalping bot for XAUUSD / EURUSD (and broker-native crosses).

## Read first

| Doc | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Standing rules, workflow, where-to-look map |
| [README.md](README.md) | Setup, run modes, architecture summary |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Broker split (MT5 Windows vs OANDA Linux) |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phase checklist — re-check before new work |
| [docs/VPS_TROUBLESHOOTING_FA.md](docs/VPS_TROUBLESHOOTING_FA.md) | Windows VPS ops runbook |

## Hard constraints (do not violate)

1. Never loosen risk management to chase win rate. Max **1%** equity risk / trade and minimum **1:1.5** R:R in `config/settings.yaml` are fixed.
2. Never remove or weaken `CHRONOSCALP_CONFIRM_LIVE` in `scripts/run_live.py`.
3. Broker SDKs (`MetaTrader5`, REST clients) only inside `src/chronoscalp/execution/*_broker.py` (plus data connectors). Strategy/risk/filters use the `Broker` interface.
4. `MetaTrader5` pip package is Windows-only — do not assume it imports on Linux/macOS.
5. New strategy/risk logic needs a matching `tests/` file.
6. **Never commit secrets** (`.env`, `لاگین.txt`, hardcoded API/MT5 passwords). Use `.env.example` placeholders only.

## End of every coding task

Unless the user says “don’t commit/push”:

1. `pytest -q` and `ruff check src tests`
2. Commit relevant changes (no secrets)
3. `git push` to `origin`
4. Update `docs/ROADMAP.md` if a checklist item completed

Default branch is **`main`**. Keep feature work on short-lived `cursor/*` branches and merge to `main` when done — do not leave finished work only on remote feature branches.

## Quick layout

- `src/chronoscalp/` — library code
- `scripts/` — CLI / panel / VPS helpers
- `config/*.yaml` — strategy & risk parameters
- `tests/` — mirrors package layout
- News ATR straddle: `filters/news_calendar.py` + `strategy/news_straddle_engine.py` (enable via `news_straddle` in panel/Telegram)
- Strategy Delta (XAUUSD/EURUSD): `strategy/delta.py` + `docs/STRATEGY_DELTA.md` — toggle via Telegram `تنظیمات → استراتژی‌ها → دلتا` or the Streamlit panel; persists in `runtime_overrides.yaml`. Not live-ready until validation gates pass.

## Imported Claude Cowork project instructions

تمامی اقدامات ضروری در انتهای اجرای هر دستور انجام شود 
push
commit
ذخیره در حافظه برای cursor
