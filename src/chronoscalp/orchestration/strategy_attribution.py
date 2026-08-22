"""Per-strategy evaluation counters for fair comparison reporting."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

COUNTER_FIELDS = (
    "evaluated",
    "internal_reject_by_reason",
    "candidate",
    "risk_reject",
    "lost_arbitration",
    "filled",
    "closed",
)


@dataclass
class StrategyCounters:
    """Mutable counters for one strategy id."""

    evaluated: int = 0
    internal_reject_by_reason: dict[str, int] = field(default_factory=dict)
    candidate: int = 0
    risk_reject: int = 0
    lost_arbitration: int = 0
    filled: int = 0
    closed: int = 0
    heat_blocked_by: dict[str, int] = field(default_factory=dict)

    def record_internal_reject(self, reason: str) -> None:
        key = (reason or "unknown").strip() or "unknown"
        self.internal_reject_by_reason[key] = self.internal_reject_by_reason.get(key, 0) + 1

    def record_heat_block(self, by_strategy: str) -> None:
        tag = (by_strategy or "unknown").strip() or "unknown"
        self.heat_blocked_by[tag] = self.heat_blocked_by.get(tag, 0) + 1

    def to_dict(self) -> dict:
        return {
            "evaluated": self.evaluated,
            "internal_reject_by_reason": dict(self.internal_reject_by_reason),
            "candidate": self.candidate,
            "risk_reject": self.risk_reject,
            "lost_arbitration": self.lost_arbitration,
            "filled": self.filled,
            "closed": self.closed,
            "heat_blocked_by": dict(self.heat_blocked_by),
        }


class AttributionLedger:
    """Keep independent counters for every strategy that runs this process."""

    def __init__(self) -> None:
        self._by_strategy: dict[str, StrategyCounters] = defaultdict(StrategyCounters)

    def for_strategy(self, strategy: str) -> StrategyCounters:
        return self._by_strategy[strategy or "unknown"]

    def snapshot(self) -> dict[str, dict]:
        return {name: counters.to_dict() for name, counters in sorted(self._by_strategy.items())}
