"""Crash-safe JSON persistence: temp + fsync + os.replace, with .bak recovery."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chronoscalp.logging_setup import logger


def backup_path(path: Path) -> Path:
    """Return the sibling ``.bak`` path for ``path``."""
    return path.with_suffix(path.suffix + ".bak")


def write_json_atomic(
    path: str | Path,
    payload: Any,
    *,
    indent: int | None = 2,
    make_backup: bool = True,
) -> None:
    """Write JSON atomically in the same directory as ``path``.

    Creates a rolling ``*.bak`` of the previous good file (when present),
    then writes a temp file, fsyncs, and ``os.replace``s into place.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    bak = backup_path(target)

    # Keep the previous good file as .bak *before* replace so a crash during
    # the new write never destroys the last known-good snapshot.
    previous: bytes | None = None
    if make_backup and target.exists():
        try:
            previous = target.read_bytes()
        except OSError as exc:
            logger.warning("Could not read prior state for {}: {}", target, exc)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent, ensure_ascii=False, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        if make_backup:
            try:
                # Prefer prior bytes; on first write, seed .bak from the new file.
                if previous is not None:
                    bak.write_bytes(previous)
                elif not bak.exists():
                    bak.write_bytes(target.read_bytes())
            except OSError as exc:
                logger.warning("Could not refresh backup for {}: {}", target, exc)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def read_json_with_fallback(
    path: str | Path,
    *,
    default: Any | None = None,
    validate: Callable[[Any], None] | None = None,
    restore_from_backup: bool = True,
) -> tuple[Any, str]:
    """Load JSON from ``path``, falling back to ``.bak`` on corruption.

    Returns ``(payload, source)`` where ``source`` is ``"main"``, ``"backup"``,
    or ``"default"``. Never raises on corrupt main when a usable backup or
    ``default`` is available; restores main from backup when requested.
    """
    target = Path(path)
    bak = backup_path(target)

    def _load(candidate: Path) -> Any:
        with candidate.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        if validate is not None:
            validate(payload)
        return payload

    if target.exists():
        try:
            return _load(target), "main"
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Corrupt state at {}: {} — trying backup", target, exc)

    if bak.exists():
        try:
            payload = _load(bak)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Backup also unreadable at {}: {}", bak, exc)
        else:
            if restore_from_backup:
                try:
                    write_json_atomic(target, payload, make_backup=False)
                except OSError as exc:
                    logger.warning("Could not restore {} from backup: {}", target, exc)
            return payload, "backup"

    if default is not None:
        return default, "default"
    raise FileNotFoundError(f"No readable JSON at {target} or {bak}")
