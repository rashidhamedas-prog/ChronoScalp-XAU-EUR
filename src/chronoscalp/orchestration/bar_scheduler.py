"""Bar-close gating and signal deduplication for the live loop."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from chronoscalp.utils.types import SignalType, Timeframe


def last_completed_bar_time(df: pd.DataFrame) -> datetime | None:
    """Timestamp of the most recently *closed* bar (index -2).

    ``copy_rates_from_pos(..., 0, n)`` includes the forming bar at index -1;
    strategy signals must be evaluated on completed bars only.
    """
    if df.empty or len(df) < 2:
        return None
    ts = df.index[-2]
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime()
    if isinstance(ts, datetime):
        return ts
    return None


def signal_dedup_key(
    symbol: str,
    timeframe: Timeframe,
    bar_time: datetime,
    signal_type: SignalType,
) -> str:
    """Stable idempotency key for a signal on a specific closed bar."""
    bar_iso = bar_time.isoformat()
    return f"{symbol}|{timeframe.value}|{bar_iso}|{signal_type.value}"


class BarCloseGate:
    """Tracks the last evaluated trigger bar per symbol (bar-close-only entries)."""

    def __init__(self) -> None:
        self._last_evaluated_bar: dict[str, datetime] = {}

    def is_new_bar(self, symbol: str, completed_bar: datetime) -> bool:
        return self._last_evaluated_bar.get(symbol) != completed_bar

    def mark_evaluated(self, symbol: str, completed_bar: datetime) -> None:
        self._last_evaluated_bar[symbol] = completed_bar

    def load_last_bar(self, symbol: str, completed_bar: datetime) -> None:
        """Restore state without treating the bar as newly evaluated."""
        self._last_evaluated_bar.setdefault(symbol, completed_bar)

    def last_evaluated_bars(self) -> dict[str, datetime]:
        return dict(self._last_evaluated_bar)


class SignalDeduper:
    """Prevents duplicate orders for the same symbol/bar/direction."""

    def __init__(self, processed: set[str] | None = None) -> None:
        self._processed = processed if processed is not None else set()

    @property
    def processed_keys(self) -> set[str]:
        return set(self._processed)

    def already_processed(self, key: str) -> bool:
        return key in self._processed

    def mark_processed(self, key: str) -> None:
        self._processed.add(key)

    def prune_older_than(self, keep_last: int = 500) -> None:
        if len(self._processed) <= keep_last:
            return
        # Keys embed ISO timestamps — sort lexicographically is safe for UTC ISO.
        trimmed = sorted(self._processed)[-keep_last:]
        self._processed = set(trimmed)
