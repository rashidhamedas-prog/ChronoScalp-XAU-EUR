"""Circuit breaker — halts new entries after repeated operational failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from chronoscalp.logging_setup import logger


@dataclass
class CircuitBreaker:
    """Trips after consecutive operational failures; stays open for a minimum
    duration and only resets after ``success_threshold`` consecutive successes.

    States: CLOSED → OPEN → HALF_OPEN → CLOSED.
    """

    max_consecutive_errors: int = 5
    min_trip_seconds: float = 600.0
    success_threshold: int = 20
    _consecutive_errors: int = 0
    _consecutive_successes: int = 0
    _tripped: bool = False
    _half_open: bool = False
    _tripped_at: datetime | None = field(default=None, repr=False)

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    @property
    def consecutive_successes(self) -> int:
        return self._consecutive_successes

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def is_half_open(self) -> bool:
        return self._half_open

    @property
    def tripped_at(self) -> datetime | None:
        return self._tripped_at

    def _min_trip_elapsed(self, now: datetime | None = None) -> bool:
        if self._tripped_at is None:
            return True
        wall = now or datetime.now(tz=UTC)
        if wall.tzinfo is None:
            wall = wall.replace(tzinfo=UTC)
        return (wall - self._tripped_at) >= timedelta(seconds=float(self.min_trip_seconds))

    def record_success(self, *, now: datetime | None = None) -> None:
        """Record a clean operational tick.

        While OPEN and the minimum trip duration has not elapsed, successes are
        ignored (breaker stays tripped). After the duration, the breaker enters
        HALF_OPEN and requires ``success_threshold`` consecutive successes.
        """
        if self._tripped and not self._min_trip_elapsed(now):
            return

        if self._tripped and not self._half_open:
            self._half_open = True
            self._consecutive_successes = 0
            logger.info(
                "Circuit breaker HALF_OPEN after min trip duration "
                "({:.0f}s) — probing",
                self.min_trip_seconds,
            )

        self._consecutive_errors = 0
        self._consecutive_successes += 1

        if self._tripped:
            if self._consecutive_successes >= int(self.success_threshold):
                self._tripped = False
                self._half_open = False
                self._tripped_at = None
                self._consecutive_successes = 0
                logger.info(
                    "Circuit breaker reset after {} consecutive successes",
                    self.success_threshold,
                )
            return

        self._consecutive_successes = 0

    def record_failure(self, context: str = "", *, now: datetime | None = None) -> bool:
        """Increment failure count; return True if the breaker just tripped."""
        self._consecutive_successes = 0
        if self._half_open:
            self._half_open = False
            self._tripped = True
            self._tripped_at = now or datetime.now(tz=UTC)
            self._consecutive_errors = max(self._consecutive_errors, 1)
            logger.error(
                "Circuit breaker re-OPENED from HALF_OPEN ({})",
                context or "unspecified",
            )
            return True

        self._consecutive_errors += 1
        logger.warning(
            "Circuit breaker failure {}/{} ({})",
            self._consecutive_errors,
            self.max_consecutive_errors,
            context or "unspecified",
        )
        if self._consecutive_errors >= self.max_consecutive_errors and not self._tripped:
            self._tripped = True
            self._tripped_at = now or datetime.now(tz=UTC)
            logger.error(
                "Circuit breaker TRIPPED after {} consecutive errors "
                "(min hold {:.0f}s / {} successes to reset)",
                self._consecutive_errors,
                self.min_trip_seconds,
                self.success_threshold,
            )
            return True
        return False

    def reset(self) -> None:
        self._consecutive_errors = 0
        self._consecutive_successes = 0
        self._tripped = False
        self._half_open = False
        self._tripped_at = None
