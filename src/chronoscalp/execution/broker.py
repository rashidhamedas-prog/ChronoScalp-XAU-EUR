"""Broker interface — the ONLY allowed coupling point to a broker SDK.

See docs/ARCHITECTURE.md "Broker abstraction" and CLAUDE.md rule #3:
strategy/risk/filter modules must depend on this Protocol, never import
`MetaTrader5` or any other broker SDK directly. This is what resolves the
Linux-VPS-vs-MT5-Windows-only conflict in the original brief — swap
implementations without touching anything above this layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from chronoscalp.execution.account_mode import AccountMarginMode
from chronoscalp.utils.types import (
    PendingOrder,
    PendingOrderSide,
    Position,
    Quote,
    Signal,
    TradeResult,
)


class Broker(Protocol):
    def connect(self) -> bool:
        """Establish the connection. Return True on success."""
        ...

    def get_balance(self) -> float:
        """Current account equity/balance in account currency."""
        ...

    def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        """All open positions, optionally filtered by symbol."""
        ...

    def get_current_spread_pips(self, symbol: str) -> float:
        """Current bid/ask spread in pips, used by the spread filter."""
        ...

    def get_quote(self, symbol: str) -> Quote | None:
        """Live bid/ask quote, or None when unavailable."""
        ...

    def place_order(self, signal: Signal, volume: float) -> Position:
        """Submit a market order derived from `signal`, sized at `volume` lots."""
        ...

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
        """Place a BUY_STOP / SELL_STOP pending order (news straddle)."""
        ...

    def cancel_pending_order(self, ticket: int) -> bool:
        """Cancel a working pending order by ticket."""
        ...

    def get_pending_orders(
        self, symbol: str | None = None, comment_prefix: str | None = None
    ) -> list[PendingOrder]:
        """Working pending orders, optionally filtered by symbol / comment prefix."""
        ...

    def modify_sl_tp(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        """Modify an open position's stop-loss / take-profit (used for
        breakeven and trailing-stop management)."""
        ...

    def close_position(self, ticket: int) -> TradeResult:
        """Close an open position at market and return the realized result."""
        ...

    def close_partial(self, ticket: int, volume: float) -> TradeResult:
        """Close part of an open position at market; leave remainder open."""
        ...

    def account_margin_mode(self) -> AccountMarginMode:
        """Hedging vs netting. Paper is always independent-capable."""
        ...
