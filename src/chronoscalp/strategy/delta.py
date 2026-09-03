"""Delta: cost-aware multi-timeframe structure strategy for XAUUSD/EURUSD.

Delta deliberately uses a small, explainable rule set: higher-timeframe regime,
M1 liquidity event, close confirmation, and structure/ATR based trade geometry.
It does not forecast returns or claim a fixed win rate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from chronoscalp.strategy.operator_style import evaluate_operator_style
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


def merge_symbol_config(config: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Return ``config`` with ``symbol_overrides[<root>]`` applied on top.

    XAUUSD moves in dollars while EURUSD moves in fractions of a pip, so one
    shared stop band cannot fit both. Each symbol may override any Delta key.
    """
    from chronoscalp.strategy.symbol_catalog import merge_symbol_overrides

    return merge_symbol_overrides(config, symbol)


def reference_stop_atr(
    config: dict[str, Any], trigger_atr: float, higher_frames: list[pd.DataFrame]
) -> float:
    """ATR the stop distance is scaled from.

    Defaults to the trigger frame for backwards compatibility. With
    ``stop_atr_source: htf`` the stop scales off a higher timeframe instead,
    because an M1 ATR is about one candle of noise: a stop of a small multiple
    of it sits inside the ordinary spread-plus-noise band and is taken out
    before the setup can resolve either way. ``stop_atr_htf_index`` selects
    which higher frame (0 = nearest), clamped to what was supplied. Falls back
    to the trigger ATR whenever the requested frame has no usable ATR.
    """
    if str(config.get("stop_atr_source", "trigger")).lower() != "htf":
        return trigger_atr
    if not higher_frames:
        return trigger_atr
    index = min(max(0, int(config.get("stop_atr_htf_index", 0))), len(higher_frames) - 1)
    frame = higher_frames[index]
    if frame is None or len(frame) == 0 or "atr" not in frame.columns:
        return trigger_atr
    value = frame["atr"].iloc[-1]
    if pd.isna(value) or float(value) <= 0:
        return trigger_atr
    return max(trigger_atr, float(value))


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
    ATR buffer, clear a configurable share of round-trip spread cost, and are
    scaled from ``reference_stop_atr`` — a higher timeframe when
    ``stop_atr_source`` is ``htf`` — so the stop is not one M1 candle wide.
    Per-symbol overrides are merged by :func:`merge_symbol_config`.
    """
    cfg = merge_symbol_config(config or {}, symbol)
    allowed = {_root(item) for item in cfg.get("allowed_symbols", ["XAUUSD", "EURUSD"])}
    if _root(symbol) not in allowed:
        return _none(symbol, "symbol_blocked")
    lookback = max(5, int(cfg.get("structure_lookback", 12)))
    if trigger_df is None or len(trigger_df) < lookback + 3:
        return _none(symbol, "insufficient_bars")

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

    style_cfg = cfg.get("operator_style") or {}
    style_on = bool(style_cfg.get("enabled", False))
    allowed_setups = {
        str(item)
        for item in (
            style_cfg.get("allowed_setups")
            or ["sweep_reclaim", "breakout_retest", "fade_extension", "htf_pullback"]
        )
    }
    sweep_allowed = bool(allowed_setups & {"sweep_reclaim", "breakout_retest"})
    m15 = higher_frames[0] if higher_frames else None
    m5 = higher_frames[1] if len(higher_frames) > 1 else m15
    style_setup = ""
    direction = TrendDirection.NEUTRAL
    if style_on:
        verdict = evaluate_operator_style(m15, m5, config=style_cfg)
        if verdict.reason == "weak_adx":
            return _none(symbol, "weak_adx")
        if verdict.allow and verdict.setup in allowed_setups:
            direction = verdict.direction
            style_setup = verdict.setup
        elif not sweep_allowed:
            return _none(symbol, verdict.reason or "no_operator_setup")

    if not style_setup:
        direction = delta_regime(
            higher_frames,
            ema_period=ema_period,
            slope_bars=max(1, int(cfg.get("slope_bars", 3))),
        )
        if direction == TrendDirection.NEUTRAL:
            return _none(symbol, "regime_neutral")

    history = trigger_df.iloc[-(lookback + 2) : -2]
    range_high = float(history["high"].max())
    range_low = float(history["low"].min())
    close = float(last["close"])
    candle_range = max(float(last["high"]) - float(last["low"]), 1e-12)
    body = abs(close - float(last["open"]))

    if style_setup:
        if direction == TrendDirection.BULLISH:
            structural_stop = min(float(prev["low"]), float(last["low"]))
            signal_type = SignalType.BUY
        else:
            structural_stop = max(float(prev["high"]), float(last["high"]))
            signal_type = SignalType.SELL
        setup = style_setup
    else:
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
        if setup not in allowed_setups:
            return _none(symbol, "setup_not_allowed")

    ref_atr = reference_stop_atr(cfg, atr, higher_frames)
    buffer = float(cfg.get("stop_buffer_atr", 0.20)) * ref_atr
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

    # Entering and exiting each pay the spread, so a stop only a few spreads
    # wide hands most of the risk budget to costs. Require the round trip to be
    # at most ``max_cost_fraction_of_risk`` of the money at risk.
    cost_fraction = float(cfg.get("max_cost_fraction_of_risk", 0.0))
    cost_floor = (2.0 * spread_distance) / cost_fraction if cost_fraction > 0 else 0.0

    max_stop = float(cfg.get("max_stop_atr", 2.5)) * ref_atr
    if cost_floor > max_stop:
        return _none(symbol, "cost_exceeds_stop_cap")

    stop_distance = max(
        structural_distance,
        float(cfg.get("min_stop_atr", 0.8)) * ref_atr,
        float(cfg.get("min_stop_spread_multiple", 2.0)) * spread_distance,
        cost_floor,
    )
    if stop_distance > max_stop:
        return _none(symbol, "stop_too_wide")

    rr = max(1.5, float(cfg.get("reward_risk_ratio", 1.8)))
    if signal_type == SignalType.BUY:
        stop_loss, take_profit = close - stop_distance, close + rr * stop_distance
    else:
        stop_loss, take_profit = close + stop_distance, close - rr * stop_distance

    confidence = min(
        0.75,
        0.55 + min(0.10, (rvol - 1.0) * 0.08) + (0.05 if setup == "sweep_reclaim" else 0.02),
    )
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
