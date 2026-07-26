"""Institutional trend filter: Session VWAP + Asian midpoint (M15/M5)."""

from __future__ import annotations

import pandas as pd

from chronoscalp.indicators.session_vwap import asian_range_midpoint, session_vwap
from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import TrendDirection


def institutional_bias(df: pd.DataFrame) -> TrendDirection:
    """Bias from close vs session VWAP and Asian range midpoint.

    Bullish: close > VWAP AND close > Asian midpoint.
    Bearish: close < VWAP AND close < Asian midpoint.
    Otherwise NEUTRAL.
    """
    if df is None or df.empty:
        return TrendDirection.NEUTRAL
    last = df.iloc[-1]
    close = float(last["close"])
    as_of = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else None
    vwap = session_vwap(df, as_of=as_of)
    mid = asian_range_midpoint(df, as_of=as_of)
    if vwap is None or mid is None:
        return TrendDirection.NEUTRAL
    if close > vwap and close > mid:
        return TrendDirection.BULLISH
    if close < vwap and close < mid:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL


def aligned_institutional_bias(frames: list[pd.DataFrame]) -> TrendDirection:
    """Require every frame's institutional bias to agree (non-neutral)."""
    if not frames:
        return TrendDirection.NEUTRAL
    biases = [institutional_bias(df) for df in frames]
    unique = set(biases)
    if len(unique) == 1 and TrendDirection.NEUTRAL not in unique:
        bias = unique.pop()
        logger.debug("Institutional bias aligned={}", bias.value)
        return bias
    logger.debug("Institutional bias rejected biases={}", [b.value for b in biases])
    return TrendDirection.NEUTRAL
