"""Single-instance lockfile with live-PID verification."""

from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from chronoscalp.logging_setup import logger
from chronoscalp.utils.atomic_json import read_json_with_fallback, write_json_atomic


class InstanceLockError(RuntimeError):
    """Raised when another live ChronoScalp process already holds the lock."""


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it — treat as alive.
        return True
    except OSError:
        return False
    return True


class InstanceLock:
    """Exclusive lock stored under ``state_dir/instance.lock``."""

    def __init__(self, state_dir: str | Path, *, enabled: bool = True) -> None:
        self.path = Path(state_dir) / "instance.lock"
        self.enabled = bool(enabled)
        self._held = False

    def acquire(self, *, magic: int | None = None) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                payload, _source = read_json_with_fallback(self.path, default={})
            except FileNotFoundError:
                payload = {}
            other_pid = int(payload.get("pid") or 0)
            if other_pid and other_pid != os.getpid() and _pid_alive(other_pid):
                raise InstanceLockError(
                    f"Another ChronoScalp process is running (pid={other_pid}, "
                    f"lock={self.path}). Stop it before starting a second instance."
                )
            logger.warning("Removing stale instance lock (pid={})", other_pid)
            with contextlib.suppress(OSError):
                self.path.unlink(missing_ok=True)

        write_json_atomic(
            self.path,
            {
                "pid": os.getpid(),
                "magic": int(magic) if magic is not None else None,
                "acquired_at": datetime.now(tz=UTC).isoformat(),
            },
            make_backup=False,
        )
        self._held = True
        logger.info("Acquired instance lock at {} (pid={})", self.path, os.getpid())

    def release(self) -> None:
        if not self._held:
            return
        try:
            if self.path.exists():
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if int(payload.get("pid") or 0) == os.getpid():
                    self.path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            logger.exception("Failed to release instance lock at {}", self.path)
        self._held = False
