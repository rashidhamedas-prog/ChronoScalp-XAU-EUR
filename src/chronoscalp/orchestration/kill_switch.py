"""Manual and environment kill switches for unattended trading.

Trading halts when either:
- ``CHRONOSCALP_STOP_TRADING=yes`` is set in the environment / .env, or
- a ``STOP_TRADING`` marker file exists in the configured state directory.
"""

from __future__ import annotations

from pathlib import Path

from chronoscalp.logging_setup import logger

STOP_FILE_NAME = "STOP_TRADING"


class KillSwitch:
    """Detects operator-initiated trading halt requests."""

    def __init__(
        self,
        state_dir: str | Path,
        env_stop: str = "no",
        marker_filename: str = STOP_FILE_NAME,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._env_stop = env_stop.strip().lower() == "yes"
        self._marker_path = self._state_dir / marker_filename
        self._last_active: bool | None = None

    @property
    def env_active(self) -> bool:
        return self._env_stop

    @property
    def file_active(self) -> bool:
        return self._marker_path.exists()

    def is_active(self) -> bool:
        return self.env_active or self.file_active

    def reason(self) -> str | None:
        if self.env_active:
            return "CHRONOSCALP_STOP_TRADING=yes"
        if self.file_active:
            return f"marker file {self._marker_path}"
        return None

    def check_and_log(self) -> bool:
        """Return True when trading must halt; log only on state transitions."""
        active = self.is_active()
        if active and self._last_active is not True:
            logger.warning("Kill switch ACTIVE ({})", self.reason())
        elif not active and self._last_active is True:
            logger.info("Kill switch cleared — trading may resume")
        self._last_active = active
        return active
