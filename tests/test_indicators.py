from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chronoscalp.indicators.technical import (
    atr,
    bollinger_bands,
    ema,
    enrich_with_indicators,
    macd,
    rsi,
)


def _make_ohlcv(n: int = 200, trend: float = 0.05, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.3, n)
    close = 100 + np.cumsum(trend + noise * 0.1)
    high = close + rng.uniform(0.05, 0.3, n)
    low = close - rng.uniform(0.05, 0.3, n)
    open_ = close - rng.uniform(-0.1, 0.1, n)
    index = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


def test_ema_converges_to_price_trend():
    df = _make_ohlcv()
    result = ema(df["close"], period=20)
    assert result.isna().sum() == 19  # min_periods warmup
    assert result.iloc[-1] == pytest.approx(df["close"].iloc[-20:].mean(), rel=0.15)


def test_rsi_bounds():
    df = _make_ohlcv()
    result = rsi(df["close"], period=14)
    valid = result.dropna()
    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_rsi_strong_uptrend_is_high():
    n = 60
    close = pd.Series(np.linspace(100, 130, n))
    result = rsi(close, period=14)
    assert result.iloc[-1] > 70


def test_macd_columns_and_shape():
    df = _make_ohlcv()
    result = macd(df["close"])
    assert list(result.columns) == ["macd", "signal", "histogram"]
    assert len(result) == len(df)


def test_bollinger_bands_ordering():
    df = _make_ohlcv()
    bands = bollinger_bands(df["close"], period=20, std_dev=2.0)
    valid = bands.dropna()
    assert (valid["bb_upper"] >= valid["bb_mid"]).all()
    assert (valid["bb_mid"] >= valid["bb_lower"]).all()


def test_atr_non_negative():
    df = _make_ohlcv()
    result = atr(df, period=14)
    assert (result.dropna() >= 0).all()


def test_enrich_with_indicators_adds_expected_columns():
    df = _make_ohlcv()
    enriched = enrich_with_indicators(df, ema_period=50)
    expected = {
        "ema_50",
        "rsi",
        "macd",
        "signal",
        "histogram",
        "bb_mid",
        "bb_upper",
        "bb_lower",
        "atr",
        "rvol",
    }
    assert expected.issubset(set(enriched.columns))
    assert len(enriched) == len(df)


def test_relative_volume_above_average_when_spike():
    from chronoscalp.indicators.technical import relative_volume

    vol = pd.Series([10.0] * 20 + [50.0])
    rvol = relative_volume(vol, period=20)
    assert rvol.iloc[-1] > 2.0
