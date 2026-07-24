#!/usr/bin/env python3
"""Train the setup-probability classifier from CSV history.

Usage:
    python scripts/train_ml_model.py --symbol XAUUSD
    python scripts/train_ml_model.py --symbol XAUUSD --output data/models/setup_classifier.joblib

After out-of-sample validation, set ``ml.enabled: true`` in config/settings.yaml.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.data.mt5_connector import load_history_csv  # noqa: E402
from chronoscalp.indicators.technical import enrich_with_indicators  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.ml.dataset import build_labeled_dataset  # noqa: E402
from chronoscalp.ml.model import SetupClassifier  # noqa: E402
from chronoscalp.smc.structure import enrich_with_smc  # noqa: E402
from chronoscalp.utils.types import Timeframe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train ChronoScalp setup classifier")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--from", dest="date_from", type=str, default=None)
    parser.add_argument("--to", dest="date_to", type=str, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output", default=None, help="Model output path (.joblib)")
    parser.add_argument("--report", default=None, help="Optional JSON training report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    data_dir = args.data_dir or settings.backtest.get("data_dir", "data/history")
    output = args.output or settings.ml.get("model_path", "data/models/setup_classifier.joblib")

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
        data_by_tf[tf] = enrich_with_smc(
            df, rvol_min=float(settings.strategy.get("liquidity_rvol_min", 1.5))
        )

    start = datetime.fromisoformat(args.date_from) if args.date_from else None
    end = datetime.fromisoformat(args.date_to) if args.date_to else None

    dataset = build_labeled_dataset(
        symbol=args.symbol,
        data_by_timeframe=data_by_tf,
        higher_timeframes=higher_tfs,
        trigger_timeframe=trigger_tf,
        settings=settings,
        start=start,
        end=end,
    )

    if len(dataset) < 20:
        logger.error(
            "Insufficient labeled samples ({}) — fetch more history or widen date range",
            len(dataset),
        )
        sys.exit(1)

    classifier = SetupClassifier()
    report = classifier.train(dataset)
    classifier.save(output)

    payload = {
        "symbol": args.symbol,
        "samples": len(dataset),
        "model_path": output,
        **report.to_dict(),
    }
    print(json.dumps(payload, indent=2))

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info("Training report written to {}", args.report)


if __name__ == "__main__":
    main()
