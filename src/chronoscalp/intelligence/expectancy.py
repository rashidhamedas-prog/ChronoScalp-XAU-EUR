"""Rank strategy candidates by **net-of-cost** expectancy, not gross R:R."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from chronoscalp.utils.types import Signal


@dataclass(frozen=True)
class CandidateScore:
    """Scored candidate ready for portfolio allocation."""

    signal: Signal
    net_expectancy_r: float
    win_prob: float
    reward_risk: float
    cost_r: float

    @property
    def strategy(self) -> str:
        return str(getattr(self.signal, "strategy", None) or self.signal.reason or "unknown")


def estimate_net_expectancy_r(
    *,
    win_prob: float,
    reward_risk: float,
    cost_r: float,
) -> float:
    """``p*R - (1-p)*1 - cost_r`` in R-units (stop distance = 1R)."""
    p = min(max(float(win_prob), 0.0), 1.0)
    rr = max(0.0, float(reward_risk))
    cost = max(0.0, float(cost_r))
    return p * rr - (1.0 - p) * 1.0 - cost


def rank_by_net_expectancy(
    scored: Sequence[CandidateScore],
    *,
    min_expectancy: float = 0.0,
) -> list[CandidateScore]:
    """Return candidates with expectancy ≥ floor, best-first."""
    eligible = [c for c in scored if c.net_expectancy_r >= float(min_expectancy)]
    return sorted(eligible, key=lambda c: c.net_expectancy_r, reverse=True)


def score_signal(
    signal: Signal,
    *,
    win_prob: float,
    cost_r: float,
) -> CandidateScore:
    """Build a :class:`CandidateScore` from geometry on ``signal``."""
    risk = abs(float(signal.entry_price) - float(signal.stop_loss))
    reward = abs(float(signal.take_profit) - float(signal.entry_price))
    rr = (reward / risk) if risk > 0 else 0.0
    exp = estimate_net_expectancy_r(win_prob=win_prob, reward_risk=rr, cost_r=cost_r)
    return CandidateScore(
        signal=signal,
        net_expectancy_r=exp,
        win_prob=float(win_prob),
        reward_risk=rr,
        cost_r=float(cost_r),
    )
