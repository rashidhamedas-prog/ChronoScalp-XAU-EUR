# Roadmap

## Strategy Delta — implemented, validation pending

- [x] Explainable M15/M5 regime + M1 sweep/retest entry engine
- [x] Structure/ATR/spread-aware stop geometry and >=1.5R target floor
- [x] XAUUSD/EURUSD allowlist, unit tests, and operator documentation
- [x] Telegram menu toggle, runtime persistence, and status visibility
- [x] Streamlit panel strategy picker + unified `resolve_enabled_strategies` (incl. delta-only path)
- [x] **Symbol-owned catalogs:** operator picks symbols only. XAUUSD and EURUSD books are Delta + M1 scalp. Telegram/panel strategy picker removed. Overlay `enabled_strategies` is ignored while `derive_strategies_from_symbols` is true. 1%/1.5R/3% unchanged. S15 ultra mode stays off (`use_s15_trigger: false`).
- [x] **Catalog slim (2026-09-03):** live week 2026-08-27..09-03 on AUSCommercial-Demo
  showed M1 `ultra_scalp` as the bleeder (46 tickets, MT5 PnL **−$6,947**, WR 37%).
  Delta was the only bot book in profit (**+$510**, 7 tickets). Operator magic=0
  gold was burst scale-in (9 baskets, 8 winners, +$57k) during Iran 13:00–18:00 —
  not copyable at 1% risk (6–25 lots). Overlay had `always_on_24h` and
  `daily_loss_limit_enabled: false`. Live books are now **Delta + news straddle**.
  YAML calendar updated for NFP 2026-09-04 12:30 UTC (Finnhub 403 keeps YAML).
  London window extended to 13:00 local so operator's 13:00 Iran gold hour is
  not in the London/NY gap. 1%/1.5R/3% unchanged. Do not re-enable ultra_scalp
  or 24h hours without a new broker-native window that beats Delta.
- [x] Broker-native history on VPS AUSCommercial-Demo: `XAUUSD`/`EURUSD` M1/M5/M15 (~100k M1/M5; not LiteFinance `_o`) — see `docs/STRATEGY_RESEARCH.md`
- [x] Limited 45d baseline + 1.5× cost-stress (2026-08-12): XAUUSD survives (E[R]≈0.35, PF≈2.11); EURUSD fails (E[R]<0) — live still disabled
- [x] Applied evidence to config: EURUSD removed from active symbols; Delta gold-only (`allowed_symbols: [XAUUSD]`)
- [x] Live-loss forensics (2026-08-26): 267 journal trades, 23.2% win rate, −$31,724. Root causes fixed — ATR trailing stop engaged from entry instead of after 1R; spread guard used a mean baseline on a right-skewed distribution; `record_external_close` stored `exit_price = entry_price`, corrupting all exit-geometry analysis. See `.ai-dos/tasks/handoff.md` (TASK-003).
- [x] Delta stop geometry rebuilt: stops scale from a configurable higher-timeframe ATR (`stop_atr_source`/`stop_atr_htf_index`) instead of the M1 trigger bar, which measured narrower than one average M1 candle on both symbols; added `max_cost_fraction_of_risk` and per-symbol `symbol_overrides`
- [x] Re-ran baseline + 1.5× cost-stress on the new geometry over the identical 2026-06-27..2026-08-11 window (2026-08-29, bar-close engine): **XAUUSD** 50 trades, PF 1.942, E[R] +0.358, maxDD 7.94%, +9.44% (1.5× cost → PF 1.940); **EURUSD** 4 trades, PF 0.00, E[R] **−1.00**, −2.03%. Per-trade gold edge is unchanged versus pre-fix (+0.354R); the return halved because wider stops mean smaller lots at the same 1% risk. EURUSD produced four full stop-outs and nothing else — no measurable edge, not live-eligible.
- [x] Closed the stop-management half of the backtest↔live parity gap: `backtest/engine.py` walks each bar as monotonic legs (`intrabar_stop_management`, adverse-first OHLC path) so a stop trailed mid-bar is reachable by the pullback in that same bar, as it is live at a 2–5s poll. `_advance_stop` applies breakeven *and* trailing per waypoint. Engine now also applies `spread_ma_guard`, `volatility_guard`, `three_strikes`, and a bar-time `daily_loss_limit` (`model_live_gates`); `RiskManager.validate_signal` takes `at` — without it the daily tracker rolled over against wall-clock and never fired on history. Summaries carry `stop_management`. `LIVE_ONLY_GATES` is down to the seven needing live account/cross-symbol state.
- [x] Re-ran both symbols on the parity engine (2026-08-29, same window): **XAUUSD** 48 trades, WR **62.5%**, PF 1.754, E[R] +0.284, maxDD 6.14%, +7.0%; PF 1.751 at 1.5× costs. **EURUSD** unchanged at 4 trades / E[R] −1.00 — all four hit their initial stop before reaching 1R, so intrabar trailing never engaged. The gold win-rate rise with a lower expectancy is the live signature reproduced: the trail now closes more trades early at small profits instead of letting them reach full TP. The edge survives a realistic engine and 1.5× costs, which is the first defensible positive evidence Delta has had.
- [x] Per-symbol validation verdicts are machine-readable (`strategy.delta.symbol_validation`) and surfaced by the live-loop startup log and Telegram `/status` (`strategy/live_gates.py`: `symbol_validation_state`, `unvalidated_live_symbols`). Reported, never enforced — enabling an unvalidated symbol stays the operator's call, but it can no longer happen unknowingly. Telegram `/status` also shows the loaded trailing gate, spread-guard baseline, and Delta stop-ATR source, so a restart can be confirmed to have picked up the fixes.
- [x] Deployed to the VPS and verified from the running process, not from git: the live log prints `Stop geometry: trailing_start=1.0R trailing_atr=1.5 delta_stop_atr_source=htf(M5) spread_ma_multiplier=2.5`. Two deploy defects were fixed on the way — `_vps_full_deploy.ps1` used to leave the bot down whenever `stop_bot()` timed out (the `bot.stopped` marker survived and `watch_bot.ps1` honours it), and the Streamlit panel had no watchdog so it died with every SSH session. `-KeepHalt` now separates shipping code from resuming live risk.
- [x] **Operator style (2026-09-04):** magic=0 gold bursts (7/14d, 86% basket
  WR, Iran 13:00–18:00) always had M15 ADX ≥ 22. Big SELL baskets faded
  RSI/Stoch spikes; BUY baskets were M5 pullbacks in an HTF uptrend. Encoded
  as ADX + Stochastic on Delta (gold: fade/pullback + existing sweep; EUR:
  fade/pullback only — not the failed sweep path). Gold TP sits at the 1.5R
  floor. 1%/3% and lot scale-in unchanged. 75% ticket WR is **not claimed**.
- [ ] Longer-horizon WF / denser OOS for XAUUSD; **EURUSD strategy redesign**
- [ ] Cost-stressed Monte Carlo analysis and 100+ demo trades per symbol
- [ ] Recalibrate the shared `rvol >= 1.50` gate in `strategy/entry_trigger.py` — dominant rejection reason for both symbols; instrument accepted bars before changing it
- [ ] Investigate BTCUSD/ETHUSD: 83 journal trades with **zero** wins plus 4,883 `no_trigger_data` skips — broken, not merely unprofitable
- [ ] Make `scripts/_vps_full_deploy.ps1` respect an existing `STOP_TRADING` marker (it currently deletes it, resuming live trading as the final deploy step); use `scripts/_vps_safe_code_update.ps1` until then
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
- [x] **Independent multi-strategy kernel + `xau_vwap_pullback` (operator live 2026-08-23):** no winner-takes-all; news heat reserved before place; fair batch risk (News in the same tick); VWAP stop-pending; pending heat restored after restart; News OCO reconstructed or leftover pending cancelled+verified; comparison books isolate max_concurrent / daily DD / Three-Strikes; Telegram RequestException logs omit URL/token. Config is `enabled: true` / `shadow_only: false` / `live_ready: true` after explicit operator confirmation. 1%/1.5R/3% heat unchanged. See `docs/STRATEGY_XAU_VWAP_PULLBACK.md`.
- [x] **MT5 connect churn:** `MT5Connector.connect()` is idempotent (`force=True` to rebuild). Each attempt calls `mt5.shutdown()` first, so repeated broker/panel/Telegram probes were tearing down the IPC link mid-fetch — visible as repeated `Connected to MT5 elapsed=0.0s` bursts
- [x] **Telegram trade-open copy:** Settings → اعلان معامله sends a fill message to a configurable chat (default `@taranomrashid`); ID changeable in-bot; recipient must Start the bot
- [x] **Live mode ignores overlay `broker: paper`:** `--mode live` used to instantiate PaperBroker when `runtime_overrides.yaml` left `execution.broker: paper` (demo leftover), so confirmed live filled nothing on MT5. Live now infers MT5/OANDA from `data_source`. Skip heartbeat records engine skip reasons (`delta:low_rvol`, …) instead of a blank `no_signal`. 1%/1.5R/3% and `CHRONOSCALP_CONFIRM_LIVE` unchanged.
- [x] **Persian HTML performance report:** `scripts/generate_performance_report.py` + `reports/performance_report.py` — strategy/session/hour/symbol breakdown, recommendations; optional `--import-mt5` on Windows VPS rebuilds closed trades from MT5 deal history, which is the only way to recover a real `exit_price` for the 255 externally-closed trades the journal recorded at entry price. Two competing implementations existed on separate branches; this one was kept and `cursor/account-performance-report-6620` / `cursor/performance-report-55625500-c139` were dropped rather than merged into duplicate modules.
- [ ] **Enforce or delete the INERT override keys:** decide per key whether to implement enforcement or drop it from the schema; until then they are documentation only
- [ ] **User action — live path:** Windows VPS + MT5 demo (Iran) *or* Netherlands Linux + OANDA; fill `.env`, run paper then gated live
- [ ] **User action — VPS disk:** prefer ≥40GB on Windows (20GB fills with OS+MT5); migrate if host cannot expand
- [ ] **User action — rotate exposed tokens:** if any API/MT5 password was ever pasted into scripts or chat, rotate `CHRONOSCALP_API_TOKEN` / MT5 demo password on the VPS `.env`
