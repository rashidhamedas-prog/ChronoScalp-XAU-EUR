from __future__ import annotations

import numpy as np
import pandas as pd

from chronoscalp.backtest.engine import run_backtest
from chronoscalp.config import Settings
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.utils.types import Timeframe


def _synthetic_ohlcv(n: int = 200, freq: str = "1min") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 2000 + np.cumsum(rng.normal(0, 0.2, n))
    high = close + rng.uniform(0.05, 0.3, n)
    low = close - rng.uniform(0.05, 0.3, n)
    open_ = close + rng.normal(0, 0.05, n)
    index = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


def _enriched_by_tf() -> dict[Timeframe, pd.DataFrame]:
    base = _synthetic_ohlcv()
    result = {}
    for tf in (Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M10):
        if tf == Timeframe.M1:
            df = base
        else:
            df = (
                base.resample(f"{tf.minutes}min")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna()
            )
        df = enrich_with_indicators(df)
        result[tf] = enrich_with_smc(df)
    return result


def test_run_backtest_returns_summary_without_error():
    settings = Settings()
    data = _enriched_by_tf()
    result = run_backtest(
        symbol="XAUUSD",
        data_by_timeframe=data,
        higher_timeframes=[Timeframe.M10, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        settings=settings,
    )
    summary = result.summary()
    assert summary["symbol"] == "XAUUSD"
    assert "total_trades" in summary
    assert result.starting_equity == float(settings.backtest.get("initial_balance", 10_000))
