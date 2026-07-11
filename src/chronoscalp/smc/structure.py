"""Smart Money Concepts (SMC) structure detection.

A real, self-contained implementation (no external SMC library) of the
building blocks referenced in the original project brief: swing points,
market structure shifts, order blocks, fair value gaps, and liquidity
sweeps. Deliberately simpler than a full commercial SMC engine — treat as a
Phase 5/6 extension surface (see docs/ROADMAP.md).

All functions take/return pandas DataFrames indexed by time with columns
open/high/low/close, and are pure (no I/O, no broker calls) so they're easy
to unit test and to run inside the backtester without look-ahead bias
(each detector only uses information available up to the current bar,
except swing confirmation which by definition lags `right` bars — documented
per function).
"""

from __future__ import annotations

import pandas as pd


def detect_swing_points(df: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
    """Fractal swing high/low detection.

    A bar at index i is a swing high if its `high` is the max within
    [i-left, i+right], and a swing low if its `low` is the min within the
    same window. NOTE: a swing point at bar i is only confirmed once bar
    i+right has closed — this lag is real and must be respected by callers
    (i.e. don't use `swing_high`/`swing_low` at the most recent `right` bars
    as if they were already confirmed).
    """
    out = df.copy()
    window = left + right + 1
    rolling_max = df["high"].rolling(window, center=True).max()
    rolling_min = df["low"].rolling(window, center=True).min()
    out["swing_high"] = df["high"] == rolling_max
    out["swing_low"] = df["low"] == rolling_min
    # Rolling(center=True) needs right-side data that isn't available live;
    # explicitly null out the last `right` bars to make the lag obvious.
    out.iloc[-right:, out.columns.get_loc("swing_high")] = False
    out.iloc[-right:, out.columns.get_loc("swing_low")] = False
    return out


def detect_market_structure(swings: pd.DataFrame) -> pd.DataFrame:
    """Break of Structure (BOS) / Change of Character (CHoCH) detection from
    confirmed swing points.

    - BOS: price closes beyond the most recent swing high (bullish BOS) or
      swing low (bearish BOS) *in the direction of the prevailing trend* —
      trend continuation.
    - CHoCH: price closes beyond the most recent opposite swing point
      *against* the prevailing trend — potential reversal.
    """
    out = swings.copy()
    out["structure_event"] = ""

    last_swing_high: float | None = None
    last_swing_low: float | None = None
    trend = "neutral"

    events = []
    for _, row in out.iterrows():
        event = ""
        close = row["close"]

        if last_swing_high is not None and close > last_swing_high:
            event = "bos_up" if trend in ("bullish", "neutral") else "choch_up"
            trend = "bullish"
        elif last_swing_low is not None and close < last_swing_low:
            event = "bos_down" if trend in ("bearish", "neutral") else "choch_down"
            trend = "bearish"

        if row.get("swing_high"):
            last_swing_high = row["high"]
        if row.get("swing_low"):
            last_swing_low = row["low"]

        events.append(event)

    out["structure_event"] = events
    out["trend"] = _trend_from_events(events)
    return out


def _trend_from_events(events: list[str]) -> list[str]:
    trend = "neutral"
    result = []
    for e in events:
        if e in ("bos_up", "choch_up"):
            trend = "bullish"
        elif e in ("bos_down", "choch_down"):
            trend = "bearish"
        result.append(trend)
    return result


def detect_order_blocks(df: pd.DataFrame, swings: pd.DataFrame) -> pd.DataFrame:
    """Order blocks: the last opposite-direction candle immediately before an
    impulsive move that breaks a swing point.

    - Bullish order block: last bearish candle before an up-move that breaks
      the prior swing high.
    - Bearish order block: last bullish candle before a down-move that
      breaks the prior swing low.
    """
    out = df.copy()
    out["bullish_ob"] = False
    out["bearish_ob"] = False

    structure = detect_market_structure(swings)
    is_bearish_candle = df["close"] < df["open"]
    is_bullish_candle = df["close"] > df["open"]

    for i in range(1, len(structure)):
        event = structure["structure_event"].iloc[i]
        if event in ("bos_up", "choch_up") and is_bearish_candle.iloc[i - 1]:
            out.iloc[i - 1, out.columns.get_loc("bullish_ob")] = True
        elif event in ("bos_down", "choch_down") and is_bullish_candle.iloc[i - 1]:
            out.iloc[i - 1, out.columns.get_loc("bearish_ob")] = True

    return out


def detect_fair_value_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """3-candle imbalance (Fair Value Gap):

    - Bullish FVG: candle[i-2].high < candle[i].low (gap left unfilled below price)
    - Bearish FVG: candle[i-2].low > candle[i].high
    """
    out = df.copy()
    out["fvg_bullish"] = False
    out["fvg_bearish"] = False
    out["fvg_top"] = float("nan")
    out["fvg_bottom"] = float("nan")

    high, low = df["high"], df["low"]
    for i in range(2, len(df)):
        if high.iloc[i - 2] < low.iloc[i]:
            out.iloc[i, out.columns.get_loc("fvg_bullish")] = True
            out.iloc[i, out.columns.get_loc("fvg_bottom")] = high.iloc[i - 2]
            out.iloc[i, out.columns.get_loc("fvg_top")] = low.iloc[i]
        elif low.iloc[i - 2] > high.iloc[i]:
            out.iloc[i, out.columns.get_loc("fvg_bearish")] = True
            out.iloc[i, out.columns.get_loc("fvg_top")] = low.iloc[i - 2]
            out.iloc[i, out.columns.get_loc("fvg_bottom")] = high.iloc[i]

    return out


def detect_liquidity_sweeps(df: pd.DataFrame, swings: pd.DataFrame) -> pd.DataFrame:
    """Liquidity sweep: a wick pierces a prior confirmed swing high/low and
    the candle closes back on the other side of it (rejection), suggesting
    stop-loss/liquidity was grabbed before a reversal.
    """
    out = df.copy()
    out["liquidity_sweep_high"] = False
    out["liquidity_sweep_low"] = False

    last_swing_high: float | None = None
    last_swing_low: float | None = None

    for i in range(len(df)):
        row = df.iloc[i]
        swing_row = swings.iloc[i]

        if last_swing_high is not None and row["high"] > last_swing_high and row["close"] < last_swing_high:
            out.iloc[i, out.columns.get_loc("liquidity_sweep_high")] = True
        if last_swing_low is not None and row["low"] < last_swing_low and row["close"] > last_swing_low:
            out.iloc[i, out.columns.get_loc("liquidity_sweep_low")] = True

        if swing_row.get("swing_high"):
            last_swing_high = row["high"]
        if swing_row.get("swing_low"):
            last_swing_low = row["low"]

    return out


def enrich_with_smc(df: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
    """Convenience: run the full SMC detector pipeline and merge all columns."""
    swings = detect_swing_points(df, left, right)
    structure = detect_market_structure(swings)
    order_blocks = detect_order_blocks(df, swings)
    fvgs = detect_fair_value_gaps(df)
    sweeps = detect_liquidity_sweeps(df, swings)

    out = df.copy()
    for extra, cols in [
        (structure, ["swing_high", "swing_low", "structure_event", "trend"]),
        (order_blocks, ["bullish_ob", "bearish_ob"]),
        (fvgs, ["fvg_bullish", "fvg_bearish", "fvg_top", "fvg_bottom"]),
        (sweeps, ["liquidity_sweep_high", "liquidity_sweep_low"]),
    ]:
        out = out.join(extra[cols])
    return out
