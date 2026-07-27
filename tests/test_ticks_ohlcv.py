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


def test_ticks_to_ohlcv_counts_ticks_when_volume_zero():
    """CFD/crypto MT5 ticks often ship volume=0 — still need usable RVOL."""
    idx = pd.date_range("2026-01-01", periods=30, freq="s", tz="UTC")
    price = 100 + np.linspace(0, 0.2, 30)
    ticks = pd.DataFrame({"bid": price, "ask": price + 0.01, "volume": 0.0}, index=idx)
    ticks.index.name = "time"
    bars = ticks_to_ohlcv(ticks.reset_index(), seconds=15)
    assert len(bars) >= 2
    assert (bars["tick_volume"] > 0).all()
    assert bars["tick_volume"].iloc[0] >= 10


def test_subminute_tick_window_uses_broker_clock():
    """UTC+3 broker: tick range must end at broker tick time, not real UTC.

    Using real UTC as ``end`` on a UTC+N server drops the newest N hours of
    ticks — signals then price entries from stale bars (Invalid stops storm).
    """
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import patch

    from chronoscalp.data.mt5_connector import MT5Connector

    broker_ahead = timedelta(hours=3)
    broker_now = datetime.now(tz=UTC) + broker_ahead
    captured: dict = {}

    def fake_copy_ticks_range(symbol, start, end, flags):
        captured["start"], captured["end"] = start, end
        return []

    mt5_mod = SimpleNamespace(
        COPY_TICKS_ALL=1,
        symbol_info_tick=lambda _s: SimpleNamespace(
            time=int(broker_now.timestamp()),
            time_msc=int(broker_now.timestamp() * 1000),
            bid=100.0,
            ask=100.01,
        ),
        copy_ticks_range=fake_copy_ticks_range,
        last_error=lambda: (1, "Success"),
    )
    connector = MT5Connector(login=1, password="x", server="test")
    with (
        patch("chronoscalp.data.mt5_connector._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": mt5_mod}),
    ):
        connector._fetch_ohlcv_from_ticks("BTCUSD", Timeframe.S15, count=300)

    assert captured["end"] >= broker_now, "range end must cover the broker's newest tick"
    assert captured["end"] - broker_now < timedelta(seconds=30)
    assert captured["start"] < captured["end"]
