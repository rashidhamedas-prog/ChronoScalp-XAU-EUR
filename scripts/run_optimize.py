#!/usr/bin/env python3
"""Grid-search or walk-forward optimization over indicator parameters.

Usage:
    python scripts/run_optimize.py --symbol XAUUSD --mode grid
    python scripts/run_optimize.py --symbol XAUUSD --mode walk-forward --folds 3

Results are written to JSON only — never auto-applied to config/settings.yaml.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.backtest.optimizer import (  # noqa: E402
    run_grid_search,
    run_walk_forward,
)
from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.data.mt5_connector import load_history_csv  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.utils.types import Timeframe  # noqa: E402

DEFAULT_GRID = {
    "ema_period_trend": [40, 50, 60],
    "rsi_period": [10, 14, 18],
    "macd_fast": [10, 12],
    "macd_slow": [24, 26],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize ChronoScalp indicator parameters")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--mode", choices=["grid", "walk-forward"], default="grid")
    parser.add_argument(
        "--metric",
        default="profit_factor",
        choices=["profit_factor", "expectancy_r", "return_pct", "win_rate"],
    )
    parser.add_argument("--from", dest="date_from", type=str, default=None)
    parser.add_argument("--to", dest="date_to", type=str, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--report", default=None, help="JSON output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    data_dir = args.data_dir or settings.backtest.get("data_dir", "data/history")

    higher_tfs = [Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]]
    trigger_tf = Timeframe(settings.raw["timeframes"]["entry_trigger"][-1])
    all_needed = sorted(
        set(higher_tfs + [Timeframe(tf) for tf in settings.raw["timeframes"]["entry_trigger"]]),
        key=lambda t: t.minutes,
    )

    raw_by_tf = {}
    for tf in all_needed:
        try:
            df = load_history_csv(data_dir, args.symbol, tf)
        except FileNotFoundError as exc:
            logger.error(str(exc))
            sys.exit(1)
        if args.date_from:
            df = df[df.index >= args.date_from]
        if args.date_to:
            df = df[df.index <= args.date_to]
        raw_by_tf[tf] = df

    if args.mode == "grid":
        from datetime import datetime

        start = datetime.fromisoformat(args.date_from) if args.date_from else None
        end = datetime.fromisoformat(args.date_to) if args.date_to else None
        result = run_grid_search(
            symbol=args.symbol,
            raw_by_timeframe=raw_by_tf,
            settings=settings,
            higher_timeframes=higher_tfs,
            trigger_timeframe=trigger_tf,
            param_grid=DEFAULT_GRID,
            metric=args.metric,
            start=start,
            end=end,
        )
        payload = {
            "mode": "grid",
            "symbol": args.symbol,
            "metric": args.metric,
            "best": (
                None
                if result.best is None
                else {
                    "params": result.best.params,
                    "score": result.best.score,
                    "summary": result.best.summary,
                }
            ),
            "top_5": [
                {"params": c.params, "score": c.score, "summary": c.summary}
                for c in result.candidates[:5]
            ],
        }
    else:
        wf = run_walk_forward(
            symbol=args.symbol,
            raw_by_timeframe=raw_by_tf,
            settings=settings,
            higher_timeframes=higher_tfs,
            trigger_timeframe=trigger_tf,
            param_grid=DEFAULT_GRID,
            metric=args.metric,
            n_folds=args.folds,
            train_ratio=args.train_ratio,
        )
        payload = {"mode": "walk-forward", **wf.to_dict()}

    print(json.dumps(payload, indent=2, default=str))

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info("Optimization report written to {}", args.report)


if __name__ == "__main__":
    main()
