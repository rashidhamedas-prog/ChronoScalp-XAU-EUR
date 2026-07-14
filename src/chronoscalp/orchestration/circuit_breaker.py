"""Circuit breaker — halts new entries after repeated operational failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from chronoscalp.logging_setup import logger


@dataclass
class CircuitBreaker:
    """Trips after ``max_consecutive_errors`` failures within the live loop.

    When tripped, callers should skip new entries and optionally shut down.
    Successful ticks reset the failure counter.
    """

    max_consecutive_errors: int = 5
    _consecutive_errors: int = 0
    _tripped: bool = False
    _tripped_at: datetime | None = field(default=None, repr=False)

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def tripped_at(self) -> datetime | None:
        return self._tripped_at

    def record_success(self) -> None:
        self._consecutive_errors = 0

    def record_failure(self, context: str = "") -> bool:
        """Increment failure count; return True if the breaker just tripped."""
        self._consecutive_errors += 1
        logger.warning(
            "Circuit breaker failure {}/{} ({})",
            self._consecutive_errors,
            self.max_consecutive_errors,
            context or "unspecified",
        )
        if self._consecutive_errors >= self.max_consecutive_errors and not self._tripped:
            self._tripped = True
            self._tripped_at = datetime.now(tz=UTC)
            logger.error(
                "Circuit breaker TRIPPED after {} consecutive errors",
                self._consecutive_errors,
            )
            return True
        return False

    def reset(self) -> None:
        self._consecutive_errors = 0
        self._tripped = False
        self._tripped_at = None
