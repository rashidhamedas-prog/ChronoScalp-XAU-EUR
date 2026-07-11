# Roadmap

Status legend: ✅ scaffolded with real logic · 🟡 stubbed / partial · ⬜ not started

## Phase 1 — Data pipeline ✅
- [x] MT5 connector: multi-symbol, multi-timeframe OHLCV fetch (`data/mt5_connector.py`)
- [x] Missing-bar / gap handling
- [x] Historical fetch CLI (`scripts/fetch_history.py`)
- [ ] Tick-level spread history capture (currently uses configured static spread cap; live spread sampling is a good next step)

## Phase 2 — Multi-timeframe feature extraction ✅
- [x] EMA(50), RSI(14) on M10/M5 for trend detection (`indicators/technical.py`)
- [x] Bollinger Bands + MACD on M3/M1 for entry signals
- [x] Trend-alignment gate: trade only if M10 and M5 agree (`strategy/multi_timeframe.py`)

## Phase 3 — Session & news filtering ✅
- [x] London (08:00–11:00 GMT) / New York (13:30–16:30 GMT) session windows (`filters/session_filter.py`, configurable in `config/settings.yaml`)
- [x] News blackout filter interface + manual/CSV calendar fallback (`filters/news_filter.py`)
- [ ] Live economic-calendar API integration (needs an API key — see `.env.example`; ships with a manual-event-list fallback so it works with zero external dependencies)

## Phase 4 — Risk management & position sizing ✅
- [x] Equity-percentage position sizing, capped at 1%/trade (`risk/position_sizing.py`)
- [x] Kelly-criterion sizing helper, hard-capped by the 1% ceiling (never allowed to exceed it)
- [x] Breakeven-at-1R and ATR-based trailing stop
- [x] Hard spread filter (`if spread > max_allowed_spread: skip`)

## Phase 5 — Backtesting & optimization 🟡
- [x] Event-driven backtest engine with spread/slippage modeling (`backtest/engine.py`)
- [x] Equity curve, win rate, profit factor, max drawdown, expectancy reporting
- [ ] Grid-search / walk-forward optimization over indicator parameters (extension point: `backtest/engine.py::run_backtest()` is pure and side-effect free, so wrapping it in a parameter sweep is a small addition — do not hardcode optimized params back into `config/settings.yaml` without walk-forward validation, to avoid overfitting)

## Phase 6 — Advanced techniques 🟡
- [x] SMC structure detection: swing points, BOS/CHoCH, order blocks, FVGs, liquidity sweeps (`smc/structure.py`)
- [ ] ML setup-probability scoring — hook exists (`strategy/multi_timeframe.py::score_setup_probability`), model training pipeline not yet built. Needs: (1) run backtest to generate labeled setups, (2) feature-engineer indicator+SMC state at signal time, (3) train/validate a classifier out-of-sample, (4) only then wire into live filtering as an additional confidence gate, never as the sole signal source
- [x] Fast breakeven + trailing stop (Phase 4, listed here too since the brief grouped it under "advanced techniques")
- [x] Hard spread-filter constraint

## Operational / deployment (added — not in the original brief, but required for production use)
- [x] Broker abstraction resolving the Linux-VPS-vs-MT5-Windows-only conflict (see `docs/ARCHITECTURE.md`)
- [x] Docker packaging (`docker/Dockerfile`, `docker/docker-compose.yml`)
- [x] Structured logging + optional Sentry integration
- [x] CI (lint + tests on push)
- [ ] OANDA REST broker implementation, if Linux-native live deployment is chosen over Windows VPS + MT5
- [ ] Alerting (Telegram/Discord webhook on trade open/close, daily loss-limit hit, connection loss) — recommended next addition for unattended operation
