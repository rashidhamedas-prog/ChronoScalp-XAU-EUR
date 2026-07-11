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

from chronoscalp.config import Settings, get_settings
from chronoscalp.data.mt5_connector import MT5Connector
from chronoscalp.execution.mt5_broker import MT5Broker
from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.logging_setup import logger
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

        self.connector = MT5Connector(
            login=settings.secrets.mt5_login,
            password=settings.secrets.mt5_password,
            server=settings.secrets.mt5_server,
            terminal_path=settings.secrets.mt5_terminal_path,
        )
        self.broker = (
            MT5Broker(
                login=settings.secrets.mt5_login,
                password=settings.secrets.mt5_password,
                server=settings.secrets.mt5_server,
                terminal_path=settings.secrets.mt5_terminal_path,
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
        self.open_tickets: dict[str, int] = {}

    def start(self) -> None:
        if not self.connector.connect():
            raise RuntimeError("Failed to connect to MT5 for market data. Is the terminal running and logged in?")
        if not self.broker.connect():
            raise RuntimeError("Failed to connect broker")

        poll_seconds = int(self.settings.execution.get("poll_interval_seconds", 5))
        logger.info("ChronoScalp started in {} mode, polling every {}s", self.mode, poll_seconds)

        try:
            while True:
                self.tick()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            logger.info("Shutdown requested, stopping.")
        finally:
            self.connector.shutdown()

    def tick(self) -> None:
        now = datetime.now(tz=timezone.utc)

        for symbol in self.settings.symbols:
            try:
                self._manage_open_position(symbol)
                if symbol in self.open_tickets:
                    continue  # one position per symbol at a time

                if not self.session_filter.is_within_session(now):
                    continue
                if self.news_filter.is_blackout(now):
                    continue

                data_by_tf = self._fetch_and_enrich(symbol)
                signal = self.strategy.evaluate(
                    symbol=symbol,
                    data_by_timeframe=data_by_tf,
                    higher_timeframes=self.higher_timeframes,
                    trigger_timeframe=self.trigger_timeframe,
                )
                if signal.signal_type == SignalType.NONE:
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

            except Exception:  # noqa: BLE001 - one symbol's failure must not kill the loop
                logger.exception("Error processing {}", symbol)

    def _fetch_and_enrich(self, symbol: str) -> dict[Timeframe, "pd.DataFrame"]:
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

    def _manage_open_position(self, symbol: str) -> None:
        ticket = self.open_tickets.get(symbol)
        if ticket is None:
            return

        positions = self.broker.get_open_positions(symbol)
        position = next((p for p in positions if p.ticket == ticket), None)
        if position is None:
            self.open_tickets.pop(symbol, None)  # closed externally (SL/TP hit, manual close)
            return

        tick_df = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=self.settings.indicators.get("atr_period", 14) + 5)
        if tick_df.empty:
            return
        current_price = float(tick_df.iloc[-1]["close"])
        atr_value = float(
            enrich_with_indicators(tick_df, atr_period=self.settings.indicators.get("atr_period", 14)).iloc[-1]["atr"]
        )

        new_sl = self.risk_manager.breakeven_stop(position, current_price)
        if new_sl is not None:
            if self.broker.modify_sl_tp(ticket, new_sl, position.take_profit):
                position.breakeven_moved = True
                position.stop_loss = new_sl
            return

        trailing_sl = self.risk_manager.trailing_stop(position, current_price, atr_value)
        if trailing_sl is not None:
            self.broker.modify_sl_tp(ticket, trailing_sl, position.take_profit)
            position.stop_loss = trailing_sl


def settings_config_dir():
    from chronoscalp.config import CONFIG_DIR

    return CONFIG_DIR


def main(mode: str = "paper") -> None:
    settings = get_settings()
    bot = TradingBot(settings, mode=mode)
    bot.start()


if __name__ == "__main__":
    main()
