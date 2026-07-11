# CLAUDE.md — Project Context for Claude Code

This file is read by Claude Code at the start of a session in this repo. Keep it accurate as the project evolves — it is the single source of truth for how to work on ChronoScalp.

## What this is

Multi-timeframe algorithmic scalping bot for XAUUSD / EURUSD (and broker-native crosses). Full context: [README.md](README.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/ROADMAP.md](docs/ROADMAP.md).

## Current build status

Phases 1–4 of the roadmap are scaffolded with real (not placeholder) logic:
data pipeline, indicators, SMC structure detection, session/news filters, risk
sizing, multi-timeframe strategy, paper + MT5 broker, backtest engine. Phase 5
(hyperopt) and Phase 6 (ML setup-scoring) are stubbed — see `docs/ROADMAP.md`
for exact extension points before building on top of them.

Always re-check `docs/ROADMAP.md` for the current phase checklist before
starting new work — update it when a phase item is completed.

## Non-negotiable rules

1. **Never weaken risk management to "improve" backtest win rate.** Max 1%
   equity risk per trade and the minimum 1:1.5 R:R in `config/settings.yaml`
   are hard constraints, not tuning knobs. If a change to `risk/` or
   `strategy/` would violate them, stop and flag it instead of implementing it.
2. **Never make `--mode live` easier to trigger.** The `CHRONOSCALP_CONFIRM_LIVE`
   env-var gate in `scripts/run_live.py` is intentional friction. Do not
   remove or default it to "yes".
3. **The `Broker` interface (`execution/broker.py`) is the only allowed
   coupling point to a broker SDK.** New broker integrations (OANDA, etc.)
   implement that interface; strategy/risk/filter code must never import a
   broker SDK directly.
4. **`MetaTrader5` (the pip package) only runs on Windows.** Don't add code
   that assumes it works on Linux/macOS, and don't silently swallow the
   ImportError — `data/mt5_connector.py` and `execution/mt5_broker.py` already
   handle this by raising a clear `RuntimeError` on unsupported platforms.
5. **All new strategy/risk logic needs a pytest test** in `tests/` before it's
   considered done — this is a trading system, silent regressions cost money.
6. **Type hints + docstrings on every public function.** Run `ruff check` and
   `black --check` before considering a change finished.

## Workflow expected at the end of every unit of work

Per project owner's standing instruction: after finishing any coding task in
this repo, always:

1. Run `pytest -q` and `ruff check src tests` — fix failures before proceeding.
2. `git add -A && git commit -m "<concise, imperative summary>"`.
3. `git push` (to the configured `origin` remote — see README §Getting Started
   for the GitHub URL; if `origin` isn't configured yet, ask the user for the
   real GitHub repo URL and run `git remote add origin <url>` first).
4. Leave a short note in `docs/ROADMAP.md` (checklist) or `CLAUDE.md` itself
   if the change affects how future sessions (Claude Code or Cursor) should
   approach the project — this keeps both tools' context in sync.

## Conventions

- Python 3.11+, `from __future__ import annotations` at the top of modules
  that use forward references.
- Layout: `src/chronoscalp/<domain>/...`, `scripts/` for CLI entry points,
  `tests/` mirrors `src/chronoscalp/` structure.
- Config: strategy/risk parameters → `config/*.yaml` (typed via
  `src/chronoscalp/config.py`); secrets → `.env` only, never committed.
- Logging via `loguru` (`from chronoscalp.logging_setup import logger`), not
  bare `print()`.
- Timeframes are always one of `Timeframe` enum values (`utils/types.py`) —
  don't pass raw strings like `"5m"` around.

## Where to look for what

| Need to... | Look at |
|---|---|
| Add/adjust an indicator | `src/chronoscalp/indicators/technical.py` |
| Change entry/trend-alignment logic | `src/chronoscalp/strategy/multi_timeframe.py` |
| Change position sizing / breakeven / trailing | `src/chronoscalp/risk/position_sizing.py` |
| Add a news source | `src/chronoscalp/filters/news_filter.py` |
| Add a broker | `src/chronoscalp/execution/broker.py` (interface) + new impl file |
| Change backtest fill/slippage assumptions | `src/chronoscalp/backtest/engine.py` |
| Tune session windows, risk %, spread caps | `config/settings.yaml` (no code change needed) |

This file intentionally mirrors `.cursor/rules/project.mdc` — if you update
one, update the other so Claude Code and Cursor stay aligned.
