"""Portfolio-level equity helpers for multi-book validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioEquityPoint:
    index: int
    equity: float
    drawdown_pct: float


def combine_book_equity_curves(
    book_curves: Sequence[Sequence[float]],
) -> list[PortfolioEquityPoint]:
    """Sum aligned per-book equity series into one portfolio curve + DD.

    Each inner sequence is an equity level (not returns). Curves are truncated
    to the shortest length so indices stay aligned.
    """
    if not book_curves:
        return []
    n = min(len(c) for c in book_curves)
    if n == 0:
        return []
    points: list[PortfolioEquityPoint] = []
    peak = 0.0
    for i in range(n):
        equity = float(sum(float(curve[i]) for curve in book_curves))
        peak = max(peak, equity)
        dd = ((peak - equity) / peak * 100.0) if peak > 0 else 0.0
        points.append(PortfolioEquityPoint(index=i, equity=equity, drawdown_pct=dd))
    return points


def max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    """Maximum drawdown percentage of an equity level series."""
    peak = 0.0
    max_dd = 0.0
    for equity in equity_curve:
        eq = float(equity)
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)
    return float(max_dd)
