"""Centralized logging setup. Import `logger` from here everywhere — never
use bare print() in strategy/risk/execution code (see CLAUDE.md conventions).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

_CONFIGURED = False


def setup_logging(log_level: str | None = None, log_dir: str | Path = "logs") -> None:
    """Idempotent logging configuration: console (colored) + rotating file sink,
    plus optional Sentry error tracking if SENTRY_DSN is set in the environment.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = log_level or os.getenv("LOG_LEVEL", "INFO")
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True, backtrace=False, diagnose=False)
    logger.add(
        log_dir / "chronoscalp_{time:YYYY-MM-DD}.log",
        level=level,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )

    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.0)
            logger.info("Sentry error tracking enabled")
        except ImportError:
            logger.warning("SENTRY_DSN set but sentry-sdk is not installed")

    _CONFIGURED = True


setup_logging()

__all__ = ["logger", "setup_logging"]
