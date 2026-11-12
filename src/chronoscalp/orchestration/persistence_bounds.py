"""Bounded on-disk artifacts: rotate spread CSVs and prune closed ticket meta."""

from __future__ import annotations

import gzip
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from chronoscalp.logging_setup import logger
from chronoscalp.utils.atomic_json import write_json_atomic


def rotate_spread_csvs(
    directory: str | Path,
    *,
    max_age_days: int = 7,
    now: datetime | None = None,
) -> int:
    """Gzip spread CSV files older than ``max_age_days``. Returns count rotated."""
    root = Path(directory)
    if not root.exists():
        return 0
    wall = now or datetime.now(tz=UTC)
    cutoff = wall - timedelta(days=max(1, int(max_age_days)))
    rotated = 0
    for path in root.glob("*.csv"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime > cutoff:
            continue
        gz_path = path.with_suffix(path.suffix + ".gz")
        try:
            with path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            path.unlink(missing_ok=True)
            rotated += 1
        except OSError as exc:
            logger.warning("Failed rotating {}: {}", path, exc)
    return rotated


def prune_closed_ticket_meta(
    meta: dict[str, Any],
    *,
    max_age_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Drop closed-ticket meta entries older than ``max_age_days``."""
    wall = now or datetime.now(tz=UTC)
    cutoff = wall - timedelta(days=max(1, int(max_age_days)))
    kept: dict[str, Any] = {}
    for key, value in meta.items():
        if not isinstance(value, dict):
            kept[key] = value
            continue
        closed_at = value.get("closed_at") or value.get("updated_at")
        if not closed_at:
            kept[key] = value
            continue
        try:
            ts = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except ValueError:
            kept[key] = value
            continue
        if ts >= cutoff:
            kept[key] = value
    return kept


def save_pruned_meta(path: str | Path, meta: dict[str, Any], **kwargs: Any) -> None:
    """Atomically persist pruned position meta."""
    write_json_atomic(path, prune_closed_ticket_meta(meta, **kwargs))
