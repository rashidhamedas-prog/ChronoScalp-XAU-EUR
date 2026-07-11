"""Broker interface — the ONLY allowed coupling point to a broker SDK.

See docs/ARCHITECTURE.md "Broker abstraction" and CLAUDE.md rule #3:
strategy/risk/filter modules must depend on this Protocol, never import
`MetaTrader5` or any other broker SDK directly. This is what resolves the
Linux-VPS-vs-MT5-Windows-only conflict in the original brief — swap
implementations without touching anything above this layer.
"""

from __future__ import annotations

from typing import Protocol

from chronoscalp.utils.types import Position, Signal, TradeResult


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

    def place_order(self, signal: Signal, volume: float) -> Position:
        """Submit a market order derived from `signal`, sized at `volume` lots."""
        ...

    def modify_sl_tp(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        """Modify an open position's stop-loss / take-profit (used for
        breakeven and trailing-stop management)."""
        ...

    def close_position(self, ticket: int) -> TradeResult:
        """Close an open position at market and return the realized result."""
        ...
