"""Institutional entry triggers: liquidity sweep + MSS + RVOL + SMC / ultra-scalp."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from chronoscalp.indicators.session_vwap import (
    previous_day_high_low,
    session_high_low,
    session_vwap,
)
from chronoscalp.logging_setup import logger
from chronoscalp.ml.features import extract_setup_features
from chronoscalp.ml.scorer import predict_setup_probability
from chronoscalp.strategy.confluence import confluence_ok
from chronoscalp.utils.types import Signal, SignalType, Timeframe, TrendDirection


def _no_signal(symbol: str, timeframe: Timeframe, reason: str = "") -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=SignalType.NONE,
        timestamp=datetime.utcnow(),
        entry_price=0.0,
        stop_loss=0.0,
        take_profit=0.0,
        timeframe=timeframe,
        reason=reason,
    )


def _last_confirmed_swing(df: pd.DataFrame, kind: str, lookback: int = 40) -> float | None:
    """Most recent confirmed swing high/low price (needs swing_* columns)."""
    if df.empty or kind not in df.columns:
        return None
    tail = df.iloc[-lookback:] if len(df) > lookback else df
    hits = tail[tail[kind].astype(bool)]
    if hits.empty:
        return None
    col = "high" if "high" in kind else "low"
    return float(hits.iloc[-1][col])


def liquidity_sweep_reclaim(
    df: pd.DataFrame, direction: TrendDirection, *, max_bars: int = 2
) -> bool:
    """True if price pierced PDH/PDL or session H/L then closed back inside within ``max_bars``."""
    if df is None or len(df) < max_bars + 1:
        return False
    as_of = df.index[-1]
    pdh, pdl = previous_day_high_low(df, as_of=as_of)
    sh, sl = session_high_low(df.iloc[:-1], as_of=as_of)  # prior session extremes
    levels_high = [x for x in (pdh, sh) if x is not None]
    levels_low = [x for x in (pdl, sl) if x is not None]
    if direction == TrendDirection.BULLISH:
        if not levels_low:
            return False
        level = min(levels_low)
        # Look at last max_bars+1 bars: pierce below then reclaim
        window = df.iloc[-(max_bars + 1) :]
        pierced = bool((window["low"] < level).any())
        reclaimed = float(window.iloc[-1]["close"]) > level
        return pierced and reclaimed
    if direction == TrendDirection.BEARISH:
        if not levels_high:
            return False
        level = max(levels_high)
        window = df.iloc[-(max_bars + 1) :]
        pierced = bool((window["high"] > level).any())
        reclaimed = float(window.iloc[-1]["close"]) < level
        return pierced and reclaimed
    return False


def market_structure_shift(df: pd.DataFrame, direction: TrendDirection) -> bool:
    """MSS: close breaks most recent swing high (long) or swing low (short)."""
    if df is None or df.empty:
        return False
    last_close = float(df.iloc[-1]["close"])
    if direction == TrendDirection.BULLISH:
        swing = _last_confirmed_swing(df, "swing_high")
        return swing is not None and last_close > swing
    if direction == TrendDirection.BEARISH:
        swing = _last_confirmed_swing(df, "swing_low")
        return swing is not None and last_close < swing
    return False


def generate_institutional_entry(
    symbol: str,
    trigger_df: pd.DataFrame,
    trend: TrendDirection,
    timeframe: Timeframe,
    *,
    use_smc_confluence: bool = True,
    use_liquidity_volume: bool = False,
    min_reward_risk_ratio: float = 1.5,
    atr_stop_multiple: float = 1.5,
    atr_target_multiple: float = 2.25,
    rvol_min: float = 1.5,
    strategy_id: str = "institutional",
) -> Signal:
    """Normal-mode entry: sweep reclaim + MSS + RVOL + optional SMC confluence."""
    if trend == TrendDirection.NEUTRAL or trigger_df is None or len(trigger_df) < 5:
        return _no_signal(symbol, timeframe, reason="trend_neutral")

    last = trigger_df.iloc[-1]
    if any(pd.isna(last.get(c)) for c in ("close", "atr", "rvol")):
        return _no_signal(symbol, timeframe, reason="indicators_nan")

    rvol = float(last.get("rvol", 1.0) or 1.0)
    if rvol < rvol_min:
        logger.info("{} entry rejected: low_rvol={:.2f} < {:.2f}", symbol, rvol, rvol_min)
        return _no_signal(symbol, timeframe, reason="low_rvol")

    if not liquidity_sweep_reclaim(trigger_df, trend):
        return _no_signal(symbol, timeframe, reason="no_liquidity_sweep")
    if not market_structure_shift(trigger_df, trend):
        return _no_signal(symbol, timeframe, reason="no_mss")

    ok, tags = confluence_ok(
        last,
        trend,
        use_smc_confluence=use_smc_confluence,
        use_liquidity_volume=use_liquidity_volume,
    )
    if not ok:
        return _no_signal(symbol, timeframe, reason="no_confluence")

    atr_value = float(last["atr"])
    entry_price = float(last["close"])
    if trend == TrendDirection.BULLISH:
        signal_type = SignalType.BUY
        stop_loss = entry_price - atr_stop_multiple * atr_value
        take_profit = entry_price + atr_target_multiple * atr_value
    else:
        signal_type = SignalType.SELL
        stop_loss = entry_price + atr_stop_multiple * atr_value
        take_profit = entry_price - atr_target_multiple * atr_value

    reason_parts = [
        "institutional_entry",
        f"trend={trend.value}",
        f"rvol={rvol:.2f}",
        "liquidity_sweep",
        "mss",
        *tags,
    ]
    signal = Signal(
        symbol=symbol,
        signal_type=signal_type,
        timestamp=last.name if isinstance(last.name, datetime) else datetime.utcnow(),
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=predict_setup_probability(
            extract_setup_features(
                trigger_row=last,
                trend=trend,
                signal_type=signal_type,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        ),
        reason=", ".join(reason_parts),
        timeframe=timeframe,
        strategy=strategy_id,
    )
    if signal.risk_reward_ratio < min_reward_risk_ratio:
        return _no_signal(symbol, timeframe, reason="rr_fail")
    logger.info("{} institutional entry {} {}", symbol, signal_type.value, signal.reason)
    return signal


def generate_ultra_scalp_v3(
    symbol: str,
    trigger_df: pd.DataFrame,
    trend: TrendDirection,
    timeframe: Timeframe,
    *,
    min_reward_risk_ratio: float = 1.0,
    atr_stop_multiple: float = 2.5,
    atr_target_multiple: float = 4.0,
    rvol_min: float = 1.2,
    impulse_body_atr_multiple: float = 0.35,
    vwap_df: pd.DataFrame | None = None,
    symbol_spec: dict | None = None,
    spread_pips: float | None = None,
    cost_aware_geometry: bool = True,
    min_stop_spread_multiple: float = 2.0,
    net_rr_after_costs: float = 1.0,
    max_stop_atr_multiple: float = 8.0,
    max_target_atr_multiple: float = 12.0,
) -> Signal:
    """Ultra-scalp S15: impulse + RVOL + VWAP, with cost-aware SL/TP geometry.

    When ``cost_aware_geometry`` is on (default), stops clear the 2× typical
    spread floor and targets clear net 1:1 after estimated commission/spread —
    without raising the 1% equity risk ceiling (wider stops shrink size).
    """
    if trend == TrendDirection.NEUTRAL or trigger_df is None or len(trigger_df) < 2:
        return _no_signal(symbol, timeframe, reason="trend_neutral")

    last = trigger_df.iloc[-1]
    prev = trigger_df.iloc[-2]
    if any(pd.isna(last.get(c)) for c in ("open", "close", "atr")):
        return _no_signal(symbol, timeframe, reason="indicators_nan")

    atr_value = float(last["atr"])
    if atr_value <= 0:
        return _no_signal(symbol, timeframe, reason="atr_zero")

    body = abs(float(last["close"]) - float(last["open"]))
    rvol = float(last.get("rvol", 1.0) or 1.0)
    if body < impulse_body_atr_multiple * atr_value:
        return _no_signal(symbol, timeframe, reason="weak_impulse")
    if rvol < rvol_min:
        return _no_signal(symbol, timeframe, reason="low_rvol")

    vwap_source = vwap_df if vwap_df is not None and not vwap_df.empty else trigger_df
    vwap = session_vwap(vwap_source)
    close = float(last["close"])
    if vwap is not None:
        if trend == TrendDirection.BULLISH and close < vwap:
            return _no_signal(symbol, timeframe, reason="vwap_misaligned")
        if trend == TrendDirection.BEARISH and close > vwap:
            return _no_signal(symbol, timeframe, reason="vwap_misaligned")

    if (
        trend == TrendDirection.BULLISH
        and last["close"] > last["open"]
        and last["close"] >= prev["close"]
    ):
        signal_type = SignalType.BUY
    elif (
        trend == TrendDirection.BEARISH
        and last["close"] < last["open"]
        and last["close"] <= prev["close"]
    ):
        signal_type = SignalType.SELL
    else:
        return _no_signal(symbol, timeframe, reason="candle_dir")

    from chronoscalp.risk.position_sizing import fit_economic_scalp_geometry

    if cost_aware_geometry:
        geometry = fit_economic_scalp_geometry(
            entry=close,
            is_buy=signal_type == SignalType.BUY,
            atr=atr_value,
            atr_stop_multiple=atr_stop_multiple,
            atr_target_multiple=atr_target_multiple,
            symbol_spec=symbol_spec,
            spread_pips=spread_pips,
            min_reward_risk_ratio=min_reward_risk_ratio,
            net_rr_floor=net_rr_after_costs,
            min_stop_spread_multiple=min_stop_spread_multiple,
            max_stop_atr_multiple=max_stop_atr_multiple,
            max_target_atr_multiple=max_target_atr_multiple,
        )
        if geometry is None:
            return _no_signal(symbol, timeframe, reason="uneconomic_costs")
        stop_loss, take_profit = geometry
    else:
        stop_dist = atr_stop_multiple * atr_value
        target_dist = atr_target_multiple * atr_value
        if signal_type == SignalType.BUY:
            stop_loss, take_profit = close - stop_dist, close + target_dist
        else:
            stop_loss, take_profit = close + stop_dist, close - target_dist

    signal = Signal(
        symbol=symbol,
        signal_type=signal_type,
        timestamp=last.name if isinstance(last.name, datetime) else datetime.utcnow(),
        entry_price=close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=predict_setup_probability(
            extract_setup_features(
                trigger_row=last,
                trend=trend,
                signal_type=signal_type,
                entry_price=close,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        ),
        reason=f"ultra_scalp_v3,trend={trend.value},rvol={rvol:.2f}",
        timeframe=timeframe,
        strategy="ultra_scalp",
    )
    if signal.risk_reward_ratio < min_reward_risk_ratio:
        return _no_signal(symbol, timeframe, reason="rr_fail")
    return signal
