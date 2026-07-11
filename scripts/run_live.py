#!/usr/bin/env python3
"""CLI entry point for paper/live trading.

Usage:
    python scripts/run_live.py --mode paper
    python scripts/run_live.py --mode live      # requires CHRONOSCALP_CONFIRM_LIVE=yes in .env

Requires a Windows host with the MT5 terminal installed and logged in (both
modes use MT5 for market data — see docs/ARCHITECTURE.md). For a
Linux/macOS-friendly workflow, use scripts/run_backtest.py instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.main import TradingBot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ChronoScalp in paper or live mode")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    try:
        bot = TradingBot(settings, mode=args.mode)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    bot.start()


if __name__ == "__main__":
    main()
