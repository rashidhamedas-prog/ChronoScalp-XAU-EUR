"""Session VWAP and Asian-range helpers for institutional trend bias.

Session boundaries use IANA zones (DST-aware), matching ``SessionFilter``.
Timestamps must already be true UTC before calling these helpers.
"""

from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from chronoscalp.logging_setup import logger

# Local wall-clock opens in each session's IANA zone (DST-aware).
SESSION_OPENS_LOCAL: dict[str, tuple[str, time]] = {
    "asia": ("Asia/Tokyo", time(9, 0)),  # Tokyo morning ≈ prior FX Asia open
    "london": ("Europe/London", time(8, 0)),
    "new_york": ("America/New_York", time(8, 0)),
}
# Asian range ends at London open (Europe/London 08:00).
ASIAN_RANGE_END_ZONE = "Europe/London"
ASIAN_RANGE_END_LOCAL = time(8, 0)


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError, Exception):
        logger.error("Session VWAP timezone {!r} invalid — failing closed", name)
        return None


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
    """Return asia / london / new_york for a true-UTC timestamp."""
    ts = _as_utc(ts)
    # Evaluate in priority NY > London > Asia using each zone's local clock.
    ny_zone = _zone(SESSION_OPENS_LOCAL["new_york"][0])
    lon_zone = _zone(SESSION_OPENS_LOCAL["london"][0])
    if ny_zone is None or lon_zone is None:
        return "asia"
    local_ny = ts.tz_convert(ny_zone).timetz().replace(tzinfo=None)
    local_lon = ts.tz_convert(lon_zone).timetz().replace(tzinfo=None)
    if local_ny >= SESSION_OPENS_LOCAL["new_york"][1]:
        return "new_york"
    if local_lon >= SESSION_OPENS_LOCAL["london"][1]:
        return "london"
    return "asia"


def session_open_timestamp(ts: pd.Timestamp) -> pd.Timestamp:
    """UTC timestamp of the current session open (IANA-local wall clock)."""
    ts = _as_utc(ts)
    name = active_session_name(ts)
    zone_name, open_t = SESSION_OPENS_LOCAL[name]
    zone = _zone(zone_name)
    if zone is None:
        # Fail closed to UTC midnight rather than inventing GMT anchors.
        return ts.normalize()
    local = ts.tz_convert(zone)
    open_local = local.replace(
        hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0
    )
    if local.timetz().replace(tzinfo=None) < open_t:
        open_local = open_local - pd.Timedelta(days=1)
    return open_local.tz_convert("UTC")


def asian_range_midpoint(df: pd.DataFrame, as_of: pd.Timestamp | None = None) -> float | None:
    """Midpoint of Asian session high/low until London open for the as_of day."""
    if df.empty:
        return None
    frame = _ensure_utc_index(df)
    as_of = _as_utc(as_of or frame.index[-1])
    lon_zone = _zone(ASIAN_RANGE_END_ZONE)
    if lon_zone is None:
        return None
    local = as_of.tz_convert(lon_zone)
    london_open_local = local.replace(
        hour=ASIAN_RANGE_END_LOCAL.hour,
        minute=ASIAN_RANGE_END_LOCAL.minute,
        second=0,
        microsecond=0,
    )
    if local.timetz().replace(tzinfo=None) < ASIAN_RANGE_END_LOCAL:
        london_open_local = london_open_local - pd.Timedelta(days=1)
        day_start_local = london_open_local - pd.Timedelta(hours=8)
    else:
        day_start_local = london_open_local - pd.Timedelta(hours=8)
    # Approximate Asia window as the 8 hours before London open.
    start_utc = day_start_local.tz_convert("UTC")
    end_utc = london_open_local.tz_convert("UTC")
    window = frame[(frame.index >= start_utc) & (frame.index < end_utc)]
    if window.empty:
        prev_end = end_utc - pd.Timedelta(days=1)
        prev_start = start_utc - pd.Timedelta(days=1)
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
        vol = window["tick_volume"].astype(float).clip(lower=0.0)
    elif "volume" in window.columns:
        vol = window["volume"].astype(float).clip(lower=0.0)
    else:
        vol = pd.Series(1.0, index=window.index)
    denom = float(vol.sum())
    if denom <= 0:
        return float(typical.iloc[-1])
    return float((typical * vol).sum() / denom)


def previous_day_high_low(
    df: pd.DataFrame, as_of: pd.Timestamp | None = None
) -> tuple[float | None, float | None]:
    """Previous calendar-day high/low from OHLCV bars (UTC day boundary)."""
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
