from __future__ import annotations

import numpy as np
import pandas as pd

from chronoscalp.smc.structure import (
    detect_fair_value_gaps,
    detect_swing_points,
    enrich_with_smc,
)


def _zigzag_df(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    x = np.linspace(0, 6 * np.pi, n)
    close = 100 + 5 * np.sin(x) + rng.normal(0, 0.05, n)
    high = close + 0.2
    low = close - 0.2
    open_ = close - 0.02
    index = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


def test_detect_swing_points_finds_some_swings():
    df = _zigzag_df()
    swings = detect_swing_points(df, left=2, right=2)
    assert swings["swing_high"].sum() > 0
    assert swings["swing_low"].sum() > 0


def test_detect_fair_value_gaps_flags_real_gap():
    index = pd.date_range("2026-01-01", periods=5, freq="min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [10, 10, 12, 13, 13],
            "high": [10.2, 10.2, 13, 13.5, 13.5],  # candle[0].high=10.2
            "low": [
                9.8,
                9.8,
                11.8,
                13.1,
                13.1,
            ],  # candle[2].low=11.8 > candle[0].high=10.2 -> bullish FVG at i=2
            "close": [10, 10.1, 12.8, 13.3, 13.4],
        },
        index=index,
    )
    result = detect_fair_value_gaps(df)
    assert result["fvg_bullish"].iloc[2]


def test_enrich_with_smc_returns_all_expected_columns():
    df = _zigzag_df()
    enriched = enrich_with_smc(df)
    expected = {
        "swing_high",
        "swing_low",
        "structure_event",
        "trend",
        "bullish_ob",
        "bearish_ob",
        "fvg_bullish",
        "fvg_bearish",
        "liquidity_sweep_high",
        "liquidity_sweep_low",
        "liquidity_sweep_high_vol",
        "liquidity_sweep_low_vol",
    }
    assert expected.issubset(set(enriched.columns))
    assert len(enriched) == len(df)


def test_volume_confirmed_liquidity_sweep_requires_elevated_rvol():
    """A low sweep with high RVOL sets liquidity_sweep_low_vol; low RVOL does not."""
    from chronoscalp.smc.structure import detect_liquidity_sweeps

    n = 10
    index = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    close = np.full(n, 100.0)
    high = close + 0.5
    low = close - 0.5
    # Bar 3 is a confirmed swing low at 98.0
    low[3] = 98.0
    close[3] = 98.5
    high[3] = 99.0
    # Bar 7 sweeps below that swing low and closes back above
    sweep_i = 7
    low[sweep_i] = 97.5
    high[sweep_i] = 99.5
    close[sweep_i] = 98.5

    df = pd.DataFrame(
        {
            "open": close.copy(),
            "high": high,
            "low": low,
            "close": close,
            "rvol": np.full(n, 1.0),
        },
        index=index,
    )
    swings = pd.DataFrame(
        {"swing_high": [False] * n, "swing_low": [False] * n},
        index=index,
    )
    swings.iloc[3, swings.columns.get_loc("swing_low")] = True

    df_low_vol = detect_liquidity_sweeps(df, swings, rvol_min=1.5)
    assert bool(df_low_vol["liquidity_sweep_low"].iloc[sweep_i])
    assert not bool(df_low_vol["liquidity_sweep_low_vol"].iloc[sweep_i])

    df2 = df.copy()
    df2.loc[df2.index[sweep_i], "rvol"] = 2.0
    df_hi_vol = detect_liquidity_sweeps(df2, swings, rvol_min=1.5)
    assert bool(df_hi_vol["liquidity_sweep_low_vol"].iloc[sweep_i])
