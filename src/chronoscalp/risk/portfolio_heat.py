"""Aggregate open-position heat vs a portfolio ceiling.

Per-trade risk remains capped at 1% in ``position_sizing``. This module only
allocates leftover heat so concurrent strategies cannot exceed
``max_portfolio_heat_pct`` (default 3%, matching daily loss).
"""

from __future__ import annotations

from dataclasses import dataclass

from chronoscalp.logging_setup import logger
from chronoscalp.risk.position_sizing import HARD_MAX_RISK_PCT
from chronoscalp.utils.types import Position

DEFAULT_MAX_PORTFOLIO_HEAT_PCT = 3.0


def resolve_max_portfolio_heat_pct(risk_cfg: dict) -> float:
    """Return the live heat ceiling; never above daily-loss and never a per-trade raise."""
    daily = float(risk_cfg.get("max_daily_loss_pct", DEFAULT_MAX_PORTFOLIO_HEAT_PCT))
    requested = float(risk_cfg.get("max_portfolio_heat_pct", DEFAULT_MAX_PORTFOLIO_HEAT_PCT))
    if requested < 0:
        return 0.0
    return min(requested, daily)


def position_heat_pct(position: Position, equity: float) -> float:
    """Open dollar risk as a percent of equity (stop distance * notional / equity)."""
    if equity <= 0:
        return 0.0
    risk_price = abs(float(position.entry_price) - float(position.stop_loss))
    if risk_price <= 0:
        return 0.0
    # Volume is lots; dollar risk is reconstructed from stored initial stop when
    # callers pass ``risk_amount`` via meta. Fallback: treat stop distance as
    # a fraction of entry (used when contract size is unknown).
    initial_sl = position.initial_stop_loss
    if initial_sl is not None:
        risk_price = abs(float(position.entry_price) - float(initial_sl))
    notional_per_lot = float(getattr(position, "notional_per_lot", 0.0) or 0.0)
    if notional_per_lot > 0:
        dollars = risk_price * notional_per_lot * float(position.volume)
        return max(0.0, dollars / equity * 100.0)
    return 0.0


def dollar_risk_to_heat_pct(dollar_risk: float, equity: float) -> float:
    """Convert a dollar risk budget into a percent of equity."""
    if equity <= 0 or dollar_risk <= 0:
        return 0.0
    return dollar_risk / equity * 100.0


@dataclass(frozen=True)
class HeatAllocation:
    """Result of trying to fit a new trade into remaining portfolio heat."""

    allowed: bool
    risk_pct: float
    remaining_heat_pct: float
    reason: str = ""


def allocate_risk_pct(
    *,
    requested_risk_pct: float,
    open_heat_pct: float,
    max_heat_pct: float,
    per_trade_ceiling: float = HARD_MAX_RISK_PCT,
) -> HeatAllocation:
    """Shrink requested risk to remaining heat; never raise the 1% per-trade cap.

    Comparison/paper books should skip this and size independently.
    """
    ceiling = min(max(requested_risk_pct, 0.0), per_trade_ceiling, HARD_MAX_RISK_PCT)
    remaining = max_heat_pct - open_heat_pct
    if remaining <= 1e-12:
        return HeatAllocation(
            allowed=False,
            risk_pct=0.0,
            remaining_heat_pct=0.0,
            reason="portfolio_heat",
        )
    fitted = min(ceiling, remaining)
    if fitted <= 1e-12:
        return HeatAllocation(
            allowed=False,
            risk_pct=0.0,
            remaining_heat_pct=remaining,
            reason="portfolio_heat",
        )
    if fitted + 1e-12 < ceiling:
        logger.info(
            "Portfolio heat allocation: requested {:.3f}% -> {:.3f}% (open={:.3f}% cap={:.3f}%)",
            ceiling,
            fitted,
            open_heat_pct,
            max_heat_pct,
        )
    return HeatAllocation(
        allowed=True,
        risk_pct=fitted,
        remaining_heat_pct=remaining,
        reason="",
    )


def open_heat_from_dollar_risks(risks: list[float], equity: float) -> float:
    """Sum known dollar risks of open positions as a percent of equity."""
    if equity <= 0:
        return 0.0
    return sum(max(0.0, r) for r in risks) / equity * 100.0
