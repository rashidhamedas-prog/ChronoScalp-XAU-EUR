from __future__ import annotations

import numpy as np
import pandas as pd

from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.strategy.multi_timeframe import (
    determine_trend,
    generate_entry_signal,
    trends_aligned,
)
from chronoscalp.utils.types import SignalType, Timeframe, TrendDirection


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


def _macd_cross_up_frame() -> pd.DataFrame:
    """Minimal frame where last bar is a bullish MACD cross with BB/ATR filled."""
    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    close = np.array([100.0, 100.1, 100.2, 100.3, 100.4])
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "macd": [-0.02, -0.01, 0.0, -0.01, 0.02],
            "signal": [0.0, 0.0, 0.0, 0.0, 0.0],
            "bb_lower": close - 1,
            "bb_upper": close + 1,
            "atr": np.full(n, 0.5),
            "rsi": np.full(n, 55.0),
            "histogram": [0.0] * n,
            "liquidity_sweep_low_vol": [False, False, False, False, True],
            "liquidity_sweep_high_vol": [False] * n,
        },
        index=index,
    )
    return df


def test_liquidity_volume_gate_blocks_without_vol_sweep():
    df = _macd_cross_up_frame()
    df.iloc[-1, df.columns.get_loc("liquidity_sweep_low_vol")] = False
    signal = generate_entry_signal(
        "EURJPY",
        df,
        TrendDirection.BULLISH,
        Timeframe.M1,
        use_smc_confluence=False,
        use_liquidity_volume=True,
    )
    assert signal.signal_type == SignalType.NONE


def test_liquidity_volume_gate_allows_vol_confirmed_sweep():
    df = _macd_cross_up_frame()
    signal = generate_entry_signal(
        "EURJPY",
        df,
        TrendDirection.BULLISH,
        Timeframe.M1,
        use_smc_confluence=False,
        use_liquidity_volume=True,
        atr_stop_multiple=1.5,
        atr_target_multiple=2.5,
    )
    assert signal.signal_type == SignalType.BUY
    assert "liquidity_volume" in signal.reason


def test_both_strategies_or_allows_smc_without_vol():
    """When SMC + liquidity are both enabled, either mode may confirm (OR)."""
    df = _macd_cross_up_frame()
    df.iloc[-1, df.columns.get_loc("liquidity_sweep_low_vol")] = False
    df["bullish_ob"] = False
    df["fvg_bullish"] = False
    df["liquidity_sweep_low"] = False
    df.iloc[-1, df.columns.get_loc("bullish_ob")] = True
    signal = generate_entry_signal(
        "USDJPY",
        df,
        TrendDirection.BULLISH,
        Timeframe.M1,
        use_smc_confluence=True,
        use_liquidity_volume=True,
    )
    assert signal.signal_type == SignalType.BUY
    assert "smc_confirmed" in signal.reason


def test_resolve_enabled_strategies_from_list():
    from chronoscalp.strategy.multi_timeframe import resolve_enabled_strategies

    smc, liq = resolve_enabled_strategies(
        {"enabled_strategies": ["smc_confluence", "liquidity_volume"]}
    )
    assert smc and liq
    smc2, liq2 = resolve_enabled_strategies({"enabled_strategies": []})
    assert not smc2 and not liq2
