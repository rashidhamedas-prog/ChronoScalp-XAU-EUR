#!/usr/bin/env python3
"""Desktop entry for the trading loop. Default mode is paper.

The logon task calls this with ``--mode paper`` and sets
``CHRONOSCALP_CONFIRM_LIVE=no`` for that process. Live still requires the
environment variable to be exactly ``yes``, and this entry does not set it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _bootstrap() -> Path:
    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from chronoscalp.platform.desktop import prepare_desktop_home

    bundled = Path(getattr(sys, "_MEIPASS", root))
    config = bundled / "config"
    if not config.is_dir():
        config = root / "config"
    example = bundled / ".env.example"
    if not example.is_file():
        example = root / ".env.example"
    home = prepare_desktop_home(config, example if example.is_file() else None)
    os.chdir(home)
    return home


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChronoScalp desktop runner")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    return parser.parse_args()


def main() -> None:
    _bootstrap()
    args = parse_args()
    from chronoscalp.config import get_settings
    from chronoscalp.logging_setup import logger
    from chronoscalp.main import TradingBot

    settings = get_settings()
    if args.mode == "live" and not settings.secrets.live_trading_confirmed:
        logger.error(
            "Refusing live mode. CHRONOSCALP_CONFIRM_LIVE is not yes. "
            "The installer leaves it no. Paper mode is the default."
        )
        sys.exit(1)
    try:
        bot = TradingBot(settings, mode=args.mode)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)
    bot.start()


if __name__ == "__main__":
    main()
