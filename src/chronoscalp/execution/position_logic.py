"""Shared open-position management: SL/TP hit detection and stop adjustments.

Used by both ``backtest/engine.py`` and ``main.py`` so paper-live behaviour
matches backtest simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.utils.types import Position, SignalType


@dataclass(frozen=True)
class SlTpHit:
    """Result when price trades through stop-loss or take-profit."""

    hit_sl: bool
    hit_tp: bool

    @property
    def triggered(self) -> bool:
        return self.hit_sl or self.hit_tp

    def exit_reason(self) -> str:
        return "stop_loss" if self.hit_sl else "take_profit"


def check_sl_tp_hit(position: Position, bar_high: float, bar_low: float) -> SlTpHit:
    """Return whether ``bar_high``/``bar_low`` pierced SL or TP for ``position``."""
    if position.direction == SignalType.BUY:
        hit_sl = bar_low <= position.stop_loss
        hit_tp = bar_high >= position.take_profit
    else:
        hit_sl = bar_high >= position.stop_loss
        hit_tp = bar_low <= position.take_profit
    return SlTpHit(hit_sl=hit_sl, hit_tp=hit_tp)


def exit_price_for_hit(position: Position, hit: SlTpHit) -> float:
    """Price at which the position should be closed given an SL/TP hit."""
    return position.stop_loss if hit.hit_sl else position.take_profit


def apply_breakeven_or_trailing(
    risk_manager: RiskManager,
    position: Position,
    current_price: float,
    atr_value: float | None,
) -> float | None:
    """Return a tighter stop-loss if breakeven or trailing rules apply, else None."""
    new_sl = risk_manager.breakeven_stop(position, current_price)
    if new_sl is not None:
        return new_sl
    if atr_value is not None and atr_value > 0:
        return risk_manager.trailing_stop(position, current_price, atr_value)
    return None


def sl_tp_hit_at(
    position: Position, bar_high: float, bar_low: float, at: datetime
) -> tuple[SlTpHit, datetime]:
    """Convenience wrapper keeping the evaluation timestamp explicit for callers."""
    return check_sl_tp_hit(position, bar_high, bar_low), at
