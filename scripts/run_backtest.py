#!/usr/bin/env python3
"""Run a backtest from local CSV history (data/history/, produced by
scripts/fetch_history.py). Works on any OS — no MT5/broker connection needed.

Usage:
    python scripts/run_backtest.py --symbol XAUUSD --from 2024-01-01 --to 2026-01-01
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.backtest.engine import run_backtest  # noqa: E402
from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.data.mt5_connector import load_history_csv  # noqa: E402
from chronoscalp.indicators.technical import enrich_with_indicators  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.ml.scorer import configure_scorer  # noqa: E402
from chronoscalp.smc.structure import enrich_with_smc  # noqa: E402
from chronoscalp.utils.types import Timeframe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest ChronoScalp against local CSV history")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--from", dest="date_from", type=str, default=None)
    parser.add_argument("--to", dest="date_to", type=str, default=None)
    parser.add_argument(
        "--data-dir", default=None, help="Defaults to config/settings.yaml backtest.data_dir"
    )
    parser.add_argument(
        "--report", default=None, help="Optional path to write a JSON summary report"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    if settings.ml.get("enabled"):
        configure_scorer(settings.ml.get("model_path"))
    data_dir = args.data_dir or settings.backtest.get("data_dir", "data/history")

    higher_tfs = [Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]]
    trigger_tf = Timeframe(settings.raw["timeframes"]["entry_trigger"][-1])
    all_needed = sorted(
        set(higher_tfs + [Timeframe(tf) for tf in settings.raw["timeframes"]["entry_trigger"]]),
        key=lambda t: t.minutes,
    )

    ind_cfg = settings.indicators
    data_by_tf = {}
    for tf in all_needed:
        try:
            df = load_history_csv(data_dir, args.symbol, tf)
        except FileNotFoundError as exc:
            logger.error(str(exc))
            sys.exit(1)
        df = enrich_with_indicators(
            df,
            ema_period=ind_cfg.get("ema_period_trend", 50),
            rsi_period=ind_cfg.get("rsi_period", 14),
            bb_period=ind_cfg.get("bollinger_period", 20),
            bb_std=ind_cfg.get("bollinger_std_dev", 2.0),
            macd_fast=ind_cfg.get("macd_fast", 12),
            macd_slow=ind_cfg.get("macd_slow", 26),
            macd_signal=ind_cfg.get("macd_signal", 9),
            atr_period=ind_cfg.get("atr_period", 14),
            rvol_period=ind_cfg.get("rvol_period", 20),
        )
        rvol_min = float(settings.strategy.get("liquidity_rvol_min", 1.5))
        df = enrich_with_smc(df, rvol_min=rvol_min)
        data_by_tf[tf] = df

    start = datetime.fromisoformat(args.date_from) if args.date_from else None
    end = datetime.fromisoformat(args.date_to) if args.date_to else None

    result = run_backtest(
        symbol=args.symbol,
        data_by_timeframe=data_by_tf,
        higher_timeframes=higher_tfs,
        trigger_timeframe=trigger_tf,
        settings=settings,
        start=start,
        end=end,
    )

    summary = result.summary()
    print(json.dumps(summary, indent=2, default=str))

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "summary": summary,
                    "trades": [
                        {
                            "symbol": t.symbol,
                            "direction": t.direction.value,
                            "entry_price": t.entry_price,
                            "exit_price": t.exit_price,
                            "volume": t.volume,
                            "open_time": t.open_time.isoformat(),
                            "close_time": t.close_time.isoformat(),
                            "pnl": t.pnl,
                            "r_multiple": t.r_multiple,
                            "exit_reason": t.exit_reason,
                        }
                        for t in result.trades
                    ],
                },
                f,
                indent=2,
            )
        logger.info("Report written to {}", args.report)


if __name__ == "__main__":
    main()
