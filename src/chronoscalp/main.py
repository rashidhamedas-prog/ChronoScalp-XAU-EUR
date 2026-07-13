"""Live/paper trading orchestration loop.

Requires a Windows host with the MT5 terminal installed and logged in (data
fetch goes through MT5Connector regardless of --mode, since that's the only
implemented real-time data source — see docs/ARCHITECTURE.md). On Linux/macOS
use scripts/run_backtest.py instead, which reads CSV history and needs no
broker connection at all.

`--mode live` additionally requires CHRONOSCALP_CONFIRM_LIVE=yes in .env —
see CLAUDE.md rule #2. Do not remove this gate.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from chronoscalp.config import Settings, get_settings
from chronoscalp.data.mt5_connector import MT5Connector
from chronoscalp.execution.mt5_broker import MT5Broker
from chronoscalp.execution.mt5_utils import CHRONOSCALP_MAGIC
from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.execution.position_logic import (
    apply_breakeven_or_trailing,
    check_sl_tp_hit,
    exit_price_for_hit,
)
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.logging_setup import logger
from chronoscalp.orchestration.bar_scheduler import (
    BarCloseGate,
    SignalDeduper,
    last_completed_bar_time,
    signal_dedup_key,
)
from chronoscalp.orchestration.state_store import TradingStateStore
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy
from chronoscalp.utils.types import SignalType, Timeframe

ALL_TIMEFRAMES = [Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M10]


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
        self.higher_timeframes = [Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]]
        self.trigger_timeframe = Timeframe(settings.raw["timeframes"]["entry_trigger"][-1])
        self.trade_on_bar_close = bool(settings.execution.get("trade_on_bar_close_only", True))
        self.max_concurrent = int(settings.risk.get("max_concurrent_positions", 2))
        self.magic = int(settings.execution.get("magic_number", CHRONOSCALP_MAGIC))

        self.connector = MT5Connector(
            login=settings.secrets.mt5_login,
            password=settings.secrets.mt5_password,
            server=settings.secrets.mt5_server,
            terminal_path=settings.secrets.mt5_terminal_path,
        )
        self.broker = (
            MT5Broker(
                connector=self.connector,
                login=settings.secrets.mt5_login,
                password=settings.secrets.mt5_password,
                server=settings.secrets.mt5_server,
                terminal_path=settings.secrets.mt5_terminal_path,
                symbols_cfg=settings.symbols_raw,
                magic=self.magic,
            )
            if mode == "live"
            else PaperBroker(
                symbols_cfg=settings.symbols_raw,
                starting_balance=float(settings.backtest.get("initial_balance", 10_000)),
                slippage_pips=float(settings.execution.get("slippage_pips", 0.5)),
            )
        )

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

        state_path = Path(settings.execution.get("state_dir", "data/state")) / f"trading_state_{mode}.json"
        self.state_store = TradingStateStore(state_path)
        self.state_store.load()

        self.open_tickets: dict[str, int] = dict(self.state_store.state.open_tickets)
        self.bar_gate = BarCloseGate()
        for symbol, bar_iso in self.state_store.state.last_evaluated_bars.items():
            try:
                self.bar_gate.load_last_bar(symbol, datetime.fromisoformat(bar_iso))
            except ValueError:
                logger.warning("Skipping invalid last_evaluated_bar for {}: {}", symbol, bar_iso)

        self.signal_deduper = SignalDeduper(set(self.state_store.state.processed_signals))

    def start(self) -> None:
        if not self.connector.connect():
            raise RuntimeError("Failed to connect to MT5 for market data. Is the terminal running and logged in?")
        if not self.broker.connect():
            raise RuntimeError("Failed to connect broker")

        self._reconcile_state_with_broker()

        poll_seconds = int(self.settings.execution.get("poll_interval_seconds", 5))
        logger.info(
            "ChronoScalp started in {} mode, polling every {}s (bar_close_only={})",
            self.mode,
            poll_seconds,
            self.trade_on_bar_close,
        )

        try:
            while True:
                self.tick()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            logger.info("Shutdown requested, stopping.")
        finally:
            self._persist_state()
            self.connector.shutdown()

    def _reconcile_state_with_broker(self) -> None:
        if self.mode == "live":
            managed = self.broker.get_managed_positions()
        else:
            managed = self.broker.get_open_positions()

        broker_map = {p.symbol: p.ticket for p in managed}
        self.state_store.reconcile_open_tickets(broker_map)
        self.open_tickets = dict(self.state_store.state.open_tickets)

    def _persist_state(self) -> None:
        self.state_store.state.open_tickets = dict(self.open_tickets)
        self.state_store.state.processed_signals = sorted(self.signal_deduper.processed_keys)
        self.state_store.state.last_evaluated_bars = {
            sym: ts.isoformat() for sym, ts in self.bar_gate.last_evaluated_bars().items()
        }
        self.state_store.save()

    def tick(self) -> None:
        now = datetime.now(tz=timezone.utc)

        for symbol in self.settings.symbols:
            try:
                self._manage_open_position(symbol, now)
                if symbol in self.open_tickets:
                    continue

                if len(self.open_tickets) >= self.max_concurrent:
                    continue

                if not self.session_filter.is_within_session(now):
                    continue
                if self.news_filter.is_blackout(now):
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

                dedup_key = signal_dedup_key(symbol, self.trigger_timeframe, completed_bar, signal.signal_type)
                if self.signal_deduper.already_processed(dedup_key):
                    continue

                spread_pips = self.broker.get_current_spread_pips(symbol)
                if not self.risk_manager.validate_signal(signal, spread_pips):
                    continue

                equity = self.broker.get_balance()
                volume = self.risk_manager.position_size_for(signal, equity)
                if volume <= 0:
                    continue

                position = self.broker.place_order(signal, volume)
                self.open_tickets[symbol] = position.ticket
                self.signal_deduper.mark_processed(dedup_key)
                self.signal_deduper.prune_older_than()
                self._persist_state()

            except Exception:  # noqa: BLE001 - one symbol's failure must not kill the loop
                logger.exception("Error processing {}", symbol)

    def _fetch_and_enrich(self, symbol: str) -> dict[Timeframe, pd.DataFrame]:
        ind_cfg = self.settings.indicators
        result = {}
        for tf in ALL_TIMEFRAMES:
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
            )
            df = enrich_with_smc(df)
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
                self.open_tickets.pop(symbol, None)
                self._persist_state()
                logger.info(
                    "Paper {} closed via {} pnl={:.2f}",
                    symbol,
                    hit.exit_reason(),
                    trade.pnl,
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
        if self.mode == "live" and isinstance(self.broker, MT5Broker):
            pnl = self.broker.fetch_closed_pnl(ticket)

        if pnl is not None:
            self.risk_manager.daily_tracker.record_trade_pnl(pnl, at=now)
            logger.info("Position {} ticket={} closed externally, pnl={:.2f}", symbol, ticket, pnl)
        else:
            logger.info("Position {} ticket={} closed externally (PnL unknown)", symbol, ticket)

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
