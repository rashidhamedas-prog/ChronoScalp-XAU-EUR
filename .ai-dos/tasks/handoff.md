# Handoff Log

Append newest entries at the top. Never erase another agent's record.

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
