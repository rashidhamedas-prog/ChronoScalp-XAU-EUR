"""Delta: cost-aware multi-timeframe structure strategy for XAUUSD/EURUSD.

Delta deliberately uses a small, explainable rule set: higher-timeframe regime,
M1 liquidity event, close confirmation, and structure/ATR based trade geometry.
It does not forecast returns or claim a fixed win rate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from chronoscalp.utils.types import Signal, SignalType, Timeframe, TrendDirection


def _none(symbol: str, reason: str) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=SignalType.NONE,
        timestamp=datetime.now(UTC),
        entry_price=0.0,
        stop_loss=0.0,
        take_profit=0.0,
        timeframe=Timeframe.M1,
        reason=f"delta:{reason}",
        strategy="delta",
    )


def _root(symbol: str) -> str:
    return str(symbol).upper().split("_", 1)[0]


def _frame_bias(df: pd.DataFrame, ema_col: str, slope_bars: int) -> TrendDirection:
    if df is None or len(df) <= slope_bars:
        return TrendDirection.NEUTRAL
    last = df.iloc[-1]
    prior = df.iloc[-1 - slope_bars]
    required = ("close", ema_col, "rsi", "atr")
    if any(pd.isna(last.get(key)) for key in required) or pd.isna(prior.get(ema_col)):
        return TrendDirection.NEUTRAL
    close = float(last["close"])
    ema = float(last[ema_col])
    slope = ema - float(prior[ema_col])
    rsi = float(last["rsi"])
    atr = float(last["atr"])
    if atr <= 0:
        return TrendDirection.NEUTRAL
    # Avoid buying/selling an already exhausted extension from its mean.
    if abs(close - ema) > 2.5 * atr:
        return TrendDirection.NEUTRAL
    if close > ema and slope > 0 and 52 <= rsi <= 70:
        return TrendDirection.BULLISH
    if close < ema and slope < 0 and 30 <= rsi <= 48:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL


def delta_regime(
    higher_frames: list[pd.DataFrame], *, ema_period: int = 50, slope_bars: int = 3
) -> TrendDirection:
    """Return a direction only when every supplied higher timeframe agrees."""
    if len(higher_frames) < 2:
        return TrendDirection.NEUTRAL
    biases = [_frame_bias(frame, f"ema_{ema_period}", slope_bars) for frame in higher_frames]
    if biases and all(bias == biases[0] != TrendDirection.NEUTRAL for bias in biases):
        return biases[0]
    return TrendDirection.NEUTRAL


def _signal_timestamp(row: pd.Series) -> datetime:
    return row.name.to_pydatetime() if isinstance(row.name, pd.Timestamp) else datetime.now(UTC)


def generate_delta_signal(
    symbol: str,
    trigger_df: pd.DataFrame,
    higher_frames: list[pd.DataFrame],
    *,
    config: dict[str, Any] | None = None,
    symbol_spec: dict[str, Any] | None = None,
    spread_pips: float | None = None,
    ema_period: int = 50,
) -> Signal:
    """Generate a Delta signal from completed M1/M5/M15 bars.

    Entry requires aligned HTF bias plus either a sweep/reclaim of the recent
    M1 range or a close-and-retest breakout. Stops sit beyond structure with an
    ATR buffer and must also clear estimated spread costs.
    """
    cfg = config or {}
    allowed = {_root(item) for item in cfg.get("allowed_symbols", ["XAUUSD", "EURUSD"])}
    if _root(symbol) not in allowed:
        return _none(symbol, "symbol_blocked")
    lookback = max(5, int(cfg.get("structure_lookback", 12)))
    if trigger_df is None or len(trigger_df) < lookback + 3:
        return _none(symbol, "insufficient_bars")

    direction = delta_regime(
        higher_frames,
        ema_period=ema_period,
        slope_bars=max(1, int(cfg.get("slope_bars", 3))),
    )
    if direction == TrendDirection.NEUTRAL:
        return _none(symbol, "regime_neutral")

    last = trigger_df.iloc[-1]
    prev = trigger_df.iloc[-2]
    required = ("open", "high", "low", "close", "atr", "rvol")
    if any(pd.isna(last.get(key)) for key in required):
        return _none(symbol, "indicators_nan")
    atr = float(last["atr"])
    if atr <= 0:
        return _none(symbol, "atr_zero")

    atr_ratio = atr / float(last["close"])
    min_atr_ratio = float(cfg.get("min_atr_close_ratio", 0.00004))
    max_atr_ratio = float(cfg.get("max_atr_close_ratio", 0.004))
    if not min_atr_ratio <= atr_ratio <= max_atr_ratio:
        return _none(symbol, "volatility_regime")
    rvol = float(last.get("rvol", 0.0) or 0.0)
    if rvol < float(cfg.get("rvol_min", 1.15)):
        return _none(symbol, "low_rvol")

    history = trigger_df.iloc[-(lookback + 2) : -2]
    range_high = float(history["high"].max())
    range_low = float(history["low"].min())
    close = float(last["close"])
    candle_range = max(float(last["high"]) - float(last["low"]), 1e-12)
    body = abs(close - float(last["open"]))
    if body / candle_range < float(cfg.get("min_body_fraction", 0.45)):
        return _none(symbol, "weak_close")

    if direction == TrendDirection.BULLISH:
        sweep = float(prev["low"]) < range_low and float(prev["close"]) > range_low
        retest = float(prev["close"]) > range_high and float(last["low"]) <= range_high < close
        confirmed = close > float(last["open"]) and close > float(prev["close"])
        if not confirmed or not (sweep or retest):
            return _none(symbol, "no_long_trigger")
        structural_stop = min(float(prev["low"]), float(last["low"]))
        signal_type = SignalType.BUY
        setup = "sweep_reclaim" if sweep else "breakout_retest"
    else:
        sweep = float(prev["high"]) > range_high and float(prev["close"]) < range_high
        retest = float(prev["close"]) < range_low and float(last["high"]) >= range_low > close
        confirmed = close < float(last["open"]) and close < float(prev["close"])
        if not confirmed or not (sweep or retest):
            return _none(symbol, "no_short_trigger")
        structural_stop = max(float(prev["high"]), float(last["high"]))
        signal_type = SignalType.SELL
        setup = "sweep_reclaim" if sweep else "breakout_retest"

    buffer = float(cfg.get("stop_buffer_atr", 0.20)) * atr
    structural_distance = (
        close - structural_stop + buffer
        if signal_type == SignalType.BUY
        else structural_stop - close + buffer
    )
    spec = symbol_spec or {}
    pip_size = float(spec.get("pip_size", 0.0) or 0.0)
    effective_spread_pips = float(
        spread_pips if spread_pips is not None else spec.get("typical_spread_pips", 0.0) or 0.0
    )
    spread_distance = effective_spread_pips * pip_size
    stop_distance = max(
        structural_distance,
        float(cfg.get("min_stop_atr", 0.8)) * atr,
        float(cfg.get("min_stop_spread_multiple", 2.0)) * spread_distance,
    )
    if stop_distance > float(cfg.get("max_stop_atr", 2.5)) * atr:
        return _none(symbol, "stop_too_wide")

    rr = max(1.5, float(cfg.get("reward_risk_ratio", 1.8)))
    if signal_type == SignalType.BUY:
        stop_loss, take_profit = close - stop_distance, close + rr * stop_distance
    else:
        stop_loss, take_profit = close + stop_distance, close - rr * stop_distance

    confidence = min(0.75, 0.55 + min(0.10, (rvol - 1.0) * 0.08) + (0.05 if sweep else 0.02))
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        timestamp=_signal_timestamp(last),
        entry_price=close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=confidence,
        reason=f"delta,{setup},trend={direction.value},rvol={rvol:.2f}",
        timeframe=Timeframe.M1,
        strategy="delta",
    )
