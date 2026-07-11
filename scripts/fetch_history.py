#!/usr/bin/env python3
"""Fetch historical OHLCV data from MT5 and save it as CSV for backtesting.

Windows + MT5 terminal required (see docs/ARCHITECTURE.md). Once fetched,
the resulting CSVs under data/history/ can be used by scripts/run_backtest.py
on any OS — you only need Windows/MT5 for this one-time (or periodically
refreshed) data pull.

Usage:
    python scripts/fetch_history.py --symbol XAUUSD --years 2
    python scripts/fetch_history.py --symbol EURUSD --timeframes M1 M3 M5 M10 --years 1
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.data.mt5_connector import MT5Connector, save_history_csv  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.utils.types import Timeframe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch MT5 historical OHLCV data to CSV")
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--timeframes", nargs="+", default=["M1", "M3", "M5", "M10"], choices=[tf.value for tf in Timeframe]
    )
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--data-dir", default="data/history")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    connector = MT5Connector(
        login=settings.secrets.mt5_login,
        password=settings.secrets.mt5_password,
        server=settings.secrets.mt5_server,
        terminal_path=settings.secrets.mt5_terminal_path,
    )
    if not connector.connect():
        logger.error("Could not connect to MT5 — is the terminal installed, running, and logged in?")
        sys.exit(1)

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=int(args.years * 365))

    try:
        for tf_name in args.timeframes:
            tf = Timeframe(tf_name)
            logger.info("Fetching {} {} from {} to {}...", args.symbol, tf.value, start.date(), end.date())
            df = connector.fetch_ohlcv_range(args.symbol, tf, start, end)
            if df.empty:
                logger.warning("No data returned for {} {}", args.symbol, tf.value)
                continue
            save_history_csv(df, args.data_dir, args.symbol, tf)
    finally:
        connector.shutdown()


if __name__ == "__main__":
    main()
