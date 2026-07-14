"""MetaTrader5 broker implementation. Windows-only — see
docs/ARCHITECTURE.md and chronoscalp.data.mt5_connector for details.
"""

from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.data.mt5_connector import MT5Connector, _require_windows
from chronoscalp.execution.mt5_utils import (
    CHRONOSCALP_MAGIC,
    fetch_closed_position_pnl,
    find_managed_position_ticket,
    resolve_order_filling_mode,
    spread_points_to_pips,
)
from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position, Signal, SignalType, TradeResult


class MT5Broker:
    """Implements the `Broker` protocol (execution/broker.py) against a real
    or demo MT5 account. Requires a Windows host with the MT5 terminal
    installed and logged in (see .env.example: MT5_LOGIN/MT5_PASSWORD/MT5_SERVER)."""

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        terminal_path: str = "",
        connector: MT5Connector | None = None,
        symbols_cfg: dict | None = None,
        magic: int = CHRONOSCALP_MAGIC,
    ) -> None:
        self._connector = connector or MT5Connector(login, password, server, terminal_path)
        self._owns_connector = connector is None
        self._symbols_cfg = symbols_cfg or {}
        self._magic = magic

    def connect(self) -> bool:
        if self._connector.is_connected:
            return True
        if self._owns_connector:
            return self._connector.connect()
        return self._connector.is_connected

    def get_balance(self) -> float:
        _require_windows()
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        return float(info.equity)

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        return self.get_managed_positions(symbol=symbol)

    def get_managed_positions(self, symbol: str | None = None) -> list[Position]:
        """Open positions placed by this bot (filtered by magic number)."""
        _require_windows()
        import MetaTrader5 as mt5

        raw_positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if raw_positions is None:
            return []

        positions = []
        for p in raw_positions:
            if p.magic != self._magic:
                continue
            positions.append(
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    direction=(
                        SignalType.BUY if p.type == mt5.POSITION_TYPE_BUY else SignalType.SELL
                    ),
                    volume=p.volume,
                    entry_price=p.price_open,
                    stop_loss=p.sl,
                    take_profit=p.tp,
                    open_time=datetime.fromtimestamp(p.time, tz=UTC),
                )
            )
        return positions

    def get_current_spread_pips(self, symbol: str) -> float:
        spread_points = self._connector.current_spread_points(symbol)
        if spread_points is None:
            return float("inf")

        spec = self._symbols_cfg.get(symbol, {})
        pip_size = float(spec.get("pip_size", 0.0))
        if pip_size <= 0:
            logger.warning(
                "No pip_size for {} in symbols.yaml — returning raw spread points", symbol
            )
            return float(spread_points)

        point = self._connector.symbol_point(symbol)
        if point is None or point <= 0:
            logger.warning("Could not read MT5 point for {} — returning raw spread points", symbol)
            return float(spread_points)

        return spread_points_to_pips(float(spread_points), point, pip_size)

    def place_order(self, signal: Signal, volume: float) -> Position:
        _require_windows()
        import MetaTrader5 as mt5

        order_type = (
            mt5.ORDER_TYPE_BUY if signal.signal_type == SignalType.BUY else mt5.ORDER_TYPE_SELL
        )
        tick = mt5.symbol_info_tick(signal.symbol)
        if tick is None:
            raise RuntimeError(f"No tick data for {signal.symbol}: {mt5.last_error()}")
        price = tick.ask if signal.signal_type == SignalType.BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": signal.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "deviation": 10,
            "magic": self._magic,
            "comment": f"chronoscalp:{signal.reason[:40]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": resolve_order_filling_mode(signal.symbol),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order_send failed: {result}")

        ticket = find_managed_position_ticket(signal.symbol, magic=self._magic)
        if ticket is None:
            raise RuntimeError(
                f"Order reported done but no managed position found for {signal.symbol} "
                f"(magic={self._magic})"
            )

        logger.info(
            "Order placed: {} {} vol={} @ {} ticket={}",
            signal.symbol,
            signal.signal_type.value,
            volume,
            price,
            ticket,
        )
        return Position(
            ticket=ticket,
            symbol=signal.symbol,
            direction=signal.signal_type,
            volume=volume,
            entry_price=price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            open_time=datetime.now(tz=UTC),
        )

    def modify_sl_tp(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        _require_windows()
        import MetaTrader5 as mt5

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.warning("modify_sl_tp: no open position for ticket {}", ticket)
            return False
        position = positions[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": stop_loss,
            "tp": take_profit,
        }
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        if not ok:
            logger.warning("modify_sl_tp failed for ticket {}: {}", ticket, result)
        return ok

    def close_position(self, ticket: int) -> TradeResult:
        _require_windows()
        import MetaTrader5 as mt5

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise RuntimeError(f"No open position for ticket {ticket}")
        position = positions[0]

        tick = mt5.symbol_info_tick(position.symbol)
        close_price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask
        order_type = (
            mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "position": ticket,
            "price": close_price,
            "deviation": 10,
            "magic": self._magic,
            "comment": "chronoscalp:close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": resolve_order_filling_mode(position.symbol),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 close order_send failed: {result}")

        direction = SignalType.BUY if position.type == mt5.POSITION_TYPE_BUY else SignalType.SELL
        pnl = float(position.profit)
        return TradeResult(
            symbol=position.symbol,
            direction=direction,
            entry_price=position.price_open,
            exit_price=close_price,
            volume=position.volume,
            open_time=datetime.fromtimestamp(position.time, tz=UTC),
            close_time=datetime.now(tz=UTC),
            pnl=pnl,
        )

    def fetch_closed_pnl(self, ticket: int) -> float | None:
        """Realized P&L after the position was closed externally (SL/TP on broker)."""
        return fetch_closed_position_pnl(ticket)
