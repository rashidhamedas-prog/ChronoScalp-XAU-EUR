"""In-memory simulated broker — runs on any OS, no MT5 terminal required.

Used for paper trading (live data feed, simulated fills) and as the fill
model reused by backtest/engine.py. Applies configured spread + slippage so
paper results are a meaningful approximation of live execution costs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.logging_setup import logger
from chronoscalp.utils.strategy_tags import resolve_strategy_tag
from chronoscalp.utils.types import (
    PendingOrder,
    PendingOrderSide,
    Position,
    Quote,
    Signal,
    SignalType,
    TradeResult,
)


class PaperBroker:
    """Implements the `Broker` protocol (execution/broker.py) with simulated
    fills. Not a subclass — Python's structural `Protocol` typing means this
    satisfies `Broker` by having matching methods."""

    def __init__(
        self, symbols_cfg: dict, starting_balance: float = 10_000.0, slippage_pips: float = 0.5
    ) -> None:
        self.symbols_cfg = symbols_cfg
        self.balance = starting_balance
        self.slippage_pips = slippage_pips
        self._positions: dict[int, Position] = {}
        self._pending: dict[int, PendingOrder] = {}
        self._quotes: dict[str, Quote] = {}
        self._next_ticket = 1

    def connect(self) -> bool:
        logger.info("PaperBroker ready (starting_balance={:.2f})", self.balance)
        return True

    def get_balance(self) -> float:
        return self.balance

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        if symbol:
            self._maybe_fill_pendings(symbol)
        else:
            for sym in {o.symbol for o in self._pending.values()}:
                self._maybe_fill_pendings(sym)
        positions = list(self._positions.values())
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        return positions

    def get_current_spread_pips(self, symbol: str) -> float:
        return float(self.symbols_cfg[symbol]["typical_spread_pips"])

    def set_quote(self, symbol: str, bid: float, ask: float, at: datetime | None = None) -> None:
        """Test/paper helper — inject a live quote for pending fill simulation."""
        self._quotes[symbol] = Quote(
            symbol=symbol, bid=float(bid), ask=float(ask), time=at or datetime.now(tz=UTC)
        )
        self._maybe_fill_pendings(symbol)

    def get_quote(self, symbol: str) -> Quote | None:
        if symbol in self._quotes:
            return self._quotes[symbol]
        # Fallback synthetic quote around last known mid from an open position or 0.
        spread_pips = self.get_current_spread_pips(symbol)
        pip_size = float(self.symbols_cfg[symbol]["pip_size"])
        half = spread_pips * pip_size / 2.0
        mid = None
        for pos in self._positions.values():
            if pos.symbol == symbol:
                mid = pos.entry_price
                break
        if mid is None:
            for pend in self._pending.values():
                if pend.symbol == symbol:
                    mid = pend.price
                    break
        if mid is None:
            return None
        return Quote(symbol=symbol, bid=mid - half, ask=mid + half, time=datetime.now(tz=UTC))

    def place_pending_stop(
        self,
        *,
        symbol: str,
        side: PendingOrderSide,
        volume: float,
        price: float,
        stop_loss: float,
        take_profit: float,
        expiration: datetime | None = None,
        comment: str = "",
    ) -> PendingOrder:
        order = PendingOrder(
            ticket=self._next_ticket,
            symbol=symbol,
            side=side,
            volume=float(volume),
            price=float(price),
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            comment=comment,
            expiration=expiration,
        )
        self._pending[order.ticket] = order
        self._next_ticket += 1
        logger.info(
            "[paper] Pending {} {} vol={} @ {:.5f} ticket={}",
            symbol,
            side.value,
            volume,
            price,
            order.ticket,
        )
        return order

    def cancel_pending_order(self, ticket: int) -> bool:
        removed = self._pending.pop(int(ticket), None)
        if removed is None:
            return False
        logger.info("[paper] Cancelled pending ticket={}", ticket)
        return True

    def get_pending_orders(
        self, symbol: str | None = None, comment_prefix: str | None = None
    ) -> list[PendingOrder]:
        orders = list(self._pending.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        if comment_prefix:
            orders = [o for o in orders if (o.comment or "").startswith(comment_prefix)]
        return orders

    def _maybe_fill_pendings(self, symbol: str) -> None:
        """Convert at most one stop pending into a position per quote update.

        News straddles are OCO: filling both BUY_STOP and SELL_STOP on the same
        spike would leave a hedged orphan. If a position is already open on the
        symbol, leave remaining stops for the engine to cancel.
        """
        if any(p.symbol == symbol for p in self._positions.values()):
            return
        quote = self.get_quote(symbol)
        if quote is None:
            return
        for ticket, order in list(self._pending.items()):
            if order.symbol != symbol:
                continue
            filled = False
            direction = SignalType.BUY
            fill_price = order.price
            if order.side == PendingOrderSide.BUY_STOP and quote.ask >= order.price:
                filled = True
                direction = SignalType.BUY
                fill_price = max(order.price, quote.ask)
            elif order.side == PendingOrderSide.SELL_STOP and quote.bid <= order.price:
                filled = True
                direction = SignalType.SELL
                fill_price = min(order.price, quote.bid)
            if not filled:
                continue
            self._pending.pop(ticket, None)
            position = Position(
                ticket=self._next_ticket,
                symbol=symbol,
                direction=direction,
                volume=order.volume,
                entry_price=fill_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                open_time=datetime.now(tz=UTC),
                initial_volume=order.volume,
                initial_stop_loss=order.stop_loss,
            )
            self._positions[position.ticket] = position
            self._next_ticket += 1
            logger.info(
                "[paper] Pending filled {} {} @ {:.5f} (was order {})",
                symbol,
                direction.value,
                fill_price,
                ticket,
            )
            # One fill per quote — remaining stop is left for OCO cancel.
            return

    def place_order(
        self, signal: Signal, volume: float, fill_price: float | None = None
    ) -> Position:
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
            open_time=signal.timestamp if signal.timestamp else datetime.now(tz=UTC),
            initial_volume=volume,
            initial_stop_loss=signal.stop_loss,
            strategy=resolve_strategy_tag(explicit=signal.strategy, reason=signal.reason),
        )
        self._positions[position.ticket] = position
        self._next_ticket += 1
        logger.info(
            "[paper] Opened {} {} vol={} @ {:.5f} (SL={:.5f} TP={:.5f})",
            signal.symbol,
            signal.signal_type.value,
            volume,
            fill,
            signal.stop_loss,
            signal.take_profit,
        )
        return position

    def modify_sl_tp(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        position = self._positions.get(ticket)
        if position is None:
            return False
        position.stop_loss = stop_loss
        position.take_profit = take_profit
        return True

    def close_position(
        self,
        ticket: int,
        exit_price: float | None = None,
        at: datetime | None = None,
        reason: str = "manual",
    ) -> TradeResult:
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

        # Prefer initial SL so trailing/breakeven moves do not distort R.
        risk_stop = position.initial_stop_loss or position.stop_loss
        risk = abs(position.entry_price - risk_stop)
        r_multiple = round(price_diff / risk, 3) if risk else 0.0

        result = TradeResult(
            symbol=position.symbol,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=close_price,
            volume=position.volume,
            open_time=position.open_time,
            close_time=at or datetime.now(tz=UTC),
            pnl=pnl,
            r_multiple=r_multiple,
            exit_reason=reason,
        )
        logger.info(
            "[paper] Closed {} {} @ {:.5f} pnl={:.2f} r={:.2f} reason={}",
            position.symbol,
            position.direction.value,
            close_price,
            pnl,
            r_multiple,
            reason,
        )
        return result

    def close_partial(
        self,
        ticket: int,
        volume: float,
        exit_price: float | None = None,
        at: datetime | None = None,
    ) -> TradeResult:
        position = self._positions.get(ticket)
        if position is None:
            raise RuntimeError(f"No open paper position for ticket {ticket}")
        close_vol = min(float(volume), position.volume)
        if close_vol <= 0:
            raise ValueError("partial volume must be positive")

        spec = self.symbols_cfg[position.symbol]
        close_price = exit_price if exit_price is not None else position.entry_price
        pip_size = spec["pip_size"]
        pip_value_per_lot = spec["pip_value_per_lot"]
        price_diff = (
            close_price - position.entry_price
            if position.direction == SignalType.BUY
            else position.entry_price - close_price
        )
        pnl = (price_diff / pip_size) * pip_value_per_lot * close_vol
        self.balance += pnl
        risk = abs(position.entry_price - (position.initial_stop_loss or position.stop_loss))
        r_multiple = round(price_diff / risk, 3) if risk else 0.0

        remaining = round(position.volume - close_vol, 8)
        if remaining <= 0:
            self._positions.pop(ticket, None)
        else:
            position.volume = remaining
            position.partial_taken = True

        return TradeResult(
            symbol=position.symbol,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=close_price,
            volume=close_vol,
            open_time=position.open_time,
            close_time=at or datetime.now(tz=UTC),
            pnl=pnl,
            r_multiple=r_multiple,
            exit_reason="partial_tp",
        )
