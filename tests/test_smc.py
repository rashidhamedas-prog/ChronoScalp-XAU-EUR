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
            "low": [9.8, 9.8, 11.8, 13.1, 13.1],   # candle[2].low=11.8 > candle[0].high=10.2 -> bullish FVG at i=2
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
        "swing_high", "swing_low", "structure_event", "trend",
        "bullish_ob", "bearish_ob", "fvg_bullish", "fvg_bearish",
        "liquidity_sweep_high", "liquidity_sweep_low",
    }
    assert expected.issubset(set(enriched.columns))
    assert len(enriched) == len(df)
