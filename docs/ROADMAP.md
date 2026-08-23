# Roadmap

## Strategy Delta — implemented, validation pending

- [x] Explainable M15/M5 regime + M1 sweep/retest entry engine
- [x] Structure/ATR/spread-aware stop geometry and >=1.5R target floor
- [x] XAUUSD/EURUSD allowlist, unit tests, and operator documentation
- [x] Telegram menu toggle, runtime persistence, and status visibility
- [x] Streamlit panel strategy picker + unified `resolve_enabled_strategies` (incl. delta-only path)
- [x] Broker-native history on VPS AUSCommercial-Demo: `XAUUSD`/`EURUSD` M1/M5/M15 (~100k M1/M5; not LiteFinance `_o`) — see `docs/STRATEGY_RESEARCH.md`
- [x] Limited 45d baseline + 1.5× cost-stress (2026-08-12): XAUUSD survives (E[R]≈0.35, PF≈2.11); EURUSD fails (E[R]<0) — live still disabled
- [x] Applied evidence to config: EURUSD removed from active symbols; Delta gold-only (`allowed_symbols: [XAUUSD]`)
- [ ] Longer-horizon WF / denser OOS for XAUUSD; **EURUSD strategy redesign**
- [ ] Cost-stressed Monte Carlo analysis and 100+ demo trades per symbol
- [ ] **Do not enable live** until denser WF/OOS + EUR redesign gates pass; keep 1%/3%

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
- [x] London (08:00–11:00 local `Europe/London`) / New York (08:30–11:30 local `America/New_York`) DST-aware session windows (`filters/session_filter.py`; invalid TZ fail closed)
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
- [x] Live trading stats dashboard: net/today P&L, open/closed counts, win rate, avg return, profit factor, streaks + auto-refresh (`orchestration/trade_journal.py`, `scripts/dashboard_stats.py`)
- [x] BTCUSD multi-symbol (24/7 session bypass) + risk presets 0.5%/1%/1.5% with hard 1% ceiling (`config/settings.yaml`, `risk/position_sizing.py`)
- [x] EURJPY multi-symbol + volume-confirmed liquidity strategy (`use_liquidity_volume`, RVOL + `liquidity_sweep_*_vol`)
- [x] USDJPY + ETHUSD symbols; panel multi-select for symbols & strategies (default all on; OR confluence)
- [x] Ultra-scalp mode (S15 from MT5 ticks, impulse+RVOL entry, panel strategy option)
- [x] Ultra-scalp scoped 1:1 R:R exception (`strategy.ultra_scalp.min_reward_risk_ratio`); global floor stays 1.5
- [x] Ultra-scalp crypto fixes: skip SMC on S15 unless `require_confluence`, primary M5 trend mode, tunable impulse/RVOL, tick-count volume when MT5 volume=0, granular skip reasons
- [x] MT5 reconnect + data-starvation alerts + skip heartbeat (avoids silent no-trade stalls)
- [x] Control API for remote monitoring (`scripts/run_api.py`, `src/chronoscalp/saas/api.py`)
- [x] Windows launcher: `scripts/start.bat` + `scripts/stop.bat`
- [x] VPS setup script: `scripts/vps-setup.sh`
- [x] Windows VPS one-shot setup: `scripts/windows_vps_setup.ps1` (MT5 + paper path)
- [x] Persian step-by-step guide: `docs/RAHNAMA_FA.md`
- [x] **SaaS packaging:** license/subscription (`licensing/`), user control panel (`scripts/app.py`), easy broker wizard, IB referral section (`docs/FOROOSH_FA.md`)
- [x] **Telegram control bot:** start/stop paper+live, status, P&L, open positions, kill switch, logs + Persian reply keyboard (`src/chronoscalp/telegram/control_bot.py`, `docs/TELEGRAM_BOT_FA.md`)
- [x] **Telegram Stop actually kills `run_live`:** stop all `run_live.py` trees (not only pid-file PID), `/stop`/`استاپ` = process stop, Start restarts if still up, watchdog honors `data/user/bot.stopped`
- [x] **Telegram watchdog:** `scripts/watch_telegram.ps1` Scheduled Task keeps control bot alive on Windows VPS
- [x] **Institutional Scalper v3:** Session VWAP + Asian mid trend (M15/M5), sweep+MSS+RVOL entry, ultra S15 VWAP/RVOL 1.3, 3-strikes, correlation/vol/spread-MA guards, daily DD close-all, partial TP@1.2R + Chandelier trail
- [x] **Volatility guard fix:** regime uses M5 ATR/close (not S15 trigger); thresholds + skip reasons (`volatility_low`/`high`/`invalid`) so ultra-scalp no longer blocks every symbol
- [x] **Telegram live positions:** «پوزیشن‌ها» live-first MT5/OANDA query (fallback: fresh `broker_positions_*.json`); empty-state shows login/equity/margin; journal ghost-drop has 90s grace; reconcile records external SL/TP closes with PnL
- [x] **MT5 stale-stops gate:** refuse `order_send` when live ask/bid has moved through signal SL/TP (prevents `Invalid stops`); skip as `stale_stops` without tripping circuit breaker
- [x] **Broker-clock tick window:** S15 bars from `copy_ticks_range` anchored to the broker's latest tick time (LiteFinance = UTC+3); real-UTC end silently dropped the newest 3h of ticks so all signals priced from stale bars
- [x] **Commission-aware risk:** `commission_pct_notional`/`commission_per_lot` in `symbols.yaml` (LiteFinance crypto ≈0.12% round-turn); sizing keeps price-risk+commission ≤1%, `validate_signal` requires net R:R after commission (blocks guaranteed-negative crypto micro-scalps), fills slipping >50% of SL distance rejected; ETHUSD `pip_value_per_lot` corrected (was 100× under-risking)
- [x] **Cost-aware ultra-scalp geometry:** `fit_economic_scalp_geometry` widens S15 SL to 2× typical spread and TP to net ≥1:1 after costs (within ATR caps); config uses wider ATR multiples + `trend_mode: primary` — 1% equity risk ceiling unchanged
- [x] **Multi-strategy OR + trading hours modes:** ultra-scalp no longer blocks SMC/liquidity; panel/Telegram `london_ny` vs `always_on_24h` (`sessions.trading_hours_mode`)
- [x] **Parallel strategy engines:** S15 ultra-scalp, M1 SMC, and liquidity evaluate independently on their own bar closes. Production paths keep **all** candidates (`evaluate_candidates`); `pick_best_signal` is unused on live/paper/backtest.
- [x] **Independent symbol+strategy entries:** open tickets keyed `(symbol, strategy, ticket)` so Delta cannot block news/liquidity/`xau_vwap_pullback` on the same symbol. Live shared portfolio heat 3% (never above 1%/trade or below 1.5R). Comparison/paper uses independent virtual books. MT5 netting fail-closes fake same-symbol independence; hedging allows it.
- [x] **Git hygiene:** secrets stripped from VPS helpers; ephemeral `_vps_skip_audit*` gitignored; durable `_vps_api_status.ps1` + `docs/VPS_TROUBLESHOOTING_FA.md` + `AGENTS.md`; finished work lands on `main`
- [x] **News ATR straddle:** selectable `news_straddle` strategy — pause scalp 2m before high-impact (NFP/CPI/FOMC), place ATR BUY_STOP/SELL_STOP ~30s prior with spread shield, OCO cancel of the twin pending, 120s expiry; Broker pending APIs on MT5/paper (OANDA not supported); panel + Telegram toggles; volume via 1% risk sizing (R:R 2.25)
- [x] **Telegram settings menu-only:** symbols/strategies/hours/risk/live-confirm chosen via reply-keyboard toggles (no typing); credential wizards remain for MT5/OANDA secrets only
- [x] **Daily loss lock toggle:** `risk.daily_loss_limit_enabled` in settings + runtime overrides; Telegram/panel on/off + unlock-today restart (`broker_wizard.apply_daily_loss_limit_enabled`, `write_daily_reset_marker`)
- [x] **MistakeMemory + forensic accounting:** dollar-risk journal R, orphan/timestamp guards, `operational_max_lot` caps; deterministic learn-from-mistakes veto with Telegram risk on/off (`risk.mistake_memory`) — live still gated
- [x] **One-shot VPS deploy from laptop:** `scripts/deploy_vps_from_local.ps1` → SSH → `_vps_full_deploy.ps1` (pull `main`, restart panel/API/live bot/Telegram, clear sticky kill marker)
- [x] **News straddle safety:** OCO/expiry run even when kill/daily-loss blocks new entries; abort pendings on halt; dual-fill orphan close; cancel-fail → `oco_retry`; paper fills ≤1 stop/symbol; place gated by `max_concurrent`
- [x] **Full bot debug pass:** circuit breaker auto-untrips on clean tick; breakeven never widens after ATR trail; MT5 drops forming bar so bar-close gate = strategy `iloc[-1]`; daily loss seeded from live equity; `position_meta` persisted; bar gate not consumed on soft `place_order` failures; `bot_stdout.log` rotates at 50MB; `scripts/debug_healthcheck.py`
- [x] **Strategy attribution + Control API reports:** journal/MT5 comment strategy tags (`utils/strategy_tags.py`); API `/journal` `/positions` `/strategy-stats` `/kill` `/settings/*` for panel/Telegram ops
- [x] **Demo/Shadow safe runtime profile:** `config/runtime_overrides.demo_shadow.example.yaml` + typed validation (`config_overrides.py`); paper broker, 0.25% risk, london_ny, liquidity-only default — Telegram controls preserved (no `control.remote_can_*=false`)
- [x] **FX ultra-scalp bleed fix:** journal showed EURUSD/USDJPY ultra losses with 40–50 lot sizes; enforce hard 1.5 R:R (no 1.0 bypass), floor volume (never round up past risk), disable ultra on FX/gold/crypto majors via `disabled_symbols`, default strategies = SMC+liquidity only
- [x] **Low-trade-count diagnosis:** deployed `runtime_overrides.yaml` had drifted from the committed example and dropped `delta` from `enabled_strategies`, silently disabling the only strategy with positive OOS evidence. Live loop now logs an "Entry gate profile" + guard line at startup and warns when no strategy is enabled
- [x] **Honest override schema:** remaining inert keys (`max_trades_*_day`, `cooldown_after_loss_minutes`, weekly/monthly loss caps, `fail_closed_when_stale`, `single_instance`, slippage/overrun caps) stay in `UNENFORCED_OVERRIDE_KEYS`. **`risk.max_portfolio_heat_pct` is now enforced** (live 3%, cannot exceed daily loss; per-trade still ≤1%).
- [x] **Backtest/live parity disclosure:** `backtest.engine.LIVE_ONLY_GATES` lists guards the engine does not simulate (including live shared heat and MT5 netting). Comparison books process all candidates; SL-first when both stops sit in one bar; spread-median and per-strategy already-open **are** modelled.
- [x] **Independent multi-strategy kernel + `xau_vwap_pullback` (shadow-only):** no winner-takes-all; news heat reserved before place; fair batch risk; VWAP stop-pending; `live_ready` fail-closed on API/Telegram/Streamlit; pending heat restored after restart; comparison reconcile keeps virtual books; comparison paper tickets are namespaced and journal/meta/heat key by `(symbol, strategy)`; cancel keeps heat until broker drop; VWAP expiry is M1-bar based. Strategy stays `enabled: false` / `shadow_only: true` / `live_ready: false` — **not live-enabled**. Independent reviewer + security still required before merge. See `docs/STRATEGY_XAU_VWAP_PULLBACK.md`.
- [x] **MT5 connect churn:** `MT5Connector.connect()` is idempotent (`force=True` to rebuild). Each attempt calls `mt5.shutdown()` first, so repeated broker/panel/Telegram probes were tearing down the IPC link mid-fetch — visible as repeated `Connected to MT5 elapsed=0.0s` bursts
- [x] **Telegram trade-open copy:** Settings → اعلان معامله sends a fill message to a configurable chat (default `@taranomrashid`); ID changeable in-bot; recipient must Start the bot
- [ ] **Enforce or delete the INERT override keys:** decide per key whether to implement enforcement or drop it from the schema; until then they are documentation only
- [ ] **User action — live path:** Windows VPS + MT5 demo (Iran) *or* Netherlands Linux + OANDA; fill `.env`, run paper then gated live
- [ ] **User action — VPS disk:** prefer ≥40GB on Windows (20GB fills with OS+MT5); migrate if host cannot expand
- [ ] **User action — rotate exposed tokens:** if any API/MT5 password was ever pasted into scripts or chat, rotate `CHRONOSCALP_API_TOKEN` / MT5 demo password on the VPS `.env`
