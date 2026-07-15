#!/usr/bin/env python3
"""Seed demo data so the dashboard has something to display before first bot run."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chronoscalp.backtest.engine import run_backtest  # noqa: E402
from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.indicators.technical import enrich_with_indicators  # noqa: E402
from chronoscalp.smc.structure import enrich_with_smc  # noqa: E402
from chronoscalp.utils.types import Timeframe  # noqa: E402


def _synthetic_ohlcv(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 2000 + np.cumsum(rng.normal(0, 0.25, n))
    high = close + rng.uniform(0.05, 0.35, n)
    low = close - rng.uniform(0.05, 0.35, n)
    open_ = close + rng.normal(0, 0.05, n)
    index = pd.date_range(end=datetime.now(tz=UTC), periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


def seed_state() -> None:
    state_dir = ROOT / "data" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    demo = {
        "open_tickets": {"XAUUSD": 1001},
        "processed_signals": ["XAUUSD|M1|2026-07-14T12:00:00+00:00|buy"],
        "last_evaluated_bars": {"XAUUSD": "2026-07-14T12:00:00+00:00", "EURUSD": "2026-07-14T12:00:00+00:00"},
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    for mode in ("paper", "live"):
        path = state_dir / f"trading_state_{mode}.json"
        if not path.exists():
            path.write_text(json.dumps(demo, indent=2), encoding="utf-8")
            print(f"Created {path}")


def seed_spread() -> None:
    spread_dir = ROOT / "data" / "spread_history"
    spread_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC)
    for symbol, base, noise in (("XAUUSD", 22.0, 4.0), ("EURUSD", 1.2, 0.3)):
        path = spread_dir / f"{symbol}_spread.csv"
        if path.exists():
            continue
        rows = []
        for i in range(120):
            ts = now - timedelta(minutes=120 - i)
            val = base + np.random.default_rng(i).normal(0, noise)
            rows.append({"timestamp": ts.isoformat(), "spread_pips": round(max(val, 0.1), 2)})
        pd.DataFrame(rows).to_csv(path, index=False)
        print(f"Created {path}")


def seed_backtest_report() -> None:
    report_dir = ROOT / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "demo_xauusd.json"
    if path.exists():
        return

    settings = get_settings()
    base = _synthetic_ohlcv()
    data = {}
    for tf in (Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M10):
        if tf == Timeframe.M1:
            df = base
        else:
            df = (
                base.resample(f"{tf.minutes}min")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna()
            )
        data[tf] = enrich_with_smc(enrich_with_indicators(df))

    result = run_backtest(
        symbol="XAUUSD",
        data_by_timeframe=data,
        higher_timeframes=[Timeframe.M10, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        settings=settings,
    )
    payload = {"summary": result.summary(), "demo": True}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Created {path} ({result.total_trades} trades)")


def main() -> None:
    seed_state()
    seed_spread()
    seed_backtest_report()
    print("Demo data ready — run: streamlit run scripts/dashboard.py")


if __name__ == "__main__":
    main()
