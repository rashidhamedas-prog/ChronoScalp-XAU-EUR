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
    rs = avg_gain / avg_loss.where(avg_loss != 0)
    result = 100 - (100 / (1 + rs))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    return result.fillna(50.0).astype("float64")


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
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


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Wilder-style ADX / +DI / −DI. Expects columns: high, low, close."""
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    alpha = 1.0 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_smooth = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_smooth = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_smooth / atr_w.where(atr_w != 0)
    minus_di = 100.0 * minus_smooth / atr_w.where(atr_w != 0)
    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.where(di_sum != 0)
    adx_line = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    return pd.DataFrame(
        {
            "plus_di": plus_di.astype("float64"),
            "minus_di": minus_di.astype("float64"),
            "adx": adx_line.astype("float64"),
        }
    )


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """Slow stochastic %K / %D. Expects columns: high, low, close."""
    lowest = df["low"].rolling(window=k_period, min_periods=k_period).min()
    highest = df["high"].rolling(window=k_period, min_periods=k_period).max()
    denom = (highest - lowest).where(highest != lowest)
    pct_k = 100.0 * (df["close"] - lowest) / denom
    pct_d = pct_k.rolling(window=d_period, min_periods=d_period).mean()
    return pd.DataFrame({"stoch_k": pct_k.astype("float64"), "stoch_d": pct_d.astype("float64")})


def relative_volume(series: pd.Series, period: int = 20) -> pd.Series:
    """Volume ÷ rolling average volume (RVOL). Values > 1.0 = above average."""
    avg = series.rolling(window=period, min_periods=max(3, period // 2)).mean()
    # Avoid pd.NA → object dtype → FutureWarning on fillna downcasting.
    ratio = series.astype("float64") / avg.where(avg != 0)
    return ratio.fillna(1.0).astype("float64")


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
    rvol_period: int = 20,
) -> pd.DataFrame:
    """Return a copy of `df` with all standard indicator columns attached.
    `df` must have columns: open, high, low, close.
    Optional ``tick_volume`` enables relative volume (``rvol``).
    """
    out = df.copy()
    out[f"ema_{ema_period}"] = ema(out["close"], ema_period)
    if ema_period != 20:
        out["ema_20"] = ema(out["close"], 20)
    out["rsi"] = rsi(out["close"], rsi_period)

    macd_df = macd(out["close"], macd_fast, macd_slow, macd_signal)
    out = out.join(macd_df)

    bb_df = bollinger_bands(out["close"], bb_period, bb_std)
    out = out.join(bb_df)

    out["atr"] = atr(out, atr_period)
    out = out.join(adx(out))
    out = out.join(stochastic(out))
    if "tick_volume" in out.columns:
        out["rvol"] = relative_volume(out["tick_volume"].astype(float), rvol_period)
    else:
        out["rvol"] = 1.0
    return out
