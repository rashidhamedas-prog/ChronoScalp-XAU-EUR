"""Append-only live spread sampling for historical analysis."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from chronoscalp.logging_setup import logger


class SpreadSampler:
    """Records periodic spread observations to CSV (one file per symbol)."""

    def __init__(self, directory: str | Path, enabled: bool = True) -> None:
        self.enabled = enabled
        self.directory = Path(directory)
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    def record(self, symbol: str, spread_pips: float, at: datetime | None = None) -> None:
        if not self.enabled:
            return
        ts = at or datetime.now(tz=UTC)
        path = self.directory / f"{symbol}_spread.csv"
        is_new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["timestamp", "spread_pips"])
            writer.writerow([ts.isoformat(), round(spread_pips, 4)])
        logger.debug("Recorded spread {} pips for {}", spread_pips, symbol)
