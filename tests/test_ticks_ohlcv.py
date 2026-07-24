from __future__ import annotations

import numpy as np
import pandas as pd

from chronoscalp.data.mt5_connector import ticks_to_ohlcv
from chronoscalp.utils.types import Timeframe


def test_timeframe_subminute_seconds():
    assert Timeframe.S15.seconds == 15
    assert Timeframe.S15.is_subminute
    assert Timeframe.M1.seconds == 60
    assert not Timeframe.M1.is_subminute


def test_ticks_to_ohlcv_builds_s15_bars():
    # 45 seconds of mid prices → three S15 bars
    idx = pd.date_range("2026-01-01", periods=45, freq="s", tz="UTC")
    price = 100 + np.linspace(0, 0.5, 45)
    ticks = pd.DataFrame({"bid": price, "ask": price + 0.01, "volume": 1.0}, index=idx)
    ticks.index.name = "time"
    bars = ticks_to_ohlcv(ticks.reset_index(), seconds=15)
    assert len(bars) >= 2
    assert {"open", "high", "low", "close", "tick_volume"}.issubset(bars.columns)
    assert bars["high"].iloc[0] >= bars["low"].iloc[0]
