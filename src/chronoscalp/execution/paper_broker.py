"""In-memory simulated broker — runs on any OS, no MT5 terminal required.

Used for paper trading (live data feed, simulated fills) and as the fill
model reused by backtest/engine.py. Applies configured spread + commission +
slippage so paper results are a meaningful approximation of live execution costs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.execution.account_mode import AccountMarginMode
from chronoscalp.execution.cost_model import (
    adverse_price_for_side,
    resolve_effective_spread_pips,
    side_fill_costs,
)
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
        self,
        symbols_cfg: dict,
        starting_balance: float = 10_000.0,
        slippage_pips: float = 0.5,
        first_ticket: int = 1,
        *,
        commission_per_lot_override: float | None = None,
        backtest_cfg: dict | None = None,
    ) -> None:
        self.symbols_cfg = {
            sym: dict(spec) for sym, spec in (symbols_cfg or {}).items() if isinstance(spec, dict)
        }
        if commission_per_lot_override is not None:
            for spec in self.symbols_cfg.values():
                spec["commission_per_lot"] = float(commission_per_lot_override)
        self.balance = starting_balance
        self.slippage_pips = slippage_pips
        self.backtest_cfg = dict(backtest_cfg or {})
        self._positions: dict[int, Position] = {}
        self._pending: dict[int, PendingOrder] = {}
        self._quotes: dict[str, Quote] = {}
        self._next_ticket = max(1, int(first_ticket))
        self._entry_costs_paid: dict[int, float] = {}

    def connect(self) -> bool:
        logger.info("PaperBroker ready (starting_balance={:.2f})", self.balance)
        return True

    def account_margin_mode(self) -> AccountMarginMode:
        """Paper books are independent; treated as hedging-capable."""
        return AccountMarginMode.PAPER

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
        return resolve_effective_spread_pips(symbol, self.symbols_cfg, self.backtest_cfg)

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
        strategy: str = "",
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
            strategy=strategy,
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
        """Fill triggered stop pendings without letting a news twin double-fill.

        Independent strategies (e.g. VWAP pullback) may fill on the same quote
        as a news leg. A second *news* fill is skipped so OCO can cancel it.
        """
        news_already_open = any(
            p.symbol == symbol and (p.strategy or "") == "news_straddle"
            for p in self._positions.values()
        )
        # Only a stored quote may trigger a fill. Synthesizing from the pending
        # price itself would fill every stop the first time it is inspected.
        quote = self._quotes.get(symbol)
        if quote is None:
            return
        filled_news = news_already_open
        for ticket, order in list(self._pending.items()):
            if order.symbol != symbol:
                continue
            comment = order.comment or ""
            is_news = comment.startswith("CS_News")
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
            if is_news and filled_news:
                continue
            self._pending.pop(ticket, None)
            tag = resolve_strategy_tag(explicit=order.strategy, comment=comment, reason=comment)
            if is_news:
                tag = "news_straddle"
                filled_news = True
            spec = self.symbols_cfg[symbol]
            spread_pips = self.get_current_spread_pips(symbol)
            entry_costs = side_fill_costs(
                spec,
                entry_price=fill_price,
                volume=order.volume,
                spread_pips=spread_pips,
            )
            self.balance -= entry_costs.total
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
                strategy=tag,
            )
            self._positions[position.ticket] = position
            self._entry_costs_paid[position.ticket] = entry_costs.total
            self._next_ticket += 1
            logger.info(
                "[paper] Pending filled {} {} @ {:.5f} (was order {} strategy={} entry_cost={:.2f})",
                symbol,
                direction.value,
                fill_price,
                ticket,
                tag,
                entry_costs.total,
            )

    def place_order(
        self, signal: Signal, volume: float, fill_price: float | None = None
    ) -> Position:
        spec = self.symbols_cfg[signal.symbol]
        spread_pips = self.get_current_spread_pips(signal.symbol)
        base_price = fill_price if fill_price is not None else signal.entry_price
        fill = adverse_price_for_side(
            mid_price=float(base_price),
            direction=signal.signal_type,
            is_entry=True,
            symbol_spec=spec,
            spread_pips=spread_pips,
            slippage_pips=self.slippage_pips,
        )
        entry_costs = side_fill_costs(
            spec, entry_price=fill, volume=volume, spread_pips=spread_pips
        )
        # Entry-side cash costs are reserved against balance immediately so
        # equity curves never ignore open-trade costs.
        self.balance -= entry_costs.total

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
        self._entry_costs_paid[position.ticket] = entry_costs.total
        self._next_ticket += 1
        logger.info(
            "[paper] Opened {} {} vol={} @ {:.5f} (SL={:.5f} TP={:.5f} entry_cost={:.2f})",
            signal.symbol,
            signal.signal_type.value,
            volume,
            fill,
            signal.stop_loss,
            signal.take_profit,
            entry_costs.total,
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
        spread_pips = self.get_current_spread_pips(position.symbol)
        raw_exit = exit_price if exit_price is not None else position.entry_price
        close_price = adverse_price_for_side(
            mid_price=float(raw_exit),
            direction=position.direction,
            is_entry=False,
            symbol_spec=spec,
            spread_pips=spread_pips,
            slippage_pips=self.slippage_pips,
        )
        pip_size = float(spec["pip_size"])
        pip_value_per_lot = float(spec["pip_value_per_lot"])

        price_diff = (
            close_price - position.entry_price
            if position.direction == SignalType.BUY
            else position.entry_price - close_price
        )
        gross_pnl = (price_diff / pip_size) * pip_value_per_lot * position.volume
        exit_costs = side_fill_costs(
            spec,
            entry_price=position.entry_price,
            volume=position.volume,
            spread_pips=spread_pips,
        )
        entry_paid = float(self._entry_costs_paid.pop(ticket, 0.0))
        # Entry costs already left the balance at open; debit exit costs now.
        self.balance += gross_pnl - exit_costs.total
        net_pnl = gross_pnl - entry_paid - exit_costs.total

        # Prefer initial SL so trailing/breakeven moves do not distort R.
        risk_stop = position.initial_stop_loss or position.stop_loss
        risk = abs(position.entry_price - risk_stop)
        risk_cash = (risk / pip_size) * pip_value_per_lot * position.volume if risk else 0.0
        r_multiple = round(net_pnl / risk_cash, 3) if risk_cash else 0.0

        result = TradeResult(
            symbol=position.symbol,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=close_price,
            volume=position.volume,
            open_time=position.open_time,
            close_time=at or datetime.now(tz=UTC),
            pnl=net_pnl,
            r_multiple=r_multiple,
            exit_reason=reason,
            commission_paid=exit_costs.commission * 2.0,
            spread_cost=exit_costs.spread * 2.0,
            gross_pnl=gross_pnl,
        )
        logger.info(
            "[paper] Closed {} {} @ {:.5f} gross={:.2f} net={:.2f} r={:.2f} reason={}",
            position.symbol,
            position.direction.value,
            close_price,
            gross_pnl,
            result.pnl,
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
        spread_pips = self.get_current_spread_pips(position.symbol)
        raw_exit = exit_price if exit_price is not None else position.entry_price
        close_price = adverse_price_for_side(
            mid_price=float(raw_exit),
            direction=position.direction,
            is_entry=False,
            symbol_spec=spec,
            spread_pips=spread_pips,
            slippage_pips=self.slippage_pips,
        )
        pip_size = float(spec["pip_size"])
        pip_value_per_lot = float(spec["pip_value_per_lot"])
        price_diff = (
            close_price - position.entry_price
            if position.direction == SignalType.BUY
            else position.entry_price - close_price
        )
        gross_pnl = (price_diff / pip_size) * pip_value_per_lot * close_vol
        exit_costs = side_fill_costs(
            spec,
            entry_price=position.entry_price,
            volume=close_vol,
            spread_pips=spread_pips,
        )
        fraction = close_vol / float(position.volume) if position.volume else 1.0
        entry_paid_total = float(self._entry_costs_paid.get(ticket, 0.0))
        entry_share = entry_paid_total * fraction
        if ticket in self._entry_costs_paid:
            self._entry_costs_paid[ticket] = max(0.0, entry_paid_total - entry_share)
        self.balance += gross_pnl - exit_costs.total
        net_pnl = gross_pnl - entry_share - exit_costs.total
        risk = abs(position.entry_price - (position.initial_stop_loss or position.stop_loss))
        risk_cash = (risk / pip_size) * pip_value_per_lot * close_vol if risk else 0.0
        r_multiple = round(net_pnl / risk_cash, 3) if risk_cash else 0.0

        remaining = round(position.volume - close_vol, 8)
        if remaining <= 0:
            self._positions.pop(ticket, None)
            self._entry_costs_paid.pop(ticket, None)
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
            pnl=net_pnl,
            r_multiple=r_multiple,
            exit_reason="partial_tp",
            commission_paid=exit_costs.commission * 2.0,
            spread_cost=exit_costs.spread * 2.0,
            gross_pnl=gross_pnl,
        )
