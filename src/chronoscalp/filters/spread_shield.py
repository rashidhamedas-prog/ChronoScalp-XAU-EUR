"""Per-symbol spread shield: broker cap, expansion vs median, conservative hard cap.

Does not raise XAUUSD news protection by blindly swapping 2 pips for a larger
constant. Callers supply the symbol's configured cap and a rolling median.
"""

from __future__ import annotations

from collections import defaultdict, deque

DEFAULT_EXPANSION = 1.2
DEFAULT_WINDOW = 50


class RollingMedianSpread:
    """Keep a short rolling window of spreads per symbol for median checks."""

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self.window = max(5, int(window))
        self._values: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.window))

    def observe(self, symbol: str, spread_pips: float) -> None:
        if spread_pips > 0:
            self._values[symbol].append(float(spread_pips))

    def median(self, symbol: str) -> float | None:
        values = list(self._values.get(symbol) or ())
        if len(values) < 3:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[mid])
        return float(ordered[mid - 1] + ordered[mid]) / 2.0


def spread_allowed(
    current_spread_pips: float,
    *,
    broker_cap_pips: float,
    rolling_median_pips: float | None,
    expansion: float = DEFAULT_EXPANSION,
    conservative_hard_cap_pips: float | None = None,
) -> tuple[bool, str]:
    """Fail closed on invalid inputs. Current must be <= cap and <= k * median."""
    if current_spread_pips <= 0 or broker_cap_pips <= 0:
        return False, "spread_invalid"
    cap = float(broker_cap_pips)
    if conservative_hard_cap_pips is not None and conservative_hard_cap_pips > 0:
        cap = min(cap, float(conservative_hard_cap_pips))
    if current_spread_pips > cap + 1e-12:
        return False, "spread_cap"
    if rolling_median_pips is None or rolling_median_pips <= 0:
        return False, "spread_median_unavailable"
    if current_spread_pips > float(expansion) * rolling_median_pips + 1e-12:
        return False, "spread_vs_median"
    return True, ""
