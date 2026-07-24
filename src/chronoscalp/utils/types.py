"""Shared value types used across the ChronoScalp codebase.

Keeping these in one module (instead of re-declaring ad-hoc dicts/strings per
module) is what lets strategy, risk, and execution code stay decoupled from
any specific broker SDK — see docs/ARCHITECTURE.md "Broker abstraction".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Timeframe(StrEnum):
    """Supported timeframes. Always pass these, never raw strings like "5m".

    Sub-minute ``S15`` / ``S30`` are built from MT5 ticks (API has no native
    second bars). Use :attr:`seconds` for duration; :attr:`minutes` only for
    minute+ frames.
    """

    S15 = "S15"
    S30 = "S30"
    M1 = "M1"
    M3 = "M3"
    M5 = "M5"
    M10 = "M10"

    @property
    def seconds(self) -> int:
        return {
            "S15": 15,
            "S30": 30,
            "M1": 60,
            "M3": 180,
            "M5": 300,
            "M10": 600,
        }[self.value]

    @property
    def is_subminute(self) -> bool:
        return self.seconds < 60

    @property
    def minutes(self) -> int:
        if self.is_subminute:
            raise ValueError(f"{self.value} is sub-minute; use Timeframe.seconds")
        return self.seconds // 60


class TrendDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    NONE = "none"


@dataclass(frozen=True)
class Signal:
    """A validated, actionable trade signal produced by the strategy layer.

    Nothing downstream of a Signal is allowed to increase risk beyond what
    risk/position_sizing.py computes from it (see docs/ARCHITECTURE.md).
    """

    symbol: str
    signal_type: SignalType
    timestamp: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float = 0.0
    reason: str = ""
    timeframe: Timeframe = Timeframe.M1

    @property
    def risk_reward_ratio(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return round(reward / risk, 3) if risk else 0.0

    @property
    def is_actionable(self) -> bool:
        return self.signal_type != SignalType.NONE


@dataclass
class Position:
    """An open position as tracked by a Broker implementation."""

    ticket: int
    symbol: str
    direction: SignalType
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    open_time: datetime
    breakeven_moved: bool = False


@dataclass
class TradeResult:
    """A closed trade, used by both live execution logging and the backtester."""

    symbol: str
    direction: SignalType
    entry_price: float
    exit_price: float
    volume: float
    open_time: datetime
    close_time: datetime
    pnl: float
    r_multiple: float = 0.0
    exit_reason: str = ""
