# Handoff Log

Append newest entries at the top. Never erase another agent's record.

## 2026-08-26 TASK-003 three live-loss root causes fixed; entries halted

- Time (UTC): 2026-08-26T13:40:00Z
- Task / owner / role: TASK-003 / cursor:claude-opus-5 / architect+implementer
- Objective: operator reported that every trade since 2026-08-25 closed at a loss,
  and asked why EURUSD barely trades. Find root causes, fix them, keep risk intact.

### Claim reclaim notice (per AGENTS.md ownership rules)

Reclaimed stale claims. Previous owners are notified here:

- **TASK-001** (`cursor:grok-4.5`, heartbeat `2026-08-17T12:00:00Z`, 9 days stale):
  `src/chronoscalp/strategy/delta.py`, `tests/test_delta_strategy.py`,
  `tests/test_trade_journal.py`.
- **TASK-002** (`cursor:grok-4.6`, heartbeat `2026-08-25T12:05:00Z`, >24h stale per
  `.ai-dos/ai-dos.yaml` `stale_claim_hours: 24`): `config/settings.yaml`,
  `src/chronoscalp/risk/position_sizing.py`,
  `src/chronoscalp/orchestration/trade_journal.py`,
  `src/chronoscalp/execution/mt5_broker.py`, `src/chronoscalp/main.py`,
  `tests/test_risk.py`, `tests/test_execution_utils.py`.
- Previously unclaimed: `src/chronoscalp/risk/institutional_guards.py`,
  `src/chronoscalp/execution/mt5_utils.py`, `tests/test_institutional_v3.py`.

This directly continues TASK-002's own recorded next action ("review the
spread-guard multiplier with fresh evidence before touching it") — the evidence
is below.

### Live state

Entries are **halted** on the VPS: `STOP_TRADING` kill-switch marker created via
`scripts/_vps_halt_entries.ps1`; `MARKER_EXISTS=True`, `open_positions 0` at
2026-08-26T13:05Z. Do not clear the marker until the validation below passes.

### Evidence (VPS `45.90.98.99`, artifacts under `data/_analysis/`)

Journal, 267 closed trades — `vps_journal_stats.txt`:

| Split | n | win% | net PnL | PF |
|---|---|---|---|---|
| all | 267 | 23.2 | -31,724 | 0.65 |
| `ultra_scalp` | 97 | 32.0 | -24,428 | 0.60 |
| `delta` | 22 | 22.7 | -3,981 | 0.36 |
| USDJPY | 27 | 18.5 | -18,498 | 0.24 |
| EURUSD | 53 | 28.3 | -6,549 | 0.73 |
| XAUUSD | 83 | 42.2 | -5,228 | 0.87 |
| BTCUSD | 33 | **0.0** | -681 | 0.00 |
| ETHUSD | 50 | **0.0** | -632 | 0.00 |

- 255 of 267 closes are `exit_reason=external`; median losing hold time 1.1 min.
- Live ATR/spread probe (`vps_atr_probe.txt`, 2026-08-26): XAUUSD M1 ATR $1.573
  vs **median M1 bar range $1.495**, and the old Delta stop band was
  $1.258–$3.932. EURUSD M1 ATR 0.94 pip vs median bar range 0.90 pip, band
  0.75–2.34 pip. **The minimum permitted stop was narrower than one average
  M1 candle on both symbols.**
- Aggregated entry-skip heartbeats (488 heartbeats): `XAUUSD:spread_ma` 3571,
  `EURUSD:spread_ma` 929, `EURUSD:delta:regime_neutral` 577,
  `XAUUSD:delta:regime_neutral` 539, `XAUUSD:delta:low_rvol` 352,
  `EURUSD:delta:low_rvol` 244, `BTCUSD:no_trigger_data` 4883,
  `*:news_straddle_place_blocked` 5914/5914/4883.

### Root causes fixed

1. **`RiskManager.trailing_stop` trailed from the moment of entry.** No profit
   precondition existed, so `current_price - 1.5*ATR` replaced any structural
   stop wider than `1.5*ATR` immediately. Live polls every 2–5s
   (`execution.poll_interval_seconds`), while `backtest/engine.py` calls
   `apply_breakeven_or_trailing` **once per bar, on the bar close, after**
   `check_sl_tp_hit`. That is a ~30x difference in how hard the bug bites, and
   it explains why the XAUUSD backtest reads +17.08% (`validate_XAUUSD_last45d.json`)
   while live gold is -$5,228. Fix: `trailing_start_r_multiple` (default 1.0),
   R measured from `initial_stop_loss`.
2. **`SpreadMovingAverageGuard` used a mean baseline with a 1.2 multiplier.**
   Spread samples are right-skewed, so news spikes lifted the mean and normal
   quotes were rejected (live: `EURUSD spread guard: 0.30 > MA0.11*1.20`). Fix:
   median baseline, multiplier 2.5. Now blocks genuine blow-outs only.
3. **`TradeJournal.record_external_close` stored `exit_price = entry_price`.**
   Every externally closed row therefore read as zero price excursion, making
   all exit-geometry analysis silently meaningless. Fix: real broker fill via
   `mt5_utils.closing_deal_exit_price` (volume-weighted `DEAL_ENTRY_OUT` legs),
   plumbed through `MT5Broker.fetch_closed_exit_price` and
   `main._on_position_closed_externally`; unknown exits are now flagged
   `exit_price_unknown` instead of faked. `r_multiple` was already PnL-derived
   and is unaffected.

### Delta geometry redesign

- `stop_atr_source: htf` + `stop_atr_htf_index` scale the stop off a higher
  timeframe instead of the M1 trigger bar (`higher_trend` is `["M15","M5"]`, so
  index 1 = M5). `stop_buffer_atr` now scales off the same reference ATR.
- `max_cost_fraction_of_risk: 0.15` forces round-trip spread to stay a minor
  share of risk; a setup whose cost floor cannot fit under `max_stop_atr` is
  rejected with the new reason `cost_exceeds_stop_cap`.
- `symbol_overrides` block: XAUUSD `min/max_stop_atr 0.80/2.00`; EURUSD
  `1.50/3.50` with `reward_risk_ratio 2.00`. Per-symbol tuning was impossible
  before — one band had to fit both a dollar-quoted metal and a 5-digit FX pair.
- Risk ceilings untouched: 1% per trade, 3% heat, `rr = max(1.5, ...)` floor,
  `CHRONOSCALP_CONFIRM_LIVE` unchanged. Wider stops **reduce** lot size via
  `calculate_position_size`, they do not raise risk.

### Per-strategy EURUSD verdict (operator's question)

The deployed VPS overlay is **not** the repo's `config/runtime_overrides.yaml`.
VPS runs `symbols=[XAUUSD,EURUSD]` with `delta.allowed_symbols` including
EURUSD; the repo file lists `[BTCUSD, ETHUSD, XAUUSD_o, USDJPY_o, EURJPY_o]`
and `delta.allowed_symbols: [XAUUSD]`. Keep that divergence in mind.

| Strategy | Evaluates EURUSD? | Dominant blocker |
|---|---|---|
| `delta` | yes (overlay) | `regime_neutral` 577, `low_rvol` 244 |
| `smc_confluence` | yes | `low_rvol`, `trend_neutral`, `no_liquidity_sweep` |
| `liquidity_volume` | yes | `low_rvol`, `trend_neutral` |
| `xau_vwap_pullback` | **no** | `symbol_blocked` — `allowed_symbols: [XAUUSD]` by design |
| `ultra_scalp` | disabled | `use_ultra_scalp: false` in overlay |
| `news_straddle` | n/a | `news_straddle_place_blocked` (Finnhub 403, no feed) |

So only `xau_vwap_pullback` hard-blocks EURUSD, and that is intentional for a
gold VWAP strategy. Everywhere else EURUSD is evaluated and rejected by the
shared `rvol >= 1.50` gate in `strategy/entry_trigger.py`.

### Tests/gates (this session, actual)

- `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_task003` → exit 0,
  378 passed.
- `.venv\Scripts\python.exe -m ruff check src tests` → All checks passed!
- `.venv\Scripts\python.exe -m black --check src tests` → 2 files would be
  reformatted: `src/chronoscalp/strategy/live_gates.py` and
  `tests/test_analyze_spread_guard.py`. **Both pre-existing on `main`** (verified
  by stashing this branch's changes and re-running). Neither is touched by this
  task, so they were left alone rather than reformatted as unrelated churn.
- New regression tests: 5 in `tests/test_risk.py` (trailing profit gate,
  sell-side, R-from-initial-stop, opt-out at 0), 3 in `tests/test_institutional_v3.py`
  (median baseline vs skew), 7 in `tests/test_delta_strategy.py` (trigger-ATR
  anchoring rejects normal structure, HTF anchoring accepts it, cost floor, cost
  cap rejection, EURUSD override, config merge, ATR fallbacks), 3 in
  `tests/test_trade_journal.py` (real exit price, unknown flagged, non-positive
  rejected), 4 in `tests/test_execution_utils.py` (fresh position untouched,
  deal parsing incl. partial closes).

### Open items — none of this is validated for live money yet

1. **Required before clearing the kill switch**: broker-native backtest with real
   costs + walk-forward on XAUUSD *and* EURUSD using the new geometry
   (`scripts/run_cost_stress_validate.py`, `scripts/_vps_limited_walkforward.ps1`).
   The prior EURUSD rejection (`validate_EURUSD_last45d.json`: 17 trades, PF 0.591,
   expectancy -0.15R; `wf_limited_EURUSD.json`: 5 OOS trades, all losers) was
   measured with M1-ATR stops and the unconditional trail, so it does **not**
   carry over — but it is not evidence in favour either. `allowed_symbols` in
   `config/settings.yaml` deliberately still reads `[XAUUSD]`.
2. **The backtest does not model the live gates it needs to.** `spread_ma_guard`,
   `volatility_guard`, `three_strikes`, `mistake_memory` are all in
   `LIVE_ONLY_GATES`, and trailing is sampled once per bar instead of every
   2–5s. Until that gap closes, a positive backtest cannot clear a strategy for
   live. This is the highest-value follow-up.
3. **`rvol >= 1.50` in `strategy/entry_trigger.py` is untouched and suspect.**
   151 logged rejections span rvol 0.19–1.49 (median 0.94). The sample contains
   only rejections so it cannot yield a pass rate — instrument accepted bars
   before changing the threshold.
4. **BTCUSD/ETHUSD: 83 trades, 0 wins**, alongside `BTCUSD:no_trigger_data` 4883.
   Broker symbol is `BTCUSD.ca` on `AUSCommercial-Demo`. Crypto handling is
   broken, not merely unprofitable — investigate separately.
5. **`ultra_scalp` is -$24,428 of the -$31,724 total** (77%). It is disabled in
   the current overlay; keep it disabled until it is re-validated.
6. `partial_tp` rows record `pnl=0.00` for all 11 occurrences — journal
   accounting gap, separate from the exit-price fix.

### Deployment hazard — do NOT use the standard deploy while entries are halted

`scripts/_vps_full_deploy.ps1` line 47 deletes `data/state/STOP_TRADING`, i.e.
the deploy **clears the kill switch and resumes live trading** as its final
step, and it also restarts the live bot. Neither is wanted before validation.
Making the deploy respect a pre-existing kill switch is a prerequisite for the
next live deploy.

The overlay is **not** at risk from `git reset --hard`:
`config/runtime_overrides.yaml` is gitignored (`.gitignore:52`) and untracked on
the VPS (`git ls-files` empty), verified 2026-08-26 by
`scripts/_vps_probe_procs_and_overlay.ps1`. An earlier version of this entry
claimed the file was tracked; that was wrong. The overlay divergence is still
worth knowing about — VPS runs `symbols=[XAUUSD,EURUSD]`, `enabled_strategies=
[delta, liquidity_volume, xau_vwap_pullback]`, `delta.allowed_symbols=
[XAUUSD, EURUSD]`, `xau_vwap_pullback.shadow_only=true`,
`sessions=always_on_24h`, `daily_loss_limit_enabled=false` — but it survives a
reset because it is ignored, not because the deploy protects it.

Also verified: the apparent duplicate `run_live.py` processes are **one** logical
bot. PID 3220 (`Program Files\Python312\python.exe`) is a child of PID 1640
(`.venv\Scripts\python.exe`) — the venv launcher spawns the base interpreter.
Same pattern for the API and Telegram processes. There is no double-order risk.

### Exact next action

1. Ship the fixes to the VPS working copy **without** `_vps_full_deploy.ps1`,
   preserving `config/runtime_overrides.yaml` and the `STOP_TRADING` marker.
2. Run `scripts/_vps_detach_cost_stress.ps1` (wraps
   `run_cost_stress_validate.py --symbols XAUUSD EURUSD --last-days 45`) and
   `scripts/_vps_detach_limited_wf.ps1`, then compare against the pre-fix
   baselines above (XAUUSD PF 2.114 / +0.354R; EURUSD PF 0.591 / -0.15R).
3. Only then decide whether EURUSD joins `allowed_symbols`, and only then clear
   `STOP_TRADING`.

## 2026-08-25 TASK-002 watchdog was killing the live bot every ~7 minutes

- Time (UTC): 2026-08-25T12:05:00Z
- Task / owner / role: TASK-002 / cursor:opus-5 / implementer
- Objective: operator reported no trades opened since 2026-08-24. Find and fix the cause.
- Root cause (VPS `45.90.98.99`, evidence in `logs/bot_watchdog.log` + `logs/chronoscalp_2026-08-25.log`):
  - `watch_bot.ps1` treated `terminal64` **working set** `< 30 MB` as a hollow terminal. Windows trims the working set of an idle background terminal to ~20–28 MB within ~6 minutes, so a fully loaded MT5 looked hollow on a fixed cycle.
  - Recycling MT5 severed the running bot's IPC link. The bot logged `Connecting to MT5`, and the `stuckConnect` check (last 20 log lines contain `Connecting to MT5` and not `ChronoScalp started`) then killed the healthy bot **in the same watchdog run**.
  - Counts: 33 `recycling hollow` and 33 `kill hung MT5 connect` on 2026-08-25 up to 03:55; 137 `ChronoScalp started` lines on 2026-08-24. Bot lifetime was capped at ~7 minutes, so no strategy held enough rolling state (spread median/MA, structure, pendings) to reach an entry. Last journal trade: 2026-08-21.
  - Secondary noise: overlay symbol `BTCUSD` does not exist on `AUSCommercial-Demo` (broker name is `BTCUSD.ca`), producing per-minute `symbol unavailable` + `Empty BTCUSD Mx — reconnect + retry` bursts.
- Product changes:
  - `scripts/watch_bot.ps1`: health reads **private bytes** (not trimmed by Windows); MT5 is recycled only on evidence (no process, unresolved IPC failure in the log, or hollow while no bot runs); terminals younger than 300s are never recycled; `Test-LiveConnectHung` requires no `Connected to MT5|ChronoScalp started|MT5 connect exhausted retries` after the last `Connecting to MT5`; no hang verdict in a run that just recycled MT5.
  - `src/chronoscalp/saas/process_control.py`: `terminal64_working_set_mb` → `terminal64_private_mb`, `HOLLOW_MT5_WS_MB` → `HOLLOW_MT5_PRIVATE_MB = 20.0`, `min_ws_mb` → `min_private_mb`, messages report `priv_mb`.
  - VPS overlay: `BTCUSD` dropped from `symbols` via `scripts/_vps_drop_unavailable_symbol.py` (gitignored local helper); backup `config/runtime_overrides.yaml.bak-20260825T113339Z` kept on the VPS.
- Tests/gates (this session, actual):
  - `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_watchdog_full` → exit 0 (full suite)
  - `.venv\Scripts\python.exe -m ruff check src tests scripts/_vps_drop_unavailable_symbol.py` → All checks passed!
  - `.venv\Scripts\python.exe -m black --check` on `process_control.py`, `test_process_control.py`, `_vps_drop_unavailable_symbol.py` → 3 files unchanged
  - New regression test `test_terminal64_health_reads_private_bytes_not_working_set` pins the metric.
- VPS verification (05:00 local / 12:00 UTC): HEAD `29463ec` on `main`; bot pid 2672 uptime 22.2 min with 22 consecutive `already running` watchdog runs and zero recycles/kills; MT5 `ws_mb=6.4` while `priv_mb=49.3` and quotes flowing — the old rule would have killed that terminal instantly; `btc_warnings=0` since restart.
- Invariants: 1% per trade / 1.5 R:R / 3% heat and `CHRONOSCALP_CONFIRM_LIVE` untouched. No strategy or risk logic changed.
- Open items: Finnhub calendar returns HTTP 403, so `news_straddle` has no event feed and logs `news_straddle_place_blocked` every tick. `XAUUSD:spread_ma` still blocks 3–6 ticks per 5 min — re-assess now that the spread MA is built from an uninterrupted session rather than a 7-minute window. `debug-ece9a8.log` instrumentation is still enabled.
- Exact next action: watch a full London/NY session for the first live entry; if `spread_ma` dominates the skip heartbeat over a full session, review the spread-guard multiplier with fresh evidence before touching it.

## 2026-08-24 TASK-002 deployed ccff6ea live+Telegram on VPS

- Time (UTC): 2026-08-24T21:25:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer
- VPS `45.90.98.99` HEAD=`ccff6ea` (feature commit; VPS local `main` pointer moved to that SHA — do not run `_vps_full_deploy.ps1` until merge to origin/main or it will roll back).
- Overlay: kept broker-native `XAUUSD/EURUSD/BTCUSD`, `always_on_24h`, chat `1008770451`, news_straddle on; added `smc_confluence`; heat 3%.
- Live: `ChronoScalp started in live mode` `broker_class=MT5Broker` `Connected AUSCommercial-Demo` equity≈71029. Telegram restarted, keyboard restored. Duplicate PID pairs are venv launcher + Python312 child, not two bots.
- Exact next action: leave VPS running; merge to origin/main before the next standard deploy.

## 2026-08-24 TASK-002 live open path: overlay paper + stripped strategies

- Time (UTC): 2026-08-24T16:30:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer
- Evidence: merged local overlay had `execution.broker: paper`, `enabled_strategies: [delta, liquidity_volume]`, `max_concurrent: 1`; `create_broker(mode=live)` returned PaperBroker; session `in_session=false` at 16:17 UTC.
- Product: live mode ignores overlay `broker: paper` and uses MT5/OANDA from data_source; skip heartbeat records engine skip reasons; local gitignored overlay restored to SMC+liq+delta+VWAP, MT5, 3% heat, independent symbols. Session still london_ny (NY 13:30–16:30 New York).
- Unchanged: 1%/1.5R/3%, `CHRONOSCALP_CONFIRM_LIVE`.
- Exact next action: restart live bot so overlay + create_broker take effect; deploy VPS; independent review still required before merge.

## 2026-08-24 TASK-002 hollow MT5 relapsed; live loop restored

- Time (UTC): 2026-08-24T15:35:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer
- Evidence: from 03:00 PDT the live loop died; `terminal64` WS≈7MB; watchdog restart-loop + IPC `-10005`. Operator asked to fix.
- Ops: killed hollow terminal + `run_live`; after clearing `bot.stopped`, watchdog started live; `initialize` launched a loaded terminal (WS≈119MB, session 0); `Connected ... elapsed=12.2s`; `ChronoScalp started in live mode` at 08:33:30 PDT.
- Product: `watch_bot.ps1` recycles hollow/missing MT5 (best-effort) and kills hung connect by process age ≥90s; `process_control.ensure_mt5_terminal` same recycle; live start warns but still spawns so initialize can launch the terminal. Deployed `watch_bot.ps1` to VPS. Reclaimed stale TASK-001 `tests/test_process_control.py`.
- Tests: `pytest tests/test_process_control.py` 11 passed; ruff+black on touched Python files.
- Invariants: 1%/1.5R/3% and `CHRONOSCALP_CONFIRM_LIVE` unchanged.
- Exact next action: keep an RDP session disconnected (not logged off) so MT5 does not go hollow again; merge still needs independent review.

## 2026-08-24 TASK-002 VPS MT5 IPC recovered + Telegram unblocked

- Time (UTC): 2026-08-24T09:37:00Z
- Telegram: Positions no longer calls `mt5.initialize` (poll hang). Keyboard restore sent to chat `1008770451`.
- Trading: zombie `terminal64` (~6MB) killed; new terminal WS≈118MB; `Connected to MT5 server=AUSCommercial-Demo` elapsed=0.0s; `ChronoScalp started in live mode`; tick running (EURUSD low_rvol skip).
- Invariants: 1%/1.5R/3% and `CHRONOSCALP_CONFIRM_LIVE` unchanged. Debug instrumentation still on (`debug-ece9a8.log`) until operator confirms Positions/Logs.
- Exact next action: operator presses Positions then Logs; then strip debug logs.


- Time (UTC): 2026-08-24T09:22:00Z
- Evidence (`debug-ece9a8.log` from VPS): status `handle` then open `handle`, then Telegram `mt5.initialize` — no `_cmd_open` finish, no logs `handle`. Live IPC timeout `-10005` ~211s.
- Fix: Telegram Positions/Logs/Test-conn no longer call `mt5.initialize`; snapshot/journal + log tail from end. MT5 connect stops retrying after IPC timeout. Watchdog kills hung connect after 4 min without `ChronoScalp started`.
- Instrumentation kept (`runId=post-fix`).
- Exact next action: deploy files, restart Telegram, operator presses Positions then Logs.


- Time (UTC): 2026-08-24T08:55:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Objective: diagnose operator report that Telegram control and ChronoScalp live bots "don't work".
- Reclaimed from stale TASK-001 (heartbeat 2026-08-17): `mt5_connector.py`, `process_control.py`. Also claimed `logging_setup.py`.
- VPS evidence (45.90.98.99, HEAD `fbb16fc` on `main`, local VPS clock ~01:47):
  - `run_live.py --mode live` alive but looping MT5 `initialize()` IPC timeout `-10005` (~211–218s per attempt). Watchdog treats it as healthy after 12s.
  - `terminal64` PID 2396 WS≈7.5MB (hollow vs a normal loaded terminal).
  - Telegram control bot up since 2026-08-23 06:54; poll errors logged only as `RequestException` (status stripped). Operator cmds at 21:38–21:58: status / positions / stop / start live / positions.
  - Overlay already uses numeric `trade_open_copy_chat_id=1008770451`.
- Hypotheses under test (debug session ece9a8): A MT5 IPC hang; B watchdog false-healthy; C poll error stripped; D Telegram positions blocks poll via second MT5 initialize; E Markdown/`@username` sendMessage 400.
- Instrumentation only — no product fix yet. Debug NDJSON: repo-root `debug-ece9a8.log`.
- Exact next action: operator reproduces via Telegram; then analyze `debug-ece9a8.log` (VPS + local) and fix with evidence.

## 2026-08-23 TASK-002 operator confirmed merge/deploy/VWAP live

- Time (UTC): 2026-08-23T13:20:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Operator confirmation: Merge, Deploy, live-enable VWAP.
- Product: `config/settings.yaml` sets `xau_vwap_pullback` `enabled: true`, `shadow_only: false`, `live_ready: true`, and lists it on `enabled_strategies`. `apply_enabled_strategies` copies `live_ready` from committed settings.yaml so Telegram/API save cannot drop the gate to false. Fail-closed path remains when `live_ready` is false.
- Unchanged: 1%/1.5R/3% heat, `CHRONOSCALP_CONFIRM_LIVE`.
- Exact next action: pytest/ruff/black, commit, merge to main, deploy VPS, confirm overlay.

## 2026-08-23 TASK-002 pin fair-batch test (finding 4)

- Time (UTC): 2026-08-23T12:55:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Why: independent functional review of `378a5e5` marked findings 1–3, 5–6 closed but finding 4's test residual — `dollar_risk=50` would still pass if News were omitted from `n`.
- Test change only: `test_tick_news_and_delta_share_batch_when_heat_tight` now spies `allocate_batch_risk_pct(n=…)`, requires `n==2`, and sizes News from `risk_pct` so a 1.5% remainder must split to 0.75% / $75. Omitting News from the batch would yield `n==1` and 1.0% / $100.
- Gates: `pytest tests/test_trading_bot_multistrat.py::test_tick_news_and_delta_share_batch_when_heat_tight` passed; ruff+black clean on that file.
- Exact next action: re-review finding 4. **Do not merge. Do not deploy. VWAP stays shadow.**

## 2026-08-23 TASK-002 independent-review fixes (do not merge)

- Time (UTC): 2026-08-23T12:35:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer (reviewer/security remain distinct)
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Objective: close the six independent-review findings without merge, deploy, or live-enabling VWAP.
- Product changes:
  1. `_restore_pending_heat_reservations` harvests fills before overwriting reservations, then merges so heat never shrinks (in-flight fill keeps prior; open + leftover pending keeps leftover; `max(prior, rebuilt)`). `_open_dollar_risks` still counts leftover live pendings even when a position already exists.
  2. `_recover_news_oco_from_broker` reconstructs News OCO after restart, or fail-closed cancels the leftover opposite pending and re-lists to verify. Open + leftover pending both stay in heat until cancel is confirmed.
  3. Comparison mode: `_at_capacity(strategy)`, per-book `DailyDrawdownGuard`, and Three-Strikes are isolated per strategy book. Hitting daily DD closes that book only.
  4. Same-tick News joins `allocate_batch_risk_pct` with other ready signals so remaining heat is split fairly (code order is not the winner).
  5. Telegram `RequestException` is logged via `telegram_error_summary` (type + optional status only). Token/URL are stripped before re-raise; poll/send do not interpolate the request URL.
- Tests (via `TradingBot.tick` except Telegram `run_forever` poll):
  - `test_tick_pending_fill_between_reconciles_keeps_heat`
  - `test_tick_restart_news_oco_cancels_leftover_or_counts_both`
  - `test_tick_comparison_limits_are_per_book`
  - `test_tick_comparison_daily_dd_is_per_book`
  - `test_tick_news_and_delta_share_batch_when_heat_tight`
  - `test_telegram_poll_error_omits_token`
- Tests/gates (this session, actual):
  - `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_task002` → exit 0 (full suite)
  - `.venv\Scripts\python.exe -m ruff check src tests scripts/app.py` → All checks passed!
  - `.venv\Scripts\python.exe -m black --check` on `src/chronoscalp/main.py`, `src/chronoscalp/risk/institutional_guards.py`, `src/chronoscalp/telegram/control_bot.py`, `src/chronoscalp/orchestration/alerts.py`, `tests/test_trading_bot_multistrat.py`, `tests/test_telegram_control_bot.py` → 6 files would be left unchanged
- Invariants: 1%/1.5R/3% intact; `CHRONOSCALP_CONFIRM_LIVE` untouched; `xau_vwap_pullback` still `live_ready: false` / `shadow_only: true`.
- Exact next action: independent functional + security review (distinct from implementer). **Do not merge. Do not deploy. Do not live-enable VWAP.**

## 2026-08-23 TASK-002 Bugbot follow-up: comparison ticket collision

- Time (UTC): 2026-08-23T11:15:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer (reviewer/security remain distinct)
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Finding closed: [Bugbot](1a3f5f30-0524-4857-bd14-da9f8ed030cf) high — paper comparison books all started at ticket 1, so shared journal/meta/heat maps keyed by bare ticket collided.
- Product changes:
  - Each comparison `PaperBroker` gets a disjoint `first_ticket` origin (1, 1_000_001, …).
  - `_position_meta` is stored under `(symbol, strategy)` with a ticket alias only when that ticket is unique to the strategy.
  - `TradeJournal.open_trades` uses composite keys; int lookup remains for unique-ticket unit tests.
  - Heat reconstruction and force-close/unrealized PnL resolve the book via `_broker_for(strategy)`.
- Tests/gates (this session, actual):
  - `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_task002_tickets_full` → passed
  - `.venv\Scripts\python.exe -m ruff check src tests scripts/app.py` → All checks passed!
  - `.venv\Scripts\python.exe -m black --check` on touched files → clean
- Invariants: 1%/1.5R/3% intact; `CHRONOSCALP_CONFIRM_LIVE` untouched; `live_ready` still false.
- Exact next action: independent functional review of this follow-up + `44b62a2`. **Do not merge. Do not live-enable VWAP.**

## 2026-08-23 TASK-002 independent security: restart-heat medium closed

- Time (UTC): 2026-08-23T10:50:00Z
- Task / owner / role: TASK-002 / independent security (distinct from implementer)
- Branch: `ai/TASK-002-xau-vwap-multistrat` @ `5f6672f` (later `44b62a2` still on the branch)
- Finding: prior medium (pending heat lost after restart) is **closed**. No new medium+ security issues in that diff. `xau_vwap_pullback` still cannot live-enable via API/Telegram/Streamlit while `live_ready: false`.
- Residual (below medium): magic-filtered MT5 pendings with empty/non-`CS_` comments are skipped rather than fail-closed.
- Process: security no longer blocks on restart-heat. **Do not merge** until independent functional review of `44b62a2`. **Do not live-enable VWAP.**

## 2026-08-23 TASK-002 bugbot follow-up: comparison reconcile, cancel heat, VWAP M1 expiry

- Time (UTC): 2026-08-23T10:45:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer (reviewer/security remain distinct)
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Objective: close [Bugbot](8b0c1f17-3636-4f43-945d-bd2b77136098) highs/medium without live-enabling VWAP.
- Product changes:
  - `_reconcile_state_with_broker` loads positions from comparison books and matches by `(symbol, strategy)` so virtual fills are not dropped.
  - `_cancel_strategy_pendings` keeps heat reserved until re-list shows no leftover (then harvest, then release).
  - VWAP `bars_left` decrements only when the last M1 timestamp changes, not on every poll.
- Tests/gates (this session, actual):
  - `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_task002_bugbot` → all passed
  - `.venv\Scripts\python.exe -m ruff check src tests scripts/app.py` → All checks passed!
  - `black --check` on touched files after format → clean
- Invariants: 1%/1.5R/3% intact; `CHRONOSCALP_CONFIRM_LIVE` untouched; `live_ready` still false.
- Exact next action: independent reviewer + security (distinct from implementer). **Do not merge. Do not live-enable VWAP.**

## 2026-08-23 TASK-002 security follow-up: restore pending heat after restart

- Time (UTC): 2026-08-23T10:30:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer (reviewer/security remain distinct)
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Objective: close the medium security finding that `_heat_reservations` were in-memory only after Stop/Start/crash.
- Product changes:
  - `_restore_pending_heat_reservations` scans broker pendings on every tick and after reconcile; rebuilds dollar risk from geometry.
  - News OCO two legs reserve **max** (not sum).
  - Unreadable CS_ comments, unusable SL/volume, or `get_pending_orders` failure set `_pending_restore_failed` / `_heat_unknown` so new entries cannot slip under the 3% cap.
  - `_open_dollar_risks` keeps that fail-closed flag (does not clear it after a failed pending list).
- Tests/gates (this session, actual):
  - `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_task002_heat` → all passed
  - `.venv\Scripts\python.exe -m ruff check src tests scripts/app.py` → All checks passed!
  - `black --check` on touched files → clean
- Invariants: 1%/1.5R/3% intact; `CHRONOSCALP_CONFIRM_LIVE` untouched; `live_ready` still false.
- Exact next action: independent security + functional reviewer (distinct from implementer). **Do not merge. Do not live-enable VWAP.**

## 2026-08-22 TASK-002 review-fix complete (do not merge)

- Time (UTC): 2026-08-22T17:15:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer (reviewer/security remain distinct)
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Objective: close merge-blocking findings on `6865d95` without live-enabling VWAP or loosening 1%/1.5R/3%.
- Product changes:
  - News pending: heat reserved **before** `news_straddle.tick`; dollar-risk capped to the allocated remainder; MT5 netting still fail-closed.
  - Simultaneous candidates: equal batch split of remaining heat (still ≤1%/trade).
  - `xau_vwap_pullback` places a stop pending; paper fills only from a **stored** crossing quote (never a synthetic quote from the pending price); expire after 2 M1 bars / engine `working_stop` None cancels.
  - `live_ready: false` fail-closed on API / Streamlit / Telegram; live loop still refuses real orders.
  - Comparison books: last quote cached onto newly created per-strategy PaperBrokers; R-normalized reports.
  - Backtest HTF uses closed-bar mask (`index + duration <= t`); comparison books + stop pendings.
  - `max_concurrent` re-checked after each fill and after stop reservation; harvest after stop place.
  - Incomplete heat metadata: reconstruct from live geometry or `_heat_unknown` blocks new entries.
- Tests/gates (this session, actual):
  - `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_task002_full` → all passed
  - `.venv\Scripts\python.exe -m ruff check src tests scripts/app.py` → All checks passed!
  - `black --check` on touched files after format → clean
- Invariants: 1%/1.5R/3% intact; `CHRONOSCALP_CONFIRM_LIVE` untouched; `live_ready` still false.
- Exact next action: independent reviewer + security (distinct from implementer). **Do not merge. Do not live-enable VWAP.**

## 2026-08-22 TASK-002 review-fix (Changes Requested on 6865d95)

- Time (UTC): 2026-08-22T16:55:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer (reviewer/security remain distinct)
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Objective: fix merge-blocking findings without live-enabling VWAP or loosening 1%/1.5R/3%.
- Scope: news heat reservation + netting; fair batch heat; VWAP stop-pending; live_ready fail-closed on API/Streamlit/Telegram; comparison books; HTF no-lookahead; max_concurrent after each reservation; reconstruct/fail-closed heat metadata; black `scripts/app.py`; ChronoScalp `TradingBot.tick` integration tests.
- Exact next action: implement, pytest/ruff/black, commit+push, re-request independent review. Do **not** merge. Do **not** set `live_ready: true`.

## 2026-08-22 TASK-002 independent multi-strategy + xau_vwap_pullback

- Time (UTC): 2026-08-22T16:40:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / implementer (reviewer and security remain distinct identities — **not done**)
- Branch: `ai/TASK-002-xau-vwap-multistrat`
- Objective: independent candidates, (symbol, strategy, ticket) state, 3% live heat, DST sessions, `xau_vwap_pullback` shadow-only, Telegram simultaneous-OR, tests + validation template.
- Product changes (this session):
  - Kernel: `evaluate_candidates`, composite tickets, heat allocation, MT5 hedging/netting fail-closed, news OCO twin-only, DST `SessionFilter`, spread shield, comparison vs live books.
  - `xau_vwap_pullback` module + `enabled: false` / `shadow_only: true`. Not on `enabled_strategies`. Not live-enabled.
  - Backtest processes all candidates (comparison books), SL-first, LIVE_ONLY_GATES includes live shared heat + netting.
  - Telegram off/shadow/on for VWAP pullback; status source; per-strategy PnL.
  - Docs: `STRATEGY_XAU_VWAP_PULLBACK.md`, validation templates with UNKNOWN metrics, ROADMAP, TELEGRAM_BOT_FA.
- Invariants: 1%/1.5R/3% intact; `CHRONOSCALP_CONFIRM_LIVE` untouched; Delta not rewritten.
- Exact next action: independent reviewer + security (distinct from implementer) before merge. Do **not** live-enable `xau_vwap_pullback`. Do not merge to `main` until those reviews land.
- Validation: `pytest -q` passed; `ruff check src tests` passed; `black --check` on touched files passed.

## 2026-08-22 TASK-002 claim + reclaim stale TASK-001 overlap

- Time (UTC): 2026-08-22T15:26:00Z
- Task / owner / role: TASK-002 / cursor:grok-4.6 / orchestrator + implementer
- Branch: ai/TASK-002-xau-vwap-multistrat
- Objective: independent multi-strategy execution + `xau_vwap_pullback` (disabled, shadow_only).
- Verified context and decisions:
  - TASK-001 heartbeat 2026-08-17 is stale vs 24h; owner `cursor:grok-4.5` is not this session.
  - Overlapping live/paper/telegram/risk/backtest files reclaimed into TASK-002. TASK-001 keeps Delta, research scripts, forensic docs.
  - Live heat cap 3.0% (matches daily loss); per-trade 1% and min 1.5 R:R unchanged. Comparison/paper uses independent virtual books.
  - `xau_vwap_pullback` will not be live-enabled this cycle. `CHRONOSCALP_CONFIRM_LIVE` untouched. Delta not rewritten.
- Exact next action: implement kernel (position keys, heat, account mode, DST sessions, candidate fan-out) then the strategy module and Telegram.

## 2026-08-17 deploy trade-open copy to VPS (TASK-001)

- Time (UTC): 2026-08-17T12:32:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer
- Branch: main @ `86bc291`
- Objective: apply Telegram trade-open copy to the running VPS program and control bot.
- Verified:
  - `origin/main` already had `86bc291`; no extra merge needed.
  - `scripts/deploy_vps_from_local.ps1` → `45.90.98.99`: VPS reset to `86bc291`, panel/API/Telegram restarted, `TG_KEYBOARD_RESTORED` to chat `1008770451`.
  - First trading restart left a leftover `run_live` PID; force restart started live PID `4644` (`START_OK=True`). Telegram PIDs running; VPS HEAD=`86bc291`.
  - `89.23.103.82` SSH port closed from this workstation; deploy target is `45.90.98.99`.
- Invariants: 1%/3% intact; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
- Exact next action: operator opens Telegram Settings → اعلان معامله; recipient must Start the bot (numeric chat_id if @username fails).

## 2026-08-17 Telegram trade-open copy to configurable chat (TASK-001)

- Time (UTC): 2026-08-17T12:00:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer
- Branch: ai/TASK-001-strategy-audit-redesign
- Objective: send a Telegram message as soon as a trade fills, default recipient `@taranomrashid`, with in-bot ID change.
- Product changes:
  - `alerting.trade_open_copy_enabled` / `trade_open_copy_chat_id` in `settings.yaml` (default `@taranomrashid`).
  - Fill path (`place_order` + news-straddle fill) calls `AlertNotifier.notify_trade_opened` so the copy goes even when general alerting is off.
  - Telegram Settings → اعلان معامله: on/off, change ID, test ping. Persist via `runtime_overrides.yaml`.
  - Unauthorized chats now see their numeric `chat_id` so a private recipient can Start the bot and pass the id to the operator.
- Invariants: 1%/3% intact; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
- Exact next action: restart Telegram control bot and trading bot so the menu and copy path load; recipient must Start the bot.

## 2026-08-14 Telegram Stop did not stop trading process (TASK-001)

- Time (UTC): 2026-08-14T09:35:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer
- Branch: ai/TASK-001-strategy-audit-redesign
- Objective: Telegram Stop then Start reported "already running" because Stop did not kill the real `run_live.py` tree (and `/stop` was kill-switch, not process stop).
- Product changes:
  - `process_control.stop_bot` kills pid-file PID **and** every `run_live.py` process; writes `data/user/bot.stopped`.
  - `bot_is_running` / `bot_pid` also detect orphan `run_live.py` processes; pid path is absolute under repo root.
  - Telegram Start Paper/Live stops first if still running, then starts; clears kill-switch marker.
  - `/stop`, «استاپ» → process stop; «توقف ورود» / `/halt` stay kill-switch.
  - `watch_bot.ps1` will not auto-start while `bot.stopped` exists.
- Gates: `pytest -q --basetemp .tmp_pytest_tg_stop_full` FULL_PYTEST=0; `ruff check src tests` RUFF_EXIT=0; black on touched files after format.
- Invariants: 1%/3% intact; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
- Exact next action: deploy so VPS Telegram/watchdog pick this up; operator uses «توقف ربات» then Start.

## 2026-08-14 apply EUR gate + merge/deploy to program (TASK-001)

- Time (UTC): 2026-08-14T08:00:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer
- Branch: ai/TASK-001-strategy-audit-redesign → merge to main + VPS deploy
- Objective: apply research evidence to running config; ship tooling/TZ/MT5 fixes.
- Product changes:
  - `settings.yaml`: remove `EURUSD_o` from active symbols; Delta `allowed_symbols: [XAUUSD]`.
  - Telegram label `دلتا (طلا)`; example overrides + docs updated.
  - VPS: after deploy run `_vps_apply_eur_gate.ps1` on gitignored runtime_overrides.
- Gates: focused pytest (delta/telegram/risk/journal/backtest) + ruff OK.
- Invariants: 1%/3% intact; live confirmation gate unchanged; EUR redesign still required.
- Exact next action after deploy: confirm VPS HEAD on main, Telegram shows دلتا (طلا), symbols exclude EUR; denser XAU OOS + EUR redesign remain open.

## 2026-08-14 limited WF + cost-stress evidence recorded (TASK-001)

- Time (UTC): 2026-08-14T01:35:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer
- Branch: ai/TASK-001-strategy-audit-redesign
- Objective: broker-native cost-stress + limited walk-forward OOS.
- Cost-stress 45d: XAUUSD 46 trades E[R] 0.354→0.353 PF≈2.11; EURUSD 17 trades E[R] −0.15→−0.206 (fail).
- Limited WF tiny-grid folds=2: XAUUSD OOS fold1 E[R]=1.007 (5t), fold2 E[R]=0.512 (4t), avg return +3.5%; EURUSD OOS E[R] −0.5/−0.76 (fail). Artifacts in `data/_analysis/`.
- Decisions: live stays disabled; EUR needs redesign; XAU promising but OOS sample too thin for live; 1%/3% intact.
- Exact next action: plan/implement EURUSD-specific strategy redesign; expand XAU OOS sample; independent reviewer/security before any enablement.

## 2026-08-12 limited 45d cost-stress COMPLETE (TASK-001)

- Time (UTC): 2026-08-12T22:50:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer
- Branch / worktree: ai/TASK-001-strategy-audit-redesign / D:/soft/Claud/porje/ChronoScalp s3
- Objective: broker-native baseline + 1.5× cost-stress for XAUUSD/EURUSD.
- Verified metrics (`data/_analysis/*_last45d.json`, window 2026-06-27→2026-08-11 UTC):
  - XAUUSD: trades=46, expectancy_r 0.354→0.353, PF 2.114→2.112, max_dd 2.02→2.03%, return ~17%.
  - EURUSD: trades=17, expectancy_r −0.150→−0.206, PF 0.591→0.477, max_dd 4.75→5.81% — **fail**.
- Decisions: do not enable live; keep 1%/3%; EUR needs separate redesign; XAU promising on this window but WF/OOS still required.
- Exact next action: run `_vps_limited_walkforward.ps1` / detach helper; record fold metrics; then EUR redesign plan.

## 2026-08-12 limited cost-stress tooling + prior XAU metrics (TASK-001)

- Time (UTC): 2026-08-12T21:25:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/Claud/porje/ChronoScalp s3 / pending
- Objective: finish broker-native 1.5× cost-stress; keep live frozen and 1%/3% intact.
- Verified context and decisions:
  - Prior VPS `validate_XAUUSD.json` (2026-08-11): 85 trades, expectancy_r 0.219→0.218 @1.5×, PF 1.654→1.652, max DD ~4.4%. Copied locally to `data/_analysis/validate_XAUUSD_vps_prior.json`.
  - Stale `cost_stress_1p5x_summary.json` with `missing_history` for both symbols is **not** trusted (wrong-era/_o).
  - Added `--last-days` / date window + pre-enrich slice to `run_cost_stress_validate.py`; quiet VPS runners (`LOG_LEVEL=WARNING`).
  - Limited 45d cost-stress observed running on VPS (~30 min per backtest); Finnhub 403 warnings only.
  - Limited WF script `_vps_limited_walkforward.ps1` ready after cost-stress completes.
- Files changed: `scripts/run_cost_stress_validate.py`, VPS helper scripts, `docs/STRATEGY_RESEARCH.md`, status/handoff/active claims.
- Tests/gates: `ruff check scripts/run_cost_stress_validate.py` OK; `pytest tests/test_backtest_engine.py tests/test_optimizer.py -q` 5 passed.
- Exact next action: poll VPS until `validate_EURUSD.json` + fresh summary appear; record metrics; run limited WF; do not enable live.

## 2026-08-12 walk-forward timezone fix (TASK-001)

- Time (UTC): 2026-08-12T16:05:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer (wf-tz lane)
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/Claud/porje/ChronoScalp s3 / pending commit
- Objective: fix `run_backtest` ValueError when walk-forward passes tz-aware start/end.
- Verified context and decisions:
  - Root cause: `pd.Timestamp(aware_dt, tz="UTC")` rejects tz-aware inputs.
  - Added `_to_utc_timestamp` (aware → `tz_convert`, naive → `tz="UTC"`); used in engine filters; fold windows normalize via same helper.
  - Live untouched; 1%/3% untouched.
- Files changed: `engine.py`, `optimizer.py`, `tests/test_backtest_engine.py`, `tests/test_optimizer.py` (new), claims/handoff.
- Tests/gates:
  - `pytest tests/test_backtest_engine.py tests/test_optimizer.py -q --basetemp .tmp_pytest_wf_tz` → 5 passed, PYTEST_EXIT=0
  - `ruff check src/chronoscalp/backtest tests/test_backtest_engine.py tests/test_optimizer.py` → All checks passed!, RUFF_EXIT=0
- Exact next action: re-run walk-forward / cost-stress on VPS with broker-native history.

## 2026-08-12 VPS history + next-step evidence (TASK-001)

- Time (UTC): 2026-08-12T15:57:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / research-docs
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/Claud/porje/ChronoScalp s3 / docs only (no commit this turn)
- Objective: record verified VPS MT5 fetch/depth facts and exact next research step; leave cost-stress numbers UNKNOWN until shell agent returns.
- Verified context and decisions:
  - VPS broker AUSCommercial-Demo uses native `XAUUSD` / `EURUSD` (not LiteFinance `XAUUSD_o` / `EURUSD_o`).
  - Chunked `fetch_ohlcv_range` fix required: tz-aware + large range → Invalid params.
  - History on VPS: ~100k bars M1/M5 for XAUUSD and EURUSD (broker depth cap); ~47–50k M15 bars.
  - Full walk-forward grid on 100k M1 too slow for interactive run; earlier failure also from tz bug in `run_backtest` date filter.
  - Live remains disabled; 1%/3% intact.
  - Cost-stress (1.5×) metrics: UNKNOWN pending shell agent.
- Files changed (and why): `docs/STRATEGY_RESEARCH.md`, `.ai-dos/project/status.md`, this handoff, `active.yaml` heartbeat — evidence + next action only.
- Tests/gates run with exact results: none this turn (docs-only).
- Review/security findings and dispositions: none new; independent reviewer/security still required before live.
- Known failures, risks, and assumptions: cost-stress numbers not yet available; full WF grid not practical interactively on 100k M1.
- File claims released or retained: TASK-001 claims retained.
- Exact next action: finish cost-stress on VPS with `XAUUSD`/`EURUSD`; then limited walk-forward (fewer folds / shorter window) after TZ fix lands.

## 2026-08-11 merge + VPS deploy complete

- Time (UTC): 2026-08-11T17:15:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / orchestrator
- Branch / worktree / commit: main @ `1c3f5aa` (merge `61164ae` + roadmap); task branch synced
- Objective: merge successful forensic/MistakeMemory/Telegram work; deploy VPS; verify Telegram.
- Verified context and decisions:
  - Merged `ai/TASK-001-strategy-audit-redesign` → `main` and pushed.
  - VPS deploy via `scripts/deploy_vps_from_local.ps1` finished at HEAD `1c3f5aa`; Telegram control bot restarted (`TG_KEYBOARD_RESTORED`); trading bot restarted by deploy script.
  - Local telegram suite: `tests/test_telegram_control_bot.py` TG_EXIT=0; smoke import OK.
  - Did not commit dirty `.env.example` / `AGENTS.md` churn.
- Exact next action: operator fetch broker-native M1 (`XAUUSD_o` / `EURUSD_o`) then walk-forward; keep live risk gates intact.

## 2026-08-11 Telegram MistakeMemory + merge/deploy

- Time (UTC): 2026-08-11T17:15:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / orchestrator
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/claud/porje/ChronoScalp s3 / pending telegram commit then merge to main
- Objective: wire MistakeMemory into Telegram risk UI, verify telegram tests, merge successful work to main, attempt VPS deploy, start broker-native history next step (docs already at 02868b4).
- Verified context and decisions:
  - Telegram: risk menu toggles «یادگیری از اشتباه روشن/خاموش», status/config visibility, runtime_overrides persistence, restart required.
  - Left unstaged: dirty `.env.example` / `AGENTS.md` (unrelated/bootstrap churn; preserve user copies).
  - Live still frozen; 1%/3% untouched.
- Files changed: broker_wizard, config_overrides, telegram control_bot/keyboards, TELEGRAM_BOT_FA.md, telegram/config_overrides tests, AI-DOS claims.
- Tests/gates: full pytest FULL_EXIT=0 (`--basetemp .tmp_pytest_merge1`); ruff RUFF_EXIT=0; telegram+overrides 29 passed earlier.
- Exact next action after merge: deploy VPS if SSH available; operator fetch `XAUUSD_o`/`EURUSD_o` M1 via `scripts/fetch_history.py`.

## 2026-08-11 forensic fixes + MistakeMemory integration

- Time (UTC): 2026-08-11T16:54:38Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / orchestrator (hard review of parallel lanes)
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/claud/porje/ChronoScalp s3 / pending product commit after 5f62ac9
- Objective and acceptance criteria: close accounting root causes with regression tests; ship learn-from-mistakes; keep live frozen and 1%/3% intact.
- Verified context and decisions:
  - Independent review blocked commit until `TradeJournal(..., symbols_cfg=settings.symbols_raw)` was wired in `main.py` (done).
  - MistakeMemory setup bucket now prefers 2nd reason token to avoid strategy-wide over-block; empty reason still incomplete.
  - `record_close` recomputes dollar-risk R when broker omits `r_multiple`.
  - `operational_max_lot`: XAU 2.0, FX majors 5.0, BTC 1.0, ETH 2.0.
- Files changed (and why):
  - `trade_journal.py` / `paper_broker.py` / `test_trade_journal.py` / `test_backtest_engine.py` — R units, orphan reject, timestamp adjust, initial SL, session-fixture docs
  - `position_sizing.py` / `symbols.yaml` / `test_risk.py` — operational lot caps
  - `mistake_memory.py` / `test_mistake_memory.py` / `main.py` / `STRATEGY_RESEARCH.md` — fingerprint refinement + journal symbols_cfg wiring
  - `.ai-dos/project/status.md` — status refresh
- Tests/gates run with exact results:
  - `.venv\Scripts\python.exe -m pytest -q --basetemp .tmp_pytest_task001_full5` → FULL_EXIT=0 (all tests passed)
  - `.venv\Scripts\python.exe -m ruff check src tests scripts` → RUFF_EXIT=0
  - `black --check` on TASK-001 touched product files → BLACK_TASK_EXIT=0 (repo-wide black still fails on pre-existing files)
- Review/security findings and dispositions: blocker (unwired symbols_cfg) fixed; high (coarse fingerprint) mitigated; independent reviewer/security still required before merge/live.
- Known failures, risks, and assumptions: no broker-native history; historical journal not rewritten; live still disabled.
- File claims released or retained: TASK-001 claims retained.
- Exact next action: obtain broker-native XAUUSD/EURUSD M1 data; run walk-forward + 1.5x cost stress before any strategy live enablement.

## 2026-08-11 MistakeMemory implemented

- Time (UTC): 2026-08-11T16:35:00Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / implementer (MistakeMemory lane)
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/Claud/porje/ChronoScalp s3 / pending commit
- Objective and acceptance criteria: deterministic learn-from-mistakes veto; no ML; 1%/3% unchanged; live not enabled.
- Verified context and decisions:
  - Fingerprint `{canonical_symbol}|{strategy}|{session}|{direction}|{setup_reason_bucket}`; exit_type omitted when `match_exit_type: false`.
  - Persist to `state_dir/lessons_{mode}.json`; block when cooldown count >= `max_repeats`.
  - Gate runs after a viable signal is selected (needs reason/direction/strategy), not at the earlier three_strikes line.
  - Record mirrors full-close three_strikes sites + negative external closes; partials skipped.
- Files changed (and why):
  - `src/chronoscalp/risk/mistake_memory.py` (new module)
  - `tests/test_mistake_memory.py` (7 unit tests)
  - `config/settings.yaml` (`risk.mistake_memory` knobs after three_strikes)
  - `src/chronoscalp/main.py` (construct + gate + record helpers)
  - `docs/STRATEGY_RESEARCH.md` (short Mistake Memory section)
- Tests/gates run with exact results:
  - `.venv\Scripts\python.exe -m pytest tests/test_mistake_memory.py -q --basetemp .tmp_pytest_task001_mm2` → 7 passed, EXIT:0
  - `.venv\Scripts\python.exe -m ruff check src/chronoscalp/risk/mistake_memory.py tests/test_mistake_memory.py src/chronoscalp/main.py` → All checks passed!
- Review/security findings and dispositions: none for this lane; independent review still required before merge/live.
- Known failures, risks, and assumptions:
  - Lessons with empty journal `reason` are skipped as incomplete (may under-record orphaned external closes).
  - Session at close time is used for recording; may differ from entry session.
  - Parallel lanes still dirty: journal/sizing/symbols — not part of this commit.
- File claims released or retained: MistakeMemory file claims retained under TASK-001.
- Exact next action: parent/orchestrator integrate with journal + sizing lanes; full pytest suite before merge.

## 2026-08-11 ownership transfer + forensic RCA start

- Time (UTC): 2026-08-11T16:19:28Z
- Task / owner / role: TASK-001 / cursor:grok-4.5 / orchestrator + architect + implementer
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/claud/porje/ChronoScalp s3 / ae20f88 (+ dirty AI-DOS/bootstrap files preserved)
- Objective and acceptance criteria: continue forensic audit + redesign; add deterministic mistake-memory so losing setups are not immediately repeated; keep live disabled and 1%/3% intact.
- Verified context and decisions:
  - Previous owner `codex:root` had stale heartbeat (2026-08-09); no competing active tasks.
  - Ownership transferred to `cursor:grok-4.5`; heartbeat refreshed; file claims extended for `main.py`, `paper_broker.py`, `risk/mistake_memory.py`, `tests/test_mistake_memory.py`.
  - Forensic RCA (read-only agent): abnormal lots are 1%-consistent with large equity × ultra-tight stops + high `max_lot`; invalid R is `$pnl / price_distance` in `record_external_close`; reversed timestamps ≈ LiteFinance UTC+3 open vs UTC close; blank rows are orphan external closes; zero-trade XAU backtest logs are synthetic off-session pytest fixtures, not a live engine crash.
  - User request: add learn-from-mistakes capability (deterministic MistakeMemory, not ML).
- Files changed (and why): `.ai-dos/tasks/active.yaml`, `.ai-dos/tasks/handoff.md` — ownership/heartbeat/claims only so far.
- Tests/gates run with exact results: not re-run yet this session (pending code changes).
- Review/security findings and dispositions: independent reviewer/security still required before merge/live.
- Known failures, risks, and assumptions: no broker-native history in repo; journal dump at `data/_analysis/trade_journal_live.json`; black --check previously failed on 13 pre-existing files.
- File claims released or retained: all TASK-001 claims retained and extended.
- Exact next action: write regression tests then fix (1) external R units + orphan/timestamp guards in trade_journal, (2) operational lot caps in sizing/symbols, (3) MistakeMemory + main wiring, (4) backtest session fixture clarity.

### Parallel agent plan (non-overlapping writers)

1. Journal/R/timestamps/orphan + paper R initial SL + journal tests + backtest fixture note
2. Operational max lot in position_sizing + symbols.yaml + risk tests
3. MistakeMemory module + settings knobs + main gate/record + tests + STRATEGY_RESEARCH note

## 2026-08-09 preflight checkpoint

- Time (UTC): 2026-08-09T14:35:07Z
- Task / owner / role: TASK-001 / codex:root / orchestrator + architect + implementer
- Branch / worktree / commit: ai/TASK-001-strategy-audit-redesign / D:/soft/claud/porje/ChronoScalp s3 / uncommitted preflight
- Objective and acceptance criteria: forensic audit of available trades/logs and evidence-based redesign for XAUUSD/EURUSD scalp and M15-H1; see active task registry.
- Verified context and decisions: no competing AI-DOS claims; dirty main contained pre-existing user/bootstrap changes; live journal last updated 2026-07-31; latest log is test output and includes a zero-trade XAUUSD backtest. Live enablement is frozen pending validation.
- Files changed (and why): AI-DOS task/project records only, to establish scope, ownership, invariants, risks, and validation before product code changes.
- Tests/gates run with exact results: `.venv/Scripts/python.exe -m pytest -q --basetemp .tmp_pytest_task001` passed 204/204; `.venv/Scripts/python.exe -m ruff check src tests scripts` passed; `.venv/Scripts/python.exe -m black --check src tests scripts` failed on 13 pre-existing files.
- Review/security findings and dispositions: critical financial-risk task requires reviewer and security identities independent from implementer before merge/live use.
- Known failures, risks, and assumptions: repository lacks broker-native historical data; journal contains abnormal lot sizes/R values and incomplete attribution; `.env` is local and was not read.
- File claims released or retained: all TASK-001 claims retained.
- Exact next action: inspect sizing/journal/backtest code and write root-cause tests; acquire broker-native XAUUSD/EURUSD M1 data before strategy selection or parameter tuning.

### Verified forensic snapshot

- Journal: 238 closed, 0 open, last update 2026-07-31T10:18:40Z; recorded net PnL = -27,326.13.
- `ultra_scalp`: 92 trades, 32.61% wins, PnL -22,713.50.
- XAUUSD canonical: 62 trades, 45.16% wins, PnL -3,352.02, average 8.84 lots, maximum 20.28 lots.
- EURUSD canonical: 45 trades, 31.11% wins, PnL -4,027.69, average 41.19 lots, maximum 49.65 lots.
- Data-integrity flags: 178 records have absolute R multiple above 10; at least 34 records have close timestamps before open timestamps, and blank timestamps also exist.
- Research decision: GitHub performance claims are hypotheses only. Reusable ideas are walk-forward/no-lookahead testing, explicit spread/commission/slippage attribution, session/regime gates, and structure-first entries. No external strategy is accepted without reproduction on this broker's untouched data.

### 2026-08-17 — low live trade count / poor results triage

- Time (UTC): 2026-08-17
- Task / owner / role: TASK-001 / cursor / implementer
- Branch / worktree / commit: `ai/TASK-001-strategy-audit-redesign`, this worktree
- Objective: explain why live/demo takes very few trades with poor results, and remove the causes that are configuration or observability defects rather than strategy quality.
- Verified context and decisions:
  - `config/runtime_overrides.yaml` on this host had `enabled_strategies: [liquidity_volume]` while the committed example has `[delta, liquidity_volume]`. `resolve_enabled_strategies` prefers the list, so Delta was off regardless of `settings.yaml`. Overlay drift is the primary cause of the low trade count.
  - 11 override keys are schema-validated and never read: confirmed by searching `src/` for each key outside `config_overrides.py`. Operators were relying on daily trade caps, portfolio heat, weekly/monthly loss caps and single-instance protection that do not exist.
  - `backtest/engine.py` applies session, news, spread and `validate_signal` only. The live loop adds nine more entry guards, so the 45-day XAUUSD result (46 trades, PF 2.11, +17.08%) is an upper bound and never described the deployed system.
  - `MT5Connector.connect()` called `mt5.shutdown()` on every attempt with no idempotence check, so any repeated caller rebuilt the IPC link. Matches the reported log bursts.
  - Independent journal recount reproduces the earlier snapshot: 238 closed trades, 22.7% wins, net -27,326.13, `ultra_scalp` -22,713.50, median volume 7.94 lots, max 50.05, 229 of 238 exits recorded as `external`.
  - VPS `89.23.103.82` was unreachable from this workstation (no ping, no direct TCP 22, no SSH banner through the local SOCKS5 proxy), so the deployed overlay could not be read or corrected remotely. The MT5 account in the operator's log (`AUSCommercial-Demo` / 55625500) also differs from the deploy helper's LiteFinance account, so the deployment target has moved.
- Files changed (and why): `src/chronoscalp/data/mt5_connector.py` (idempotent connect), `src/chronoscalp/config.py` (retain overlay for reporting), `src/chronoscalp/config_overrides.py` (`UNENFORCED_OVERRIDE_KEYS`, `unenforced_override_keys`), `src/chronoscalp/main.py` (`_log_entry_gate_profile` at startup), `src/chronoscalp/backtest/engine.py` (`LIVE_ONLY_GATES` + summary field + warning), `config/runtime_overrides.demo_shadow.example.yaml` (INERT annotations, drift warning), `docs/ROADMAP.md`, plus tests.
- Tests/gates run with exact results: `python -m pytest -q` passed; `python -m ruff check src tests` passed; `python -m black --check` clean on all eight changed files (7 pre-existing unrelated files still fail, untouched).
- Known failures, risks, and assumptions: no risk ceiling was changed (1% per trade, 1.5 gross R:R, live gate all intact). Delta remains unvalidated for live money per `docs/STRATEGY_DELTA.md`; re-enabling it here only affects the paper/shadow overlay. The deployed VPS overlay is still stale and must be corrected on the host.
- File claims released or retained: all TASK-001 claims retained.
- Exact next action: correct the deployed `runtime_overrides.yaml` (or toggle Delta via Telegram Settings -> Strategies), restart the bot, then read the new "Entry gate profile" and 5-minute "Entry skip heartbeat" lines to see which guard dominates before tuning anything.

## Template

- Time (UTC):
- Task / owner / role:
- Branch / worktree / commit:
- Objective and acceptance criteria:
- Verified context and decisions:
- Files changed (and why):
- Tests/gates run with exact results:
- Review/security findings and dispositions:
- Known failures, risks, and assumptions:
- File claims released or retained:
- Exact next action:
