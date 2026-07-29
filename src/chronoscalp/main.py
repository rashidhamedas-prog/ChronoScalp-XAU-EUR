"""Live/paper trading orchestration loop.

Deployment targets:
- **Windows + MT5** — ``execution.broker: mt5``, ``data_source: mt5`` (or auto)
- **Linux VPS (e.g. Netherlands)** — ``execution.broker: oanda``, ``data_source: oanda``
  See docs/DEPLOY_NL_VPS.md. No MetaTrader5 terminal required.
- **Paper on any OS** — ``execution.broker: paper`` with ``data_source: oanda`` or ``mt5``

``--mode live`` requires CHRONOSCALP_CONFIRM_LIVE=yes in .env — see CLAUDE.md rule #2.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from chronoscalp.config import Settings, get_settings
from chronoscalp.data.spread_sampler import SpreadSampler
from chronoscalp.execution.mt5_broker import MT5Broker
from chronoscalp.execution.mt5_utils import StaleStopsError
from chronoscalp.execution.oanda_broker import OANDABroker
from chronoscalp.execution.position_logic import (
    apply_breakeven_or_trailing,
    check_sl_tp_hit,
    exit_price_for_hit,
)
from chronoscalp.execution.trade_manager import manage_open_position
from chronoscalp.filters.news_calendar import NewsCalendarManager
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.logging_setup import logger
from chronoscalp.ml.scorer import configure_scorer
from chronoscalp.orchestration.alerts import AlertLevel, AlertNotifier
from chronoscalp.orchestration.bar_scheduler import (
    BarCloseGate,
    SignalDeduper,
    last_completed_bar_time,
    signal_dedup_key,
)
from chronoscalp.orchestration.bootstrap import (
    connector_label,
    create_broker,
    create_data_connector,
    resolve_data_source,
)
from chronoscalp.orchestration.circuit_breaker import CircuitBreaker
from chronoscalp.orchestration.kill_switch import KillSwitch
from chronoscalp.orchestration.state_store import TradingStateStore
from chronoscalp.orchestration.trade_journal import (
    TradeJournal,
    journal_path_for,
    load_daily_reset_marker,
    sum_closed_pnl_today,
)
from chronoscalp.risk.institutional_guards import (
    DailyDrawdownGuard,
    SpreadMovingAverageGuard,
    ThreeStrikesGuard,
    correlation_blocks,
    correlation_guard_enabled,
    effective_max_concurrent_positions,
    volatility_decision,
)
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy, resolve_enabled_strategies
from chronoscalp.strategy.news_straddle_engine import DynamicNewsStraddleEngine
from chronoscalp.utils.types import SignalType, Timeframe

STANDARD_TIMEFRAMES = [Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M10, Timeframe.M15]


class TradingBot:
    def __init__(self, settings: Settings, mode: str) -> None:
        if mode not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")
        if mode == "live" and not settings.secrets.live_trading_confirmed:
            raise RuntimeError(
                "Refusing to start --mode live: set CHRONOSCALP_CONFIRM_LIVE=yes "
                "in .env only once you have validated the strategy in backtest "
                "and paper mode. See docs/RISK_DISCLAIMER.md."
            )

        self.settings = settings
        self.mode = mode
        _, _, use_ultra_scalp, use_news_straddle = resolve_enabled_strategies(settings.strategy)
        self.use_ultra_scalp = use_ultra_scalp
        self.use_news_straddle = use_news_straddle
        scalp_tf = (settings.raw.get("timeframes") or {}).get("ultra_scalp") or {}
        if use_ultra_scalp:
            higher_raw = scalp_tf.get("higher_trend") or ["M15", "M5"]
            trigger_raw = scalp_tf.get("entry_trigger") or ["S15"]
            self.higher_timeframes = [Timeframe(tf) for tf in higher_raw]
            self.trigger_timeframe = Timeframe(trigger_raw[-1])
            self.poll_interval = int(
                scalp_tf.get(
                    "poll_interval_seconds",
                    settings.execution.get("poll_interval_seconds", 2),
                )
            )
            self.fetch_timeframes = list(
                dict.fromkeys([*self.higher_timeframes, self.trigger_timeframe, Timeframe.M1])
            )
            logger.info(
                "Ultra-scalp mode ON: higher={} trigger={} poll={}s",
                [t.value for t in self.higher_timeframes],
                self.trigger_timeframe.value,
                self.poll_interval,
            )
        else:
            self.higher_timeframes = [
                Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]
            ]
            self.trigger_timeframe = Timeframe(settings.raw["timeframes"]["entry_trigger"][-1])
            self.poll_interval = int(settings.execution.get("poll_interval_seconds", 5))
            self.fetch_timeframes = list(STANDARD_TIMEFRAMES)

        self.trade_on_bar_close = bool(settings.execution.get("trade_on_bar_close_only", True))
        self.independent_symbol_entries = bool(
            settings.risk.get("independent_symbol_entries", False)
        )
        self.max_concurrent = effective_max_concurrent_positions(
            settings.risk, len(settings.symbols)
        )
        self.state_dir = Path(settings.execution.get("state_dir", "data/state"))
        self.data_source = resolve_data_source(settings)

        self.connector = create_data_connector(settings)
        self.broker = create_broker(settings, mode=mode, connector=self.connector)

        self.session_filter = SessionFilter.from_config(settings.sessions)
        self.news_filter = NewsFilter.from_config(
            settings.news_filter,
            settings_config_dir() / "news_events.yaml",
            settings.secrets.news_api_key,
        )
        self.news_calendar = NewsCalendarManager.from_news_filter(self.news_filter)
        self.strategy = MultiTimeframeStrategy(
            settings.strategy, settings.indicators, symbols_cfg=settings.symbols_raw
        )
        self.risk_manager = RiskManager(
            risk_cfg=settings.risk,
            spread_cfg=settings.spread_filter,
            symbols_cfg=settings.symbols_raw,
            starting_equity=float(settings.backtest.get("initial_balance", 10_000)),
        )
        news_straddle_cfg = dict(settings.strategy.get("news_straddle") or {})
        self.news_straddle = DynamicNewsStraddleEngine(
            calendar=self.news_calendar,
            risk_manager=self.risk_manager,
            cfg=news_straddle_cfg,
        )
        if self.use_news_straddle:
            logger.info(
                "News straddle ON: place={}s before, pause={}m, expiry={}s, max_spread={} pips",
                news_straddle_cfg.get("place_seconds_before", 30),
                news_straddle_cfg.get("pause_minutes_before", 2),
                news_straddle_cfg.get("expiry_seconds", 120),
                news_straddle_cfg.get("max_spread_pips", 2.0),
            )

        risk_cfg = settings.risk
        strikes_cfg = risk_cfg.get("three_strikes") or {}
        self.three_strikes = ThreeStrikesGuard(
            max_losses=int(strikes_cfg.get("max_losses", 3)),
            pause_hours=int(strikes_cfg.get("pause_hours", 12)),
        )
        self.three_strikes_enabled = bool(strikes_cfg.get("enabled", True))
        spread_ma_cfg = risk_cfg.get("spread_ma_guard") or {}
        self.spread_ma_guard = SpreadMovingAverageGuard(
            window=int(spread_ma_cfg.get("window", 100)),
            multiplier=float(spread_ma_cfg.get("multiplier", 1.2)),
        )
        self.spread_ma_enabled = bool(spread_ma_cfg.get("enabled", True))
        self.corr_cfg = risk_cfg.get("correlation") or {}
        self.vol_cfg = risk_cfg.get("volatility_guard") or {}
        self.partial_cfg = risk_cfg.get("partial_tp") or {}
        self.chandelier_cfg = risk_cfg.get("chandelier") or {}
        self.daily_dd_guard = DailyDrawdownGuard(
            max_daily_loss_pct=float(risk_cfg.get("max_daily_loss_pct", 3.0)),
            starting_equity=float(settings.backtest.get("initial_balance", 10_000)),
        )
        self.daily_dd_close_all = bool(risk_cfg.get("daily_drawdown_close_all", True))
        self._position_meta: dict[int, dict] = {}

        state_path = self.state_dir / f"trading_state_{mode}.json"
        self.state_store = TradingStateStore(state_path)
        self.state_store.load()

        self.trade_journal = TradeJournal(journal_path_for(self.state_dir, mode), mode=mode)
        self.trade_journal.load()

        # Re-seed today's realized P&L so restarts can't bypass the daily stop.
        # An explicit operator marker (scripts/reset_daily_tracker.py) excludes
        # trades closed before the reset.
        reset_marker = load_daily_reset_marker(self.state_dir, mode)
        today_pnl = sum_closed_pnl_today(self.trade_journal.closed_trades, since=reset_marker)
        if today_pnl:
            self.risk_manager.daily_tracker.record_trade_pnl(today_pnl)
            logger.info(
                "Daily tracker seeded from journal: realized_today={:+.2f} (reset_marker={})",
                today_pnl,
                reset_marker.isoformat() if reset_marker else "none",
            )

        resilience_cfg = settings.resilience
        self.kill_switch = KillSwitch(
            state_dir=self.state_dir,
            env_stop=settings.secrets.chronoscalp_stop_trading,
        )
        self.circuit_breaker = CircuitBreaker(
            max_consecutive_errors=int(resilience_cfg.get("max_consecutive_errors", 5)),
        )
        self.alerts = AlertNotifier.from_settings(settings.alerting, settings.secrets)
        self._alert_on_daily_loss = bool(resilience_cfg.get("alert_on_daily_loss_limit", True))
        self._alert_on_connection_loss = bool(resilience_cfg.get("alert_on_connection_loss", True))
        self._reconcile_interval = int(resilience_cfg.get("reconcile_interval_seconds", 60))
        self._last_reconcile_at: datetime | None = None
        self._daily_loss_alerted = False
        self._connection_loss_alerted = False
        self._kill_switch_alerted = False
        self._skip_counts: dict[str, int] = {}
        self._last_skip_log_at: datetime | None = None
        self._data_starvation_alerted = False
        self._last_trade_opened_at: datetime | None = None
        self._started_at: datetime | None = None
        self._skip_heartbeat_seconds = int(resilience_cfg.get("skip_heartbeat_seconds", 300))
        self._data_starvation_alert_seconds = int(
            resilience_cfg.get("data_starvation_alert_seconds", 300)
        )

        self.open_tickets: dict[str, int] = dict(self.state_store.state.open_tickets)
        self.bar_gate = BarCloseGate()
        for symbol, bar_iso in self.state_store.state.last_evaluated_bars.items():
            try:
                self.bar_gate.load_last_bar(symbol, datetime.fromisoformat(bar_iso))
            except ValueError:
                logger.warning("Skipping invalid last_evaluated_bar for {}: {}", symbol, bar_iso)

        self.signal_deduper = SignalDeduper(set(self.state_store.state.processed_signals))

        ml_cfg = settings.ml
        if ml_cfg.get("enabled"):
            configure_scorer(ml_cfg.get("model_path"))

        spread_cfg = settings.spread_filter
        self.spread_sampler = SpreadSampler(
            directory=spread_cfg.get("spread_history_dir", "data/spread_history"),
            enabled=bool(spread_cfg.get("sample_live_spread", False)),
        )

    def _news_currency(self, symbol: str) -> str | None:
        spec = self.settings.symbols_raw.get(symbol, {})
        return spec.get("news_currency")

    def start(self) -> None:
        if not self.connector.connect():
            raise RuntimeError(
                f"Failed to connect to {connector_label(self.connector)} for market data. "
                "Check credentials in .env and docs/DEPLOY_NL_VPS.md for OANDA setup."
            )
        if not self.broker.connect():
            raise RuntimeError("Failed to connect broker")

        self._reconcile_state_with_broker()
        self._last_reconcile_at = datetime.now(tz=UTC)
        self._started_at = self._last_reconcile_at

        poll_seconds = int(self.poll_interval)
        logger.info(
            "ChronoScalp started in {} mode (data={}, broker={}), polling every {}s (bar_close_only={})",
            self.mode,
            self.data_source,
            self.settings.execution.get("broker", "paper"),
            poll_seconds,
            self.trade_on_bar_close,
        )
        if self.alerts.is_configured:
            self.alerts.notify(
                "Bot started",
                f"mode={self.mode}, symbols={','.join(self.settings.symbols)}",
                AlertLevel.INFO,
            )
        if self.kill_switch.is_active():
            logger.warning("Kill switch active at startup — new entries disabled")

        try:
            while True:
                if self.kill_switch.check_and_log():
                    prev = self._kill_switch_alerted
                    if not prev:
                        self.alerts.notify(
                            "Kill switch active",
                            self.kill_switch.reason() or "unknown",
                            AlertLevel.CRITICAL,
                        )
                    self._kill_switch_alerted = True
                else:
                    self._kill_switch_alerted = False
                self.tick()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            logger.info("Shutdown requested, stopping.")
        finally:
            self._persist_state()
            self.connector.shutdown()

    def _reconcile_state_with_broker(self, *, alert_on_change: bool = False) -> None:
        previous = dict(self.open_tickets)
        if self.mode == "live":
            if isinstance(self.broker, MT5Broker):
                managed = self.broker.get_managed_positions()
            else:
                managed = self.broker.get_open_positions()
        else:
            managed = self.broker.get_open_positions()

        managed_tickets = {p.ticket for p in managed}
        now = datetime.now(tz=UTC)
        for symbol, ticket in list(previous.items()):
            if ticket not in managed_tickets:
                # SL/TP/manual close — record PnL before state/journal ghost-drop.
                self._on_position_closed_externally(symbol, ticket, now)

        broker_map = {p.symbol: p.ticket for p in managed}
        self.state_store.reconcile_open_tickets(broker_map)
        self.open_tickets = dict(self.state_store.state.open_tickets)
        self.trade_journal.sync_open_from_broker(managed, now=now)
        self._write_broker_positions_snapshot()

        if alert_on_change and previous != self.open_tickets:
            self.alerts.notify(
                "State reconciled",
                f"before={previous} after={self.open_tickets}",
                AlertLevel.WARNING,
            )

    def _write_broker_positions_snapshot(self) -> None:
        """Persist live account positions for Telegram/dashboard (all magics)."""
        path = self.state_dir / f"broker_positions_{self.mode}.json"
        rows: list[dict] = []
        account: dict = {}
        try:
            if isinstance(self.broker, MT5Broker):
                rows = self.broker.snapshot_account_positions()
                account = self.broker.snapshot_account_summary()
            else:
                for p in self.broker.get_open_positions():
                    direction = (
                        p.direction.value if hasattr(p.direction, "value") else str(p.direction)
                    )
                    rows.append(
                        {
                            "ticket": int(p.ticket),
                            "symbol": str(p.symbol),
                            "direction": direction,
                            "volume": float(p.volume),
                            "entry_price": float(p.entry_price),
                            "stop_loss": float(p.stop_loss),
                            "take_profit": float(p.take_profit),
                            "profit": 0.0,
                            "magic": 0,
                            "comment": "",
                            "open_time": p.open_time.isoformat() if p.open_time else "",
                        }
                    )
                try:
                    bal = float(self.broker.get_balance())
                    account = {
                        "equity": bal,
                        "balance": bal,
                        "margin": 0.0,
                        "profit": 0.0,
                        "login": 0,
                        "server": "",
                    }
                except Exception:  # noqa: BLE001
                    account = {}
            payload = {
                "mode": self.mode,
                "updated_at": datetime.now(tz=UTC).isoformat(),
                "account": account,
                "positions": rows,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("Failed writing broker positions snapshot to {}", path)

    def _maybe_reconcile(self, now: datetime) -> None:
        if self._reconcile_interval <= 0:
            return
        if self._last_reconcile_at is None:
            self._reconcile_state_with_broker(alert_on_change=True)
            self._last_reconcile_at = now
            return
        elapsed = (now - self._last_reconcile_at).total_seconds()
        if elapsed >= self._reconcile_interval:
            self._reconcile_state_with_broker(alert_on_change=True)
            self._last_reconcile_at = now

    def _note_skip(self, reason: str) -> None:
        self._skip_counts[reason] = self._skip_counts.get(reason, 0) + 1

    def _maybe_log_skip_heartbeat(self, now: datetime) -> None:
        if self._last_skip_log_at is None:
            self._last_skip_log_at = now
            return
        if (now - self._last_skip_log_at).total_seconds() < self._skip_heartbeat_seconds:
            return
        if self._skip_counts:
            summary = ", ".join(f"{k}={v}" for k, v in sorted(self._skip_counts.items()))
            logger.info("Entry skip heartbeat ({}s): {}", self._skip_heartbeat_seconds, summary)
        else:
            logger.info(
                "Entry skip heartbeat ({}s): no skips recorded", self._skip_heartbeat_seconds
            )
        self._skip_counts.clear()
        self._last_skip_log_at = now

    def _check_data_health(self, now: datetime) -> None:
        """Reconnect + alert when market data has been empty too long."""
        ensure = getattr(self.connector, "ensure_connected", None)
        if callable(ensure):
            ensure()

        last_ok = getattr(self.connector, "last_successful_fetch_at", None)
        if last_ok is None:
            if self._started_at is None:
                return
            age = (now - self._started_at).total_seconds()
        else:
            age = (now - last_ok).total_seconds()

        if age < self._data_starvation_alert_seconds:
            self._data_starvation_alerted = False
            return
        if self._data_starvation_alerted:
            return
        self._data_starvation_alerted = True
        msg = (
            f"No successful market-data fetch for {int(age)}s "
            f"(threshold={self._data_starvation_alert_seconds}s). "
            "Check MT5 terminal login / Market Watch symbols."
        )
        logger.error(msg)
        self.alerts.notify("Data starvation", msg, AlertLevel.ERROR)
        if callable(ensure):
            ensure()

    def _min_rr_for_signal(self, signal) -> float:
        if "ultra_scalp" in (signal.reason or ""):
            scalp = self.settings.strategy.get("ultra_scalp") or {}
            return max(1.0, float(scalp.get("min_reward_risk_ratio", 1.0)))
        return max(1.0, float(self.settings.risk.get("min_reward_risk_ratio", 1.5)))

    def _persist_state(self) -> None:
        self.state_store.state.open_tickets = dict(self.open_tickets)
        self.state_store.state.processed_signals = sorted(self.signal_deduper.processed_keys)
        self.state_store.state.last_evaluated_bars = {
            sym: ts.isoformat() for sym, ts in self.bar_gate.last_evaluated_bars().items()
        }
        self.state_store.save()

    def tick(self) -> None:
        now = datetime.now(tz=UTC)
        self._maybe_reconcile(now)
        self._check_data_health(now)
        tick_had_failure = False
        failure_context = ""

        if not self.connector.is_connected:
            tick_had_failure = True
            failure_context = "data_disconnect"
            if self._alert_on_connection_loss and not self._connection_loss_alerted:
                self.alerts.notify(
                    f"{connector_label(self.connector)} connection lost",
                    "Market data connector is disconnected — skipping new entries",
                    AlertLevel.ERROR,
                )
                self._connection_loss_alerted = True
        else:
            self._connection_loss_alerted = False

        kill_active = self.kill_switch.is_active()
        circuit_tripped = self.circuit_breaker.is_tripped
        equity_now = self.broker.get_balance()
        unrealized = self._estimate_unrealized_pnl()
        realized = float(self.risk_manager.daily_tracker._realized_pnl_today)
        daily_dd_hit = self.daily_dd_guard.check(equity_now, realized, unrealized, at=now)
        daily_limit_hit = daily_dd_hit or self.risk_manager.daily_tracker.daily_loss_limit_hit(
            at=now
        )
        if daily_dd_hit and self.daily_dd_close_all:
            self._close_all_positions(now, reason="daily_drawdown")
        if daily_limit_hit and self._alert_on_daily_loss and not self._daily_loss_alerted:
            self.alerts.notify(
                "Daily loss limit hit",
                "No new entries until the next trading day",
                AlertLevel.WARNING,
            )
            self._daily_loss_alerted = True
        if not daily_limit_hit:
            self._daily_loss_alerted = False

        allow_new_entries = (
            self.connector.is_connected
            and not kill_active
            and not circuit_tripped
            and not daily_limit_hit
            and not self.daily_dd_guard.blocked
        )
        if not allow_new_entries:
            if not self.connector.is_connected:
                self._note_skip("data_disconnect")
            if kill_active:
                self._note_skip("kill_switch")
            if circuit_tripped:
                self._note_skip("circuit_breaker")
            if daily_limit_hit:
                self._note_skip("daily_loss_limit")

        for symbol in self.settings.symbols:
            try:
                spread_pips = self.broker.get_current_spread_pips(symbol)
                self.spread_sampler.record(symbol, spread_pips, at=now)
                self.spread_ma_guard.observe(symbol, spread_pips)

                self._manage_open_position(symbol, now)
                if not allow_new_entries:
                    continue
                if symbol in self.open_tickets:
                    self._note_skip(f"{symbol}:already_open")
                    continue

                if self.three_strikes_enabled and self.three_strikes.is_paused(symbol, at=now):
                    self._note_skip(f"{symbol}:three_strikes")
                    continue

                if len(self.open_tickets) >= self.max_concurrent:
                    self._note_skip("max_concurrent")
                    continue

                if not self.session_filter.is_within_session(now, symbol=symbol):
                    self._note_skip(f"{symbol}:outside_session")
                    continue

                use_smc, use_liq, use_scalp, use_news_straddle = resolve_enabled_strategies(
                    self.settings.strategy
                )
                currency = self._news_currency(symbol)

                # News straddle: pause normal entries near high-impact releases and
                # drive ATR pending brackets + OCO via the Broker interface.
                if use_news_straddle:
                    m1_for_straddle = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=40)
                    if m1_for_straddle is not None and not m1_for_straddle.empty:
                        atr_period = int(
                            (self.settings.strategy.get("news_straddle") or {}).get("atr_period", 14)
                        )
                        m1_for_straddle = enrich_with_indicators(
                            m1_for_straddle,
                            atr_period=atr_period,
                        )
                        # PaperBroker has no live ticks — seed bid/ask from last M1 close.
                        if hasattr(self.broker, "set_quote"):
                            mid = float(m1_for_straddle["close"].iloc[-1])
                            pip_size = float(
                                self.settings.symbols_raw.get(symbol, {}).get("pip_size", 0.01)
                                or 0.01
                            )
                            half = max(spread_pips, 0.0) * pip_size / 2.0
                            self.broker.set_quote(symbol, mid - half, mid + half, now)
                    else:
                        m1_for_straddle = pd.DataFrame()
                    straddle_res = self.news_straddle.tick(
                        self.broker,
                        symbol=symbol,
                        moment=now,
                        m1_df=m1_for_straddle,
                        spread_pips=spread_pips,
                        currency=currency,
                        already_open=symbol in self.open_tickets,
                    )
                    if straddle_res.action in ("placed", "oco_filled", "filled", "expired"):
                        logger.info(
                            "{} news_straddle action={} phase={}",
                            symbol,
                            straddle_res.action,
                            straddle_res.phase.value,
                        )
                    if straddle_res.opened_position is not None:
                        position = straddle_res.opened_position
                        self.open_tickets[symbol] = position.ticket
                        self._position_meta[position.ticket] = {
                            "initial_volume": position.volume,
                            "initial_stop_loss": position.stop_loss,
                            "partial_taken": False,
                            "breakeven_moved": False,
                        }
                        self.trade_journal.record_open(position)
                        self._persist_state()
                        self._last_trade_opened_at = now
                        event_title = ""
                        if straddle_res.session is not None:
                            event_title = straddle_res.session.event_title
                        self.alerts.notify(
                            "News straddle filled",
                            (
                                f"{symbol} {position.direction.value} vol={position.volume:.2f} "
                                f"entry={position.entry_price:.5f} event={event_title}"
                            ),
                            AlertLevel.INFO,
                        )
                        continue
                    if self.news_straddle.is_scalp_paused(now, currency) or straddle_res.phase.value in (
                        "paused",
                        "pending",
                    ):
                        self._note_skip(f"{symbol}:news_straddle_{straddle_res.action}")
                        continue

                if self.news_filter.is_blackout(now, currency=currency):
                    self._note_skip(f"{symbol}:news_blackout")
                    continue

                if self.spread_ma_enabled and not self.spread_ma_guard.allows(symbol, spread_pips):
                    self._note_skip(f"{symbol}:spread_ma")
                    continue

                data_by_tf = self._fetch_and_enrich(symbol)
                want_institutional = use_smc or use_liq or (not use_scalp)

                scalp_df = data_by_tf.get(self.trigger_timeframe) if use_scalp else None
                inst_tf = Timeframe.M1
                inst_df = data_by_tf.get(inst_tf) if want_institutional else None
                if want_institutional and (inst_df is None or inst_df.empty):
                    # Fallback when M1 missing (paper/tests): use trigger frame.
                    inst_df = data_by_tf.get(self.trigger_timeframe)
                    inst_tf = self.trigger_timeframe

                if use_scalp and (scalp_df is None or scalp_df.empty) and (
                    inst_df is None or inst_df.empty
                ):
                    self._note_skip(f"{symbol}:no_trigger_data")
                    continue
                if (not use_scalp) and (inst_df is None or inst_df.empty):
                    self._note_skip(f"{symbol}:no_trigger_data")
                    continue

                # Volatility / correlation regime still prefer M5.
                trigger_df = scalp_df if scalp_df is not None and not scalp_df.empty else inst_df
                if trigger_df is None or trigger_df.empty:
                    self._note_skip(f"{symbol}:no_trigger_data")
                    continue

                if bool(self.vol_cfg.get("enabled", True)):
                    # Regime check on M5 (configurable), not S15/M1 trigger ATR —
                    # ultra-scalp trigger bars have tiny ATR/close and would
                    # permanently fail a min ratio calibrated for higher TFs.
                    vol_tf_name = str(self.vol_cfg.get("timeframe", "M5"))
                    try:
                        vol_tf = Timeframe(vol_tf_name)
                    except ValueError:
                        vol_tf = Timeframe.M5
                    vol_df = data_by_tf.get(vol_tf)
                    if vol_df is None or vol_df.empty:
                        vol_df = data_by_tf.get(Timeframe.M5)
                    if vol_df is None or vol_df.empty:
                        vol_df = trigger_df
                    last = vol_df.iloc[-1]
                    atr_raw = last.get("atr", 0)
                    close_raw = last.get("close", 0)
                    try:
                        atr_v = float(atr_raw) if atr_raw is not None else 0.0
                    except (TypeError, ValueError):
                        atr_v = 0.0
                    try:
                        close_v = float(close_raw) if close_raw is not None else 0.0
                    except (TypeError, ValueError):
                        close_v = 0.0
                    allowed, vol_reason, ratio = volatility_decision(
                        atr_v,
                        close_v,
                        min_ratio=float(self.vol_cfg.get("min_atr_close_ratio", 0.00005)),
                        max_ratio=float(self.vol_cfg.get("max_atr_close_ratio", 0.05)),
                    )
                    if not allowed:
                        self._note_skip(f"{symbol}:volatility_{vol_reason}")
                        logger.debug(
                            "{} volatility_guard {}: atr={:.6g} close={:.6g} ratio={} tf={}",
                            symbol,
                            vol_reason,
                            atr_v,
                            close_v,
                            f"{ratio:.6g}" if ratio is not None else "n/a",
                            vol_tf.value,
                        )
                        continue

                # Cross-symbol correlation is optional. With independent_symbol_entries
                # each pair may open regardless of other open tickets (still one per symbol).
                if correlation_guard_enabled(self.settings.risk) and self.open_tickets:
                    m5 = data_by_tf.get(Timeframe.M5)
                    if m5 is not None and not m5.empty:
                        closes_map = {symbol: m5["close"]}
                        for other_sym in list(self.open_tickets):
                            if other_sym == symbol:
                                continue
                            other_m5 = self.connector.fetch_ohlcv(other_sym, Timeframe.M5, count=40)
                            if not other_m5.empty:
                                closes_map[other_sym] = other_m5["close"]
                        open_pos = self.broker.get_open_positions()
                        if correlation_blocks(
                            symbol,
                            m5["close"],
                            open_pos,
                            closes_map,
                            period=int(self.corr_cfg.get("period", 20)),
                            max_abs_corr=float(self.corr_cfg.get("max_abs_corr", 0.80)),
                        ):
                            self._note_skip(f"{symbol}:correlation")
                            continue

                run_scalp = False
                run_institutional = False
                scalp_bar = None
                inst_bar = None
                if self.trade_on_bar_close:
                    if use_scalp and scalp_df is not None and not scalp_df.empty:
                        scalp_bar = last_completed_bar_time(scalp_df)
                        if scalp_bar is not None and self.bar_gate.is_new_bar(
                            f"{symbol}:scalp", scalp_bar
                        ):
                            run_scalp = True
                    if want_institutional and inst_df is not None and not inst_df.empty:
                        inst_bar = last_completed_bar_time(inst_df)
                        if inst_bar is not None and self.bar_gate.is_new_bar(
                            f"{symbol}:inst", inst_bar
                        ):
                            run_institutional = True
                    if not run_scalp and not run_institutional:
                        continue
                else:
                    run_scalp = use_scalp
                    run_institutional = want_institutional

                # Independent engines on their own timeframes (not fallback chain).
                raw_signals = []
                skip_parts: list[str] = []
                if run_scalp:
                    scalp_sig = self.strategy.evaluate(
                        symbol=symbol,
                        data_by_timeframe=data_by_tf,
                        higher_timeframes=self.higher_timeframes,
                        trigger_timeframe=self.trigger_timeframe,
                        spread_pips=spread_pips,
                        run_scalp=True,
                        run_institutional=False,
                    )
                    if scalp_sig.is_actionable:
                        raw_signals.append(scalp_sig)
                    else:
                        skip_parts.append(f"scalp:{(scalp_sig.reason or 'no_signal')}")
                if run_institutional:
                    inst_sig = self.strategy.evaluate(
                        symbol=symbol,
                        data_by_timeframe=data_by_tf,
                        higher_timeframes=self.higher_timeframes,
                        trigger_timeframe=self.trigger_timeframe,
                        spread_pips=spread_pips,
                        run_scalp=False,
                        run_institutional=True,
                    )
                    if inst_sig.is_actionable:
                        raw_signals.append(inst_sig)
                    else:
                        skip_parts.append(f"inst:{(inst_sig.reason or 'no_signal')}")

                if self.trade_on_bar_close:
                    if run_scalp and scalp_bar is not None:
                        self.bar_gate.mark_evaluated(f"{symbol}:scalp", scalp_bar)
                    if run_institutional and inst_bar is not None:
                        self.bar_gate.mark_evaluated(f"{symbol}:inst", inst_bar)

                # Risk/dedup each candidate independently, then pick the strongest.
                viable = []
                for cand in raw_signals:
                    cand_tf = cand.timeframe or self.trigger_timeframe
                    if "ultra_scalp" in (cand.reason or ""):
                        cand_bar = scalp_bar or last_completed_bar_time(
                            scalp_df if scalp_df is not None else trigger_df
                        )
                    else:
                        cand_bar = inst_bar or last_completed_bar_time(
                            inst_df if inst_df is not None else trigger_df
                        )
                    if cand_bar is None:
                        cand_bar = now
                    dedup_key = signal_dedup_key(
                        symbol, cand_tf, cand_bar, cand.signal_type
                    )
                    if self.signal_deduper.already_processed(dedup_key):
                        skip_parts.append(f"{cand_tf.value}:dedup")
                        continue
                    if not self.risk_manager.validate_signal(
                        cand,
                        spread_pips,
                        min_reward_risk_ratio=self._min_rr_for_signal(cand),
                    ):
                        skip_parts.append(f"{cand_tf.value}:risk_reject")
                        continue
                    viable.append((cand, cand_tf, cand_bar, dedup_key))

                if not viable:
                    detail = (
                        "|".join(skip_parts) if skip_parts else "no_signal"
                    ).replace(" ", "_")
                    self._note_skip(f"{symbol}:{detail}")
                    continue

                signal, signal_tf, completed_bar, dedup_key = max(
                    viable,
                    key=lambda item: (
                        float(item[0].risk_reward_ratio),
                        float(item[0].confidence),
                    ),
                )
                if len(viable) > 1:
                    logger.info(
                        "{} parallel entries viable ({}); taking {} on {}",
                        symbol,
                        ",".join(v[0].reason.split(",")[0] for v in viable),
                        signal.reason.split(",")[0],
                        signal_tf.value,
                    )
                equity = self.broker.get_balance()
                volume = self.risk_manager.position_size_for(signal, equity)
                if volume <= 0:
                    self._note_skip(f"{symbol}:zero_volume")
                    continue

                position = self.broker.place_order(signal, volume)
                self.open_tickets[symbol] = position.ticket
                self._position_meta[position.ticket] = {
                    "initial_volume": position.volume,
                    "initial_stop_loss": position.stop_loss,
                    "partial_taken": False,
                    "breakeven_moved": False,
                }
                self.trade_journal.record_open(position)
                self.signal_deduper.mark_processed(dedup_key)
                self.signal_deduper.prune_older_than()
                self._persist_state()
                self._last_trade_opened_at = now
                self.alerts.notify(
                    "Trade opened",
                    (
                        f"{symbol} {signal.signal_type.value} vol={volume:.2f} "
                        f"entry={position.entry_price:.5f} sl={position.stop_loss:.5f} "
                        f"tp={position.take_profit:.5f}"
                    ),
                    AlertLevel.INFO,
                )

            except StaleStopsError as exc:
                # Price moved through SL/TP before fill — skip, do not trip circuit breaker.
                self._note_skip(f"{symbol}:stale_stops")
                logger.warning("Skipping {} — {}", symbol, exc)

            except Exception:  # noqa: BLE001 - one symbol's failure must not kill the loop
                tick_had_failure = True
                failure_context = f"symbol={symbol}"
                self._note_skip(f"{symbol}:exception")
                self.alerts.notify(
                    "Processing error",
                    f"symbol={symbol} — see logs for traceback",
                    AlertLevel.ERROR,
                )
                logger.exception("Error processing {}", symbol)

        self._maybe_log_skip_heartbeat(now)

        if tick_had_failure:
            if self.circuit_breaker.record_failure(failure_context or "tick"):
                self.alerts.notify(
                    "Circuit breaker tripped",
                    f"Halting new entries after {self.circuit_breaker.consecutive_errors} errors",
                    AlertLevel.CRITICAL,
                )
        else:
            self.circuit_breaker.record_success()

    def _fetch_and_enrich(self, symbol: str) -> dict[Timeframe, pd.DataFrame]:
        ind_cfg = self.settings.indicators
        result = {}
        for tf in self.fetch_timeframes:
            df = self.connector.fetch_ohlcv(symbol, tf, count=300)
            if df.empty:
                continue
            df = enrich_with_indicators(
                df,
                ema_period=ind_cfg.get("ema_period_trend", 50),
                rsi_period=ind_cfg.get("rsi_period", 14),
                bb_period=ind_cfg.get("bollinger_period", 20),
                bb_std=ind_cfg.get("bollinger_std_dev", 2.0),
                macd_fast=ind_cfg.get("macd_fast", 12),
                macd_slow=ind_cfg.get("macd_slow", 26),
                macd_signal=ind_cfg.get("macd_signal", 9),
                atr_period=ind_cfg.get("atr_period", 14),
                rvol_period=ind_cfg.get("rvol_period", 20),
            )
            rvol_min = float(self.settings.strategy.get("liquidity_rvol_min", 1.5))
            df = enrich_with_smc(df, rvol_min=rvol_min)
            result[tf] = df
        return result

    def _apply_position_meta(self, position) -> None:
        meta = self._position_meta.get(position.ticket) or {}
        if meta.get("initial_volume") is not None:
            position.initial_volume = float(meta["initial_volume"])
        if meta.get("initial_stop_loss") is not None:
            position.initial_stop_loss = float(meta["initial_stop_loss"])
        position.partial_taken = bool(meta.get("partial_taken", False))
        position.breakeven_moved = bool(meta.get("breakeven_moved", False))

    def _estimate_unrealized_pnl(self) -> float:
        total = 0.0
        for symbol, ticket in list(self.open_tickets.items()):
            positions = self.broker.get_open_positions(symbol)
            position = next((p for p in positions if p.ticket == ticket), None)
            if position is None:
                continue
            try:
                m1 = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=2)
                if m1.empty:
                    continue
                price = float(m1.iloc[-1]["close"])
                spec = self.settings.symbols_raw[symbol]
                pip_size = float(spec["pip_size"])
                pip_value = float(spec["pip_value_per_lot"])
                diff = (
                    price - position.entry_price
                    if position.direction == SignalType.BUY
                    else position.entry_price - price
                )
                total += (diff / pip_size) * pip_value * position.volume
            except Exception:  # noqa: BLE001
                continue
        return total

    def _close_all_positions(self, now: datetime, *, reason: str) -> None:
        for symbol, ticket in list(self.open_tickets.items()):
            try:
                trade = self.broker.close_position(ticket)
                self.risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=now)
                if self.three_strikes_enabled:
                    self.three_strikes.record_result(symbol, trade.pnl, at=now)
                self.trade_journal.record_close(trade, ticket=ticket)
                self._position_meta.pop(ticket, None)
                self.open_tickets.pop(symbol, None)
                logger.warning("Force-closed {} ticket={} reason={}", symbol, ticket, reason)
            except Exception:  # noqa: BLE001
                logger.exception("Failed force-close {} ticket={}", symbol, ticket)
        self._persist_state()

    def _manage_open_position(self, symbol: str, now: datetime) -> None:
        ticket = self.open_tickets.get(symbol)
        if ticket is None:
            return

        positions = self.broker.get_open_positions(symbol)
        position = next((p for p in positions if p.ticket == ticket), None)
        if position is None:
            self._on_position_closed_externally(symbol, ticket, now)
            return
        self._apply_position_meta(position)

        m1_df = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=40)
        if m1_df.empty:
            return
        m1_df = enrich_with_indicators(
            m1_df, atr_period=self.settings.indicators.get("atr_period", 14)
        )

        bar = m1_df.iloc[-1]
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        current_price = float(bar["close"])

        if self.mode == "paper":
            hit = check_sl_tp_hit(position, bar_high, bar_low)
            if hit.triggered:
                exit_price = exit_price_for_hit(position, hit)
                trade = self.broker.close_position(
                    ticket,
                    exit_price=exit_price,
                    at=now,
                    reason=hit.exit_reason(),
                )
                self.risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=now)
                if self.three_strikes_enabled:
                    self.three_strikes.record_result(symbol, trade.pnl, at=now)
                self.trade_journal.record_close(trade, ticket=ticket)
                self.open_tickets.pop(symbol, None)
                self._position_meta.pop(ticket, None)
                self._persist_state()
                logger.info(
                    "Paper {} closed via {} pnl={:.2f}",
                    symbol,
                    hit.exit_reason(),
                    trade.pnl,
                )
                self.alerts.notify(
                    "Trade closed",
                    f"{symbol} {hit.exit_reason()} pnl={trade.pnl:.2f}",
                    AlertLevel.INFO,
                )
                return

        pip_size = float(self.settings.symbols_raw[symbol]["pip_size"])
        spread_pips = self.broker.get_current_spread_pips(symbol)
        spread_price = spread_pips * pip_size
        action = manage_open_position(
            position,
            current_price,
            m1_df,
            spread_price=spread_price,
            partial_r=float(self.partial_cfg.get("r_multiple", 1.2)),
            chandelier_lookback=int(self.chandelier_cfg.get("lookback", 22)),
            chandelier_atr_multiple=float(self.chandelier_cfg.get("atr_multiple", 2.5)),
        )

        if bool(self.partial_cfg.get("enabled", True)) and action.partial is not None:
            try:
                trade = self.broker.close_partial(ticket, action.partial.close_volume)
                self.risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=now)
                self.trade_journal.record_close(trade, ticket=ticket)
                meta = self._position_meta.setdefault(ticket, {})
                meta["partial_taken"] = True
                meta["breakeven_moved"] = True
                position.partial_taken = True
                position.breakeven_moved = True
                if action.partial.new_stop_loss is not None and self.broker.modify_sl_tp(
                    ticket, action.partial.new_stop_loss, position.take_profit
                ):
                    position.stop_loss = action.partial.new_stop_loss
                logger.info(
                    "Partial TP {} ticket={} vol={} pnl={:.2f}",
                    symbol,
                    ticket,
                    action.partial.close_volume,
                    trade.pnl,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Partial TP failed for {} ticket={}", symbol, ticket)

        new_sl = action.new_stop_loss
        if new_sl is None and not (
            bool(self.chandelier_cfg.get("enabled", True)) and position.partial_taken
        ):
            atr_value = float(m1_df.iloc[-1]["atr"])
            new_sl = apply_breakeven_or_trailing(
                self.risk_manager, position, current_price, atr_value
            )
        if new_sl is not None and self.broker.modify_sl_tp(ticket, new_sl, position.take_profit):
            if abs(new_sl - position.entry_price) < pip_size * 2:
                position.breakeven_moved = True
                self._position_meta.setdefault(ticket, {})["breakeven_moved"] = True
            position.stop_loss = new_sl

    def _on_position_closed_externally(self, symbol: str, ticket: int, now: datetime) -> None:
        pnl: float | None = None
        if self.mode == "live" and isinstance(self.broker, (MT5Broker, OANDABroker)):
            pnl = self.broker.fetch_closed_pnl(ticket)

        self.trade_journal.record_external_close(ticket, symbol, pnl, at=now)

        if pnl is not None:
            self.risk_manager.daily_tracker.record_trade_pnl(pnl, at=now)
            if self.three_strikes_enabled:
                self.three_strikes.record_result(symbol, pnl, at=now)
            logger.info("Position {} ticket={} closed externally, pnl={:.2f}", symbol, ticket, pnl)
            self.alerts.notify(
                "Trade closed",
                f"{symbol} external close pnl={pnl:.2f}",
                AlertLevel.INFO,
            )
        else:
            logger.info("Position {} ticket={} closed externally (PnL unknown)", symbol, ticket)
            self.alerts.notify(
                "Trade closed",
                f"{symbol} external close (PnL unknown)",
                AlertLevel.INFO,
            )

        self.open_tickets.pop(symbol, None)
        self._position_meta.pop(ticket, None)
        self._persist_state()


def settings_config_dir():
    from chronoscalp.config import CONFIG_DIR

    return CONFIG_DIR


def main(mode: str = "paper") -> None:
    settings = get_settings()
    bot = TradingBot(settings, mode=mode)
    bot.start()


if __name__ == "__main__":
    main()
