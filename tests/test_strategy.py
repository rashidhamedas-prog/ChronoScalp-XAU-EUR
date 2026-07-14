from __future__ import annotations

import numpy as np
import pandas as pd

from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.strategy.multi_timeframe import determine_trend, trends_aligned
from chronoscalp.utils.types import TrendDirection


def _trending_df(n: int = 120, direction: str = "up") -> pd.DataFrame:
    slope = 0.15 if direction == "up" else -0.15
    close = 100 + np.cumsum(np.full(n, slope))
    high = close + 0.1
    low = close - 0.1
    open_ = close - 0.02
    index = pd.date_range("2026-01-01", periods=n, freq="10min", tz="UTC")
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)
    return enrich_with_indicators(df, ema_period=50)


def test_determine_trend_bullish():
    df = _trending_df(direction="up")
    trend = determine_trend(df, ema_col="ema_50")
    assert trend == TrendDirection.BULLISH


def test_determine_trend_bearish():
    df = _trending_df(direction="down")
    trend = determine_trend(df, ema_col="ema_50")
    assert trend == TrendDirection.BEARISH


def test_determine_trend_neutral_on_insufficient_data():
    df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]})
    assert determine_trend(df) == TrendDirection.NEUTRAL


def test_trends_aligned_requires_unanimous_agreement():
    assert (
        trends_aligned([TrendDirection.BULLISH, TrendDirection.BULLISH]) == TrendDirection.BULLISH
    )
    assert (
        trends_aligned([TrendDirection.BULLISH, TrendDirection.BEARISH]) == TrendDirection.NEUTRAL
    )
    assert (
        trends_aligned([TrendDirection.NEUTRAL, TrendDirection.NEUTRAL]) == TrendDirection.NEUTRAL
    )
