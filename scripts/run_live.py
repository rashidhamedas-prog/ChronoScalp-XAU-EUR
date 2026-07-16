#!/usr/bin/env python3
"""CLI entry point for paper/live trading.

Usage:
    python scripts/run_live.py --mode paper
    python scripts/run_live.py --mode live      # requires CHRONOSCALP_CONFIRM_LIVE=yes in .env

Deployment:
    Windows + MT5  →  execution.broker=mt5, data_source=mt5
    Linux VPS (NL) →  execution.broker=oanda, data_source=oanda  (see docs/DEPLOY_NL_VPS.md)
    Paper anywhere →  execution.broker=paper, data_source=oanda|mt5
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
        from chronoscalp.licensing import require_valid_license

        require_valid_license(settings)
        bot = TradingBot(settings, mode=args.mode)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    bot.start()


if __name__ == "__main__":
    main()
