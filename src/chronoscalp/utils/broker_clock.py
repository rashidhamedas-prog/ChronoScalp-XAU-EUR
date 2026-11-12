"""Normalize broker server timestamps to true UTC.

MT5 (and many other FX platforms) stamp bar/tick epochs in *server wall clock*
while exposing them as Unix integers. Treating those values as UTC silently
shifts sessions, VWAP, and day boundaries by the broker offset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from chronoscalp.logging_setup import logger


@dataclass(frozen=True)
class BrokerClockOffset:
    """Measured broker-server offset relative to true UTC."""

    offset: timedelta
    measured_at: datetime
    source: str = "live_tick"
    stale: bool = False

    @property
    def offset_seconds(self) -> float:
        return float(self.offset.total_seconds())

    @property
    def offset_hours(self) -> float:
        return self.offset_seconds / 3600.0


def measure_offset_from_tick(
    server_epoch_seconds: float,
    *,
    wall_utc: datetime | None = None,
    max_tick_age_seconds: float = 120.0,
) -> BrokerClockOffset:
    """Compare a fresh server-stamped tick epoch to wall-clock UTC.

    Raises ``ValueError`` when the tick is too old to trust (weekend/holiday).
    Offset is rounded to the nearest 15 minutes to absorb jitter.
    """
    wall = wall_utc or datetime.now(tz=UTC)
    wall = wall.replace(tzinfo=UTC) if wall.tzinfo is None else wall.astimezone(UTC)

    server_as_if_utc = datetime.fromtimestamp(float(server_epoch_seconds), tz=UTC)
    raw = server_as_if_utc - wall
    # If the tick is stale relative to wall clock after removing a plausible
    # ±14h broker offset band, refuse to guess.
    residual_age = abs(raw.total_seconds()) % 3600
    # Prefer: age of tick assuming offset is a multiple of 15 minutes near raw.
    rounded_hours = round(raw.total_seconds() / 900.0) * 900.0
    offset = timedelta(seconds=rounded_hours)
    implied_true_utc = server_as_if_utc - offset
    age = abs((wall - implied_true_utc).total_seconds())
    stale = age > float(max_tick_age_seconds)
    if stale and abs(raw.total_seconds()) > 14 * 3600:
        raise ValueError(
            f"Broker tick too stale or out of range for offset detection "
            f"(age≈{age:.0f}s residual={residual_age:.0f}s)"
        )
    return BrokerClockOffset(
        offset=offset,
        measured_at=wall,
        source="live_tick",
        stale=stale,
    )


def to_true_utc(server_epoch_seconds: float, offset: BrokerClockOffset | timedelta) -> datetime:
    """Convert a broker-server epoch to timezone-aware true UTC."""
    delta = offset.offset if isinstance(offset, BrokerClockOffset) else offset
    as_if_utc = datetime.fromtimestamp(float(server_epoch_seconds), tz=UTC)
    return as_if_utc - delta


def assert_bar_freshness(
    last_bar_utc: datetime,
    *,
    wall_utc: datetime | None = None,
    max_age: timedelta = timedelta(minutes=5),
) -> None:
    """Fail closed when the latest M1 bar is older than ``max_age`` vs wall clock."""
    wall = wall_utc or datetime.now(tz=UTC)
    wall = wall.replace(tzinfo=UTC) if wall.tzinfo is None else wall.astimezone(UTC)
    bar = last_bar_utc
    bar = bar.replace(tzinfo=UTC) if bar.tzinfo is None else bar.astimezone(UTC)
    age = wall - bar
    if age > max_age:
        raise RuntimeError(
            f"Last M1 bar is stale: bar={bar.isoformat()} wall={wall.isoformat()} "
            f"age={age} max={max_age}"
        )
    logger.debug("M1 freshness OK age={}", age)
