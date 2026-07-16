# Roadmap

Status legend: ✅ scaffolded with real logic · 🟡 stubbed / partial · ⬜ not started

## Phase 1 — Data pipeline ✅
- [x] MT5 connector: multi-symbol, multi-timeframe OHLCV fetch (`data/mt5_connector.py`)
- [x] Missing-bar / gap handling
- [x] Historical fetch CLI (`scripts/fetch_history.py`)
- [x] Tick-level spread history capture (`data/spread_sampler.py`, `spread_filter.sample_live_spread`)

## Phase 2 — Multi-timeframe feature extraction ✅
- [x] EMA(50), RSI(14) on M10/M5 for trend detection (`indicators/technical.py`)
- [x] Bollinger Bands + MACD on M3/M1 for entry signals
- [x] Trend-alignment gate: trade only if M10 and M5 agree (`strategy/multi_timeframe.py`)

## Phase 3 — Session & news filtering ✅
- [x] London (08:00–11:00 GMT) / New York (13:30–16:30 GMT) session windows (`filters/session_filter.py`, configurable in `config/settings.yaml`)
- [x] News blackout filter interface + manual/CSV calendar fallback (`filters/news_filter.py`)
- [x] Live economic-calendar API integration via Finnhub (`filters/news_filter.py::_fetch_events_from_api`, `NEWS_API_KEY` in `.env`)

## Phase 4 — Risk management & position sizing ✅
- [x] Equity-percentage position sizing, capped at 1%/trade (`risk/position_sizing.py`)
- [x] Kelly-criterion sizing helper, hard-capped by the 1% ceiling (never allowed to exceed it)
- [x] Breakeven-at-1R and ATR-based trailing stop
- [x] Hard spread filter (`if spread > max_allowed_spread: skip`)

## Phase 5 — Backtesting & optimization ✅
- [x] Event-driven backtest engine with spread/slippage modeling (`backtest/engine.py`)
- [x] Equity curve, win rate, profit factor, max drawdown, expectancy reporting
- [x] Grid-search / walk-forward optimization over indicator parameters (`backtest/optimizer.py`, `scripts/run_optimize.py` — results are JSON-only, never auto-written to `config/settings.yaml`)

## Phase 6 — Advanced techniques ✅
- [x] SMC structure detection: swing points, BOS/CHoCH, order blocks, FVGs, liquidity sweeps (`smc/structure.py`)
- [x] ML setup-probability scoring — training pipeline (`ml/dataset.py`, `ml/model.py`, `scripts/train_ml_model.py`), feature extraction, optional live gate via `ml.enabled` + `strategy.min_signal_confidence` (never sole signal source)
- [x] Fast breakeven + trailing stop (Phase 4, listed here too since the brief grouped it under "advanced techniques")
- [x] Hard spread-filter constraint

## Operational / deployment (added — not in the original brief, but required for production use)
- [x] Broker abstraction resolving the Linux-VPS-vs-MT5-Windows-only conflict (see `docs/ARCHITECTURE.md`)
- [x] Docker packaging (`docker/Dockerfile`, `docker/docker-compose.yml`)
- [x] Structured logging + optional Sentry integration
- [x] CI (lint + tests on push)
- [x] **Phase A safety (execution reliability):** MT5 spread points→pips fix, shared MT5 connector, dynamic order filling mode, position ticket verification after `order_send`, bar-close-only entry gate, signal deduplication, persistent state + broker reconciliation, paper-live SL/TP simulation, `max_concurrent_positions` enforcement, daily PnL tracking on close (`orchestration/`, `execution/mt5_utils.py`, `execution/position_logic.py`)
- [x] **Phase B resilience:** kill switch (`CHRONOSCALP_STOP_TRADING` / `data/state/STOP_TRADING`), circuit breaker after consecutive loop errors, Telegram/Discord alerting on trade open/close, daily loss limit, connection loss, and critical faults (`orchestration/kill_switch.py`, `circuit_breaker.py`, `alerts.py`)
- [x] **Periodic reconciliation:** broker ↔ state sync every N seconds in live loop (`resilience.reconcile_interval_seconds`)
- [x] OANDA v20 REST broker + connector for Linux VPS deployment (`execution/oanda_broker.py`, `data/oanda_connector.py`, `docs/DEPLOY_NL_VPS.md`)
- [x] Bilingual Streamlit dashboard (`scripts/dashboard.py`, `scripts/dashboard_i18n.py`)
- [x] Windows launcher: `scripts/start.bat` + `scripts/stop.bat`
- [x] VPS setup script: `scripts/vps-setup.sh`
- [x] Persian step-by-step guide: `docs/RAHNAMA_FA.md`
- [ ] **User action — VPS deploy:** purchase Netherlands VPS, configure `.env`, run `docker compose up` (see `docs/RAHNAMA_FA.md` §13)
