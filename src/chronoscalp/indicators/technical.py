"""Technical indicators.

Implemented as plain pandas (no TA-Lib compile step, no strict pandas-ta
dependency at import time) so the module works in any environment. If
pandas-ta is installed it's used for cross-checking in tests, but the
production computations below are self-contained and unit-testable.
"""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    result = 100 - (100 / (1 + rs))
    return result.fillna(50.0)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": histogram}
    )


def bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> pd.DataFrame:
    mid = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return pd.DataFrame({"bb_mid": mid, "bb_upper": upper, "bb_lower": lower})


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range. Expects columns: high, low, close."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def enrich_with_indicators(
    df: pd.DataFrame,
    ema_period: int = 50,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Return a copy of `df` with all standard indicator columns attached.
    `df` must have columns: open, high, low, close.
    """
    out = df.copy()
    out[f"ema_{ema_period}"] = ema(out["close"], ema_period)
    out["rsi"] = rsi(out["close"], rsi_period)

    macd_df = macd(out["close"], macd_fast, macd_slow, macd_signal)
    out = out.join(macd_df)

    bb_df = bollinger_bands(out["close"], bb_period, bb_std)
    out = out.join(bb_df)

    out["atr"] = atr(out, atr_period)
    return out
