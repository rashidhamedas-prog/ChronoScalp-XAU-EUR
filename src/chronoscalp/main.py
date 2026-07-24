"""Live/paper trading orchestration loop.

Deployment targets:
- **Windows + MT5** — ``execution.broker: mt5``, ``data_source: mt5`` (or auto)
- **Linux VPS (e.g. Netherlands)** — ``execution.broker: oanda``, ``data_source: oanda``
  See docs/DEPLOY_NL_VPS.md. No MetaTrader5 terminal required.
- **Paper on any OS** — ``execution.broker: paper`` with ``data_source: oanda`` or ``mt5``

``--mode live`` requires CHRONOSCALP_CONFIRM_LIVE=yes in .env — see CLAUDE.md rule #2.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from chronoscalp.config import Settings, get_settings
from chronoscalp.data.spread_sampler import SpreadSampler
from chronoscalp.execution.mt5_broker import MT5Broker
from chronoscalp.execution.oanda_broker import OANDABroker
from chronoscalp.execution.position_logic import (
    apply_breakeven_or_trailing,
    check_sl_tp_hit,
    exit_price_for_hit,
)
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
from chronoscalp.orchestration.trade_journal import TradeJournal, journal_path_for
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy, resolve_enabled_strategies
from chronoscalp.utils.types import SignalType, Timeframe

STANDARD_TIMEFRAMES = [Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M10]


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
        _, _, use_ultra_scalp = resolve_enabled_strategies(settings.strategy)
        self.use_ultra_scalp = use_ultra_scalp
        scalp_tf = (settings.raw.get("timeframes") or {}).get("ultra_scalp") or {}
        if use_ultra_scalp:
            higher_raw = scalp_tf.get("higher_trend") or ["M5", "M1"]
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
        self.max_concurrent = int(settings.risk.get("max_concurrent_positions", 2))
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
        self.strategy = MultiTimeframeStrategy(settings.strategy, settings.indicators)
        self.risk_manager = RiskManager(
            risk_cfg=settings.risk,
            spread_cfg=settings.spread_filter,
            symbols_cfg=settings.symbols_raw,
            starting_equity=float(settings.backtest.get("initial_balance", 10_000)),
        )

        state_path = self.state_dir / f"trading_state_{mode}.json"
        self.state_store = TradingStateStore(state_path)
        self.state_store.load()

        self.trade_journal = TradeJournal(journal_path_for(self.state_dir, mode), mode=mode)
        self.trade_journal.load()

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

        broker_map = {p.symbol: p.ticket for p in managed}
        self.state_store.reconcile_open_tickets(broker_map)
        self.open_tickets = dict(self.state_store.state.open_tickets)
        self.trade_journal.sync_open_from_broker(managed)

        if alert_on_change and previous != self.open_tickets:
            self.alerts.notify(
                "State reconciled",
                f"before={previous} after={self.open_tickets}",
                AlertLevel.WARNING,
            )

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
        daily_limit_hit = self.risk_manager.daily_tracker.daily_loss_limit_hit(at=now)
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
        )

        for symbol in self.settings.symbols:
            try:
                spread_pips = self.broker.get_current_spread_pips(symbol)
                self.spread_sampler.record(symbol, spread_pips, at=now)

                self._manage_open_position(symbol, now)
                if not allow_new_entries:
                    continue
                if symbol in self.open_tickets:
                    continue

                if len(self.open_tickets) >= self.max_concurrent:
                    continue

                if not self.session_filter.is_within_session(now, symbol=symbol):
                    continue
                if self.news_filter.is_blackout(now, currency=self._news_currency(symbol)):
                    continue

                data_by_tf = self._fetch_and_enrich(symbol)
                trigger_df = data_by_tf.get(self.trigger_timeframe)
                if trigger_df is None or trigger_df.empty:
                    continue

                completed_bar = last_completed_bar_time(trigger_df)
                if self.trade_on_bar_close:
                    if completed_bar is None:
                        continue
                    if not self.bar_gate.is_new_bar(symbol, completed_bar):
                        continue

                signal = self.strategy.evaluate(
                    symbol=symbol,
                    data_by_timeframe=data_by_tf,
                    higher_timeframes=self.higher_timeframes,
                    trigger_timeframe=self.trigger_timeframe,
                )

                if self.trade_on_bar_close and completed_bar is not None:
                    self.bar_gate.mark_evaluated(symbol, completed_bar)

                if signal.signal_type == SignalType.NONE:
                    continue

                if completed_bar is None:
                    completed_bar = last_completed_bar_time(trigger_df) or now

                dedup_key = signal_dedup_key(
                    symbol, self.trigger_timeframe, completed_bar, signal.signal_type
                )
                if self.signal_deduper.already_processed(dedup_key):
                    continue

                if not self.risk_manager.validate_signal(signal, spread_pips):
                    continue

                equity = self.broker.get_balance()
                volume = self.risk_manager.position_size_for(signal, equity)
                if volume <= 0:
                    continue

                position = self.broker.place_order(signal, volume)
                self.open_tickets[symbol] = position.ticket
                self.trade_journal.record_open(position)
                self.signal_deduper.mark_processed(dedup_key)
                self.signal_deduper.prune_older_than()
                self._persist_state()
                self.alerts.notify(
                    "Trade opened",
                    (
                        f"{symbol} {signal.signal_type.value} vol={volume:.2f} "
                        f"entry={position.entry_price:.5f} sl={position.stop_loss:.5f} "
                        f"tp={position.take_profit:.5f}"
                    ),
                    AlertLevel.INFO,
                )

            except Exception:  # noqa: BLE001 - one symbol's failure must not kill the loop
                tick_had_failure = True
                failure_context = f"symbol={symbol}"
                self.alerts.notify(
                    "Processing error",
                    f"symbol={symbol} — see logs for traceback",
                    AlertLevel.ERROR,
                )
                logger.exception("Error processing {}", symbol)

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

    def _manage_open_position(self, symbol: str, now: datetime) -> None:
        ticket = self.open_tickets.get(symbol)
        if ticket is None:
            return

        positions = self.broker.get_open_positions(symbol)
        position = next((p for p in positions if p.ticket == ticket), None)
        if position is None:
            self._on_position_closed_externally(symbol, ticket, now)
            return

        m1_df = self.connector.fetch_ohlcv(
            symbol, Timeframe.M1, count=self.settings.indicators.get("atr_period", 14) + 5
        )
        if m1_df.empty:
            return

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
                self.trade_journal.record_close(trade, ticket=ticket)
                self.open_tickets.pop(symbol, None)
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

        atr_value = float(
            enrich_with_indicators(
                m1_df, atr_period=self.settings.indicators.get("atr_period", 14)
            ).iloc[-1]["atr"]
        )

        new_sl = apply_breakeven_or_trailing(self.risk_manager, position, current_price, atr_value)
        if new_sl is not None and self.broker.modify_sl_tp(ticket, new_sl, position.take_profit):
            if new_sl == position.entry_price:
                position.breakeven_moved = True
            position.stop_loss = new_sl

    def _on_position_closed_externally(self, symbol: str, ticket: int, now: datetime) -> None:
        pnl: float | None = None
        if self.mode == "live" and isinstance(self.broker, (MT5Broker, OANDABroker)):
            pnl = self.broker.fetch_closed_pnl(ticket)

        self.trade_journal.record_external_close(ticket, symbol, pnl, at=now)

        if pnl is not None:
            self.risk_manager.daily_tracker.record_trade_pnl(pnl, at=now)
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
