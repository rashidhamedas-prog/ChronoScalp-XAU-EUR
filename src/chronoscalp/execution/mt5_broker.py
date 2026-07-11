"""MetaTrader5 broker implementation. Windows-only — see
docs/ARCHITECTURE.md and chronoscalp.data.mt5_connector for details.
"""

from __future__ import annotations

from datetime import datetime, timezone

from chronoscalp.data.mt5_connector import MT5Connector, _require_windows
from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position, Signal, SignalType, TradeResult


class MT5Broker:
    """Implements the `Broker` protocol (execution/broker.py) against a real
    or demo MT5 account. Requires a Windows host with the MT5 terminal
    installed and logged in (see .env.example: MT5_LOGIN/MT5_PASSWORD/MT5_SERVER)."""

    def __init__(self, login: int, password: str, server: str, terminal_path: str = "") -> None:
        self._connector = MT5Connector(login, password, server, terminal_path)

    def connect(self) -> bool:
        return self._connector.connect()

    def get_balance(self) -> float:
        _require_windows()
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        return float(info.equity)

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        _require_windows()
        import MetaTrader5 as mt5

        raw_positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if raw_positions is None:
            return []

        positions = []
        for p in raw_positions:
            positions.append(
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    direction=SignalType.BUY if p.type == mt5.POSITION_TYPE_BUY else SignalType.SELL,
                    volume=p.volume,
                    entry_price=p.price_open,
                    stop_loss=p.sl,
                    take_profit=p.tp,
                    open_time=datetime.fromtimestamp(p.time, tz=timezone.utc),
                )
            )
        return positions

    def get_current_spread_pips(self, symbol: str) -> float:
        spread_points = self._connector.current_spread_points(symbol)
        return float(spread_points) if spread_points is not None else float("inf")

    def place_order(self, signal: Signal, volume: float) -> Position:
        _require_windows()
        import MetaTrader5 as mt5

        order_type = mt5.ORDER_TYPE_BUY if signal.signal_type == SignalType.BUY else mt5.ORDER_TYPE_SELL
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
            "magic": 20260711,
            "comment": f"chronoscalp:{signal.reason[:40]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order_send failed: {result}")

        logger.info("Order placed: {} {} vol={} @ {}", signal.symbol, signal.signal_type.value, volume, price)
        return Position(
            ticket=result.order,
            symbol=signal.symbol,
            direction=signal.signal_type,
            volume=volume,
            entry_price=price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            open_time=datetime.now(tz=timezone.utc),
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
        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "position": ticket,
            "price": close_price,
            "deviation": 10,
            "magic": 20260711,
            "comment": "chronoscalp:close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 close order_send failed: {result}")

        direction = SignalType.BUY if position.type == mt5.POSITION_TYPE_BUY else SignalType.SELL
        pnl = position.profit
        return TradeResult(
            symbol=position.symbol,
            direction=direction,
            entry_price=position.price_open,
            exit_price=close_price,
            volume=position.volume,
            open_time=datetime.fromtimestamp(position.time, tz=timezone.utc),
            close_time=datetime.now(tz=timezone.utc),
            pnl=pnl,
        )
