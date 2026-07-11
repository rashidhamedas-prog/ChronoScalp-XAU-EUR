"""In-memory simulated broker — runs on any OS, no MT5 terminal required.

Used for paper trading (live data feed, simulated fills) and as the fill
model reused by backtest/engine.py. Applies configured spread + slippage so
paper results are a meaningful approximation of live execution costs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position, Signal, SignalType, TradeResult


class PaperBroker:
    """Implements the `Broker` protocol (execution/broker.py) with simulated
    fills. Not a subclass — Python's structural `Protocol` typing means this
    satisfies `Broker` by having matching methods."""

    def __init__(self, symbols_cfg: dict, starting_balance: float = 10_000.0, slippage_pips: float = 0.5) -> None:
        self.symbols_cfg = symbols_cfg
        self.balance = starting_balance
        self.slippage_pips = slippage_pips
        self._positions: dict[int, Position] = {}
        self._next_ticket = 1

    def connect(self) -> bool:
        logger.info("PaperBroker ready (starting_balance={:.2f})", self.balance)
        return True

    def get_balance(self) -> float:
        return self.balance

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        positions = list(self._positions.values())
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        return positions

    def get_current_spread_pips(self, symbol: str) -> float:
        return float(self.symbols_cfg[symbol]["typical_spread_pips"])

    def place_order(self, signal: Signal, volume: float, fill_price: float | None = None) -> Position:
        spec = self.symbols_cfg[signal.symbol]
        pip_size = spec["pip_size"]
        slip = self.slippage_pips * pip_size
        base_price = fill_price if fill_price is not None else signal.entry_price
        fill = base_price + slip if signal.signal_type == SignalType.BUY else base_price - slip

        position = Position(
            ticket=self._next_ticket,
            symbol=signal.symbol,
            direction=signal.signal_type,
            volume=volume,
            entry_price=fill,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            open_time=signal.timestamp if signal.timestamp else datetime.now(tz=timezone.utc),
        )
        self._positions[position.ticket] = position
        self._next_ticket += 1
        logger.info(
            "[paper] Opened {} {} vol={} @ {:.5f} (SL={:.5f} TP={:.5f})",
            signal.symbol, signal.signal_type.value, volume, fill, signal.stop_loss, signal.take_profit,
        )
        return position

    def modify_sl_tp(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        position = self._positions.get(ticket)
        if position is None:
            return False
        position.stop_loss = stop_loss
        position.take_profit = take_profit
        return True

    def close_position(self, ticket: int, exit_price: float | None = None, at: datetime | None = None, reason: str = "manual") -> TradeResult:
        position = self._positions.pop(ticket, None)
        if position is None:
            raise RuntimeError(f"No open paper position for ticket {ticket}")

        spec = self.symbols_cfg[position.symbol]
        close_price = exit_price if exit_price is not None else position.entry_price
        pip_size = spec["pip_size"]
        pip_value_per_lot = spec["pip_value_per_lot"]

        price_diff = (
            close_price - position.entry_price
            if position.direction == SignalType.BUY
            else position.entry_price - close_price
        )
        pnl = (price_diff / pip_size) * pip_value_per_lot * position.volume
        self.balance += pnl

        risk = abs(position.entry_price - position.stop_loss)
        r_multiple = round(price_diff / risk, 3) if risk else 0.0

        result = TradeResult(
            symbol=position.symbol,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=close_price,
            volume=position.volume,
            open_time=position.open_time,
            close_time=at or datetime.now(tz=timezone.utc),
            pnl=pnl,
            r_multiple=r_multiple,
            exit_reason=reason,
        )
        logger.info(
            "[paper] Closed {} {} @ {:.5f} pnl={:.2f} r={:.2f} reason={}",
            position.symbol, position.direction.value, close_price, pnl, r_multiple, reason,
        )
        return result
