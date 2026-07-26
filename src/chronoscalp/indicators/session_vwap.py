"""Session VWAP and Asian-range helpers for institutional trend bias."""

from __future__ import annotations

from datetime import time

import pandas as pd

# Session opens in GMT (UTC).
SESSION_OPENS_GMT: dict[str, time] = {
    "asia": time(0, 0),
    "london": time(7, 0),
    "new_york": time(12, 0),
}
ASIAN_RANGE_END_GMT = time(7, 0)


def _ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must be DatetimeIndex")
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def active_session_name(ts: pd.Timestamp) -> str:
    """Return asia / london / new_york for a UTC timestamp."""
    t = ts.timetz().replace(tzinfo=None) if hasattr(ts, "timetz") else ts.time()
    if t >= SESSION_OPENS_GMT["new_york"]:
        return "new_york"
    if t >= SESSION_OPENS_GMT["london"]:
        return "london"
    return "asia"


def session_open_timestamp(ts: pd.Timestamp) -> pd.Timestamp:
    """UTC timestamp of the current session open on the same calendar day."""
    ts = _as_utc(ts)
    name = active_session_name(ts)
    open_t = SESSION_OPENS_GMT[name]
    return pd.Timestamp(
        year=ts.year, month=ts.month, day=ts.day, hour=open_t.hour, minute=open_t.minute, tz="UTC"
    )


def asian_range_midpoint(df: pd.DataFrame, as_of: pd.Timestamp | None = None) -> float | None:
    """Midpoint of Asian session high/low (00:00–07:00 GMT) for the as_of day."""
    if df.empty:
        return None
    frame = _ensure_utc_index(df)
    as_of = _as_utc(as_of or frame.index[-1])
    day_start = as_of.normalize()
    asian_end = day_start + pd.Timedelta(hours=7)
    window = frame[(frame.index >= day_start) & (frame.index < asian_end)]
    if window.empty:
        prev_start = day_start - pd.Timedelta(days=1)
        prev_end = prev_start + pd.Timedelta(hours=7)
        window = frame[(frame.index >= prev_start) & (frame.index < prev_end)]
    if window.empty:
        return None
    return float((window["high"].max() + window["low"].min()) / 2.0)


def session_vwap(df: pd.DataFrame, as_of: pd.Timestamp | None = None) -> float | None:
    """Typical-price VWAP from the current session open to ``as_of``."""
    if df.empty or "close" not in df.columns:
        return None
    frame = _ensure_utc_index(df)
    as_of = _as_utc(as_of or frame.index[-1])
    start = session_open_timestamp(as_of)
    window = frame[(frame.index >= start) & (frame.index <= as_of)]
    if window.empty:
        return None
    typical = (window["high"] + window["low"] + window["close"]) / 3.0
    if "tick_volume" in window.columns:
        vol = window["tick_volume"].astype(float).clip(lower=1.0)
    else:
        vol = pd.Series(1.0, index=window.index)
    denom = float(vol.sum())
    if denom <= 0:
        return float(typical.iloc[-1])
    return float((typical * vol).sum() / denom)


def previous_day_high_low(
    df: pd.DataFrame, as_of: pd.Timestamp | None = None
) -> tuple[float | None, float | None]:
    """Previous calendar-day high/low from OHLCV bars."""
    if df.empty:
        return None, None
    frame = _ensure_utc_index(df)
    as_of = _as_utc(as_of or frame.index[-1])
    day_start = as_of.normalize()
    prev_start = day_start - pd.Timedelta(days=1)
    prev = frame[(frame.index >= prev_start) & (frame.index < day_start)]
    if prev.empty:
        return None, None
    return float(prev["high"].max()), float(prev["low"].min())


def session_high_low(
    df: pd.DataFrame, as_of: pd.Timestamp | None = None
) -> tuple[float | None, float | None]:
    """High/low of the active session up to ``as_of``."""
    if df.empty:
        return None, None
    frame = _ensure_utc_index(df)
    as_of = _as_utc(as_of or frame.index[-1])
    start = session_open_timestamp(as_of)
    window = frame[(frame.index >= start) & (frame.index <= as_of)]
    if window.empty:
        return None, None
    return float(window["high"].max()), float(window["low"].min())
