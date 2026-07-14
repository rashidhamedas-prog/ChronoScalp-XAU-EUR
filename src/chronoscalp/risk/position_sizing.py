"""Position sizing, spread filtering, breakeven/trailing-stop, and daily
loss-limit enforcement.

This module is the single place that turns a `Signal` into an actual risked
dollar amount. See CLAUDE.md rule #1 — max_risk_per_trade_pct and
min_reward_risk_ratio (config/settings.yaml) are hard constraints enforced
here, not tuning knobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position, Signal


def round_to_lot_step(volume: float, min_lot: float, max_lot: float, lot_step: float) -> float:
    if lot_step <= 0:
        return max(min_lot, min(volume, max_lot))
    steps = round(volume / lot_step)
    rounded = steps * lot_step
    return max(min_lot, min(round(rounded, 8), max_lot))


def calculate_position_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    symbol_spec: dict,
) -> float:
    """Position size (in lots) such that a stop-loss hit loses exactly
    `risk_pct`% of `equity` (before slippage/commission)."""
    if equity <= 0:
        raise ValueError("equity must be positive")

    risk_amount = equity * (risk_pct / 100.0)
    price_risk = abs(entry_price - stop_loss)
    if price_risk <= 0:
        raise ValueError("entry_price and stop_loss must differ")

    pip_size = symbol_spec["pip_size"]
    pip_value_per_lot = symbol_spec["pip_value_per_lot"]
    risk_pips = price_risk / pip_size
    if risk_pips <= 0:
        raise ValueError("computed risk_pips must be positive")

    raw_volume = risk_amount / (risk_pips * pip_value_per_lot)
    return round_to_lot_step(
        raw_volume,
        min_lot=symbol_spec["min_lot"],
        max_lot=symbol_spec["max_lot"],
        lot_step=symbol_spec["lot_step"],
    )


def kelly_fraction(win_rate: float, reward_risk_ratio: float, cap_pct: float) -> float:
    """Kelly criterion position-sizing fraction (% of equity), hard-capped at
    `cap_pct`. Never returns a value above the cap regardless of how
    favorable win_rate/reward_risk_ratio look — see CLAUDE.md rule #1.
    """
    if reward_risk_ratio <= 0:
        return 0.0
    b = reward_risk_ratio
    p = win_rate
    q = 1 - p
    kelly = p - (q / b)
    kelly_pct = max(0.0, kelly) * 100.0
    return min(kelly_pct, cap_pct)


def passes_spread_filter(current_spread_pips: float, max_allowed_pips: float) -> bool:
    return current_spread_pips <= max_allowed_pips


def passes_reward_risk_filter(signal: Signal, min_ratio: float) -> bool:
    return signal.risk_reward_ratio >= min_ratio


@dataclass
class DailyRiskTracker:
    """Tracks realized P&L for the current day and enforces the daily loss
    limit — once hit, no new trades are permitted until the tracker rolls
    over to a new day."""

    max_daily_loss_pct: float
    starting_equity: float
    _current_date: date = field(default_factory=lambda: datetime.utcnow().date())
    _realized_pnl_today: float = 0.0

    def record_trade_pnl(self, pnl: float, at: datetime | None = None) -> None:
        self._roll_over_if_new_day(at or datetime.utcnow())
        self._realized_pnl_today += pnl

    def _roll_over_if_new_day(self, at: datetime) -> None:
        if at.date() != self._current_date:
            self._current_date = at.date()
            self._realized_pnl_today = 0.0

    def daily_loss_limit_hit(self, at: datetime | None = None) -> bool:
        self._roll_over_if_new_day(at or datetime.utcnow())
        loss_limit = -abs(self.starting_equity * (self.max_daily_loss_pct / 100.0))
        hit = self._realized_pnl_today <= loss_limit
        if hit:
            logger.warning(
                "Daily loss limit hit: realized_pnl_today={:.2f} <= limit={:.2f}",
                self._realized_pnl_today,
                loss_limit,
            )
        return hit


class RiskManager:
    """Facade combining sizing, filters, and breakeven/trailing logic behind
    a small API consumed by main.py / backtest/engine.py."""

    def __init__(
        self,
        risk_cfg: dict,
        spread_cfg: dict,
        symbols_cfg: dict,
        starting_equity: float,
    ) -> None:
        self.risk_cfg = risk_cfg
        self.spread_cfg = spread_cfg
        self.symbols_cfg = symbols_cfg
        self.daily_tracker = DailyRiskTracker(
            max_daily_loss_pct=risk_cfg.get("max_daily_loss_pct", 3.0),
            starting_equity=starting_equity,
        )

    def validate_signal(self, signal: Signal, current_spread_pips: float) -> bool:
        if self.daily_tracker.daily_loss_limit_hit():
            return False

        min_rr = self.risk_cfg.get("min_reward_risk_ratio", 1.5)
        if not passes_reward_risk_filter(signal, min_rr):
            logger.debug(
                "Signal rejected: R:R {:.2f} < min {:.2f}", signal.risk_reward_ratio, min_rr
            )
            return False

        if self.spread_cfg.get("enabled", True):
            max_spread = self.spread_cfg.get("max_spread_pips", {}).get(signal.symbol)
            if max_spread is not None and not passes_spread_filter(current_spread_pips, max_spread):
                logger.debug(
                    "Signal rejected: spread {:.2f} > max {:.2f} for {}",
                    current_spread_pips,
                    max_spread,
                    signal.symbol,
                )
                return False

        return True

    def position_size_for(
        self, signal: Signal, equity: float, win_rate_estimate: float = 0.6
    ) -> float:
        symbol_spec = self.symbols_cfg[signal.symbol]
        risk_pct = self.risk_cfg.get("max_risk_per_trade_pct", 1.0)

        if self.risk_cfg.get("use_kelly_sizing", False):
            risk_pct = kelly_fraction(
                win_rate=win_rate_estimate,
                reward_risk_ratio=signal.risk_reward_ratio,
                cap_pct=self.risk_cfg.get("max_risk_per_trade_pct", 1.0),
            )
            if risk_pct <= 0:
                return 0.0

        return calculate_position_size(
            equity=equity,
            risk_pct=risk_pct,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            symbol_spec=symbol_spec,
        )

    def breakeven_stop(self, position: Position, current_price: float) -> float | None:
        """Return a new stop-loss at entry price (breakeven) once price has
        moved `breakeven_at_r_multiple` R in favor, else None (no change)."""
        r_trigger = self.risk_cfg.get("breakeven_at_r_multiple", 1.0)
        risk = abs(position.entry_price - position.stop_loss)
        if risk == 0 or position.breakeven_moved:
            return None

        favorable_move = (
            current_price - position.entry_price
            if position.direction.value == "buy"
            else position.entry_price - current_price
        )
        if favorable_move >= r_trigger * risk:
            return position.entry_price
        return None

    def trailing_stop(
        self, position: Position, current_price: float, atr_value: float
    ) -> float | None:
        """ATR-based trailing stop. Returns a new SL only if it's tighter
        than the current one (never widens risk)."""
        multiple = self.risk_cfg.get("trailing_stop_atr_multiple", 1.5)
        if position.direction.value == "buy":
            candidate = current_price - multiple * atr_value
            if candidate > position.stop_loss:
                return candidate
        else:
            candidate = current_price + multiple * atr_value
            if candidate < position.stop_loss:
                return candidate
        return None
