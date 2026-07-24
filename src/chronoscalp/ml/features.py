"""Feature extraction at signal time for setup-probability scoring."""

from __future__ import annotations

import pandas as pd

from chronoscalp.utils.types import Signal, SignalType, TrendDirection

FEATURE_COLUMNS: list[str] = [
    "rsi",
    "macd",
    "macd_histogram",
    "atr_norm",
    "bb_position",
    "trend_bullish",
    "trend_bearish",
    "is_buy",
    "smc_bullish_ob",
    "smc_bearish_ob",
    "smc_fvg_bullish",
    "smc_fvg_bearish",
    "smc_sweep_low",
    "smc_sweep_high",
    "smc_sweep_low_vol",
    "smc_sweep_high_vol",
    "rvol",
    "risk_reward_ratio",
]


def _bb_position(row: pd.Series) -> float:
    upper = float(row.get("bb_upper", row["close"]))
    lower = float(row.get("bb_lower", row["close"]))
    width = upper - lower
    if width <= 0:
        return 0.5
    return float((row["close"] - lower) / width)


def extract_setup_features(
    trigger_row: pd.Series,
    trend: TrendDirection,
    signal_type: SignalType,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> dict[str, float]:
    """Build a numeric feature dict from the trigger bar at signal time."""
    close = float(trigger_row["close"])
    atr_value = float(trigger_row.get("atr", 0.0) or 0.0)
    atr_norm = atr_value / close if close > 0 else 0.0

    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    rr = reward / risk if risk > 0 else 0.0

    return {
        "rsi": float(trigger_row.get("rsi", 50.0)),
        "macd": float(trigger_row.get("macd", 0.0)),
        "macd_histogram": float(trigger_row.get("histogram", 0.0)),
        "atr_norm": atr_norm,
        "bb_position": _bb_position(trigger_row),
        "trend_bullish": 1.0 if trend == TrendDirection.BULLISH else 0.0,
        "trend_bearish": 1.0 if trend == TrendDirection.BEARISH else 0.0,
        "is_buy": 1.0 if signal_type == SignalType.BUY else 0.0,
        "smc_bullish_ob": 1.0 if bool(trigger_row.get("bullish_ob")) else 0.0,
        "smc_bearish_ob": 1.0 if bool(trigger_row.get("bearish_ob")) else 0.0,
        "smc_fvg_bullish": 1.0 if bool(trigger_row.get("fvg_bullish")) else 0.0,
        "smc_fvg_bearish": 1.0 if bool(trigger_row.get("fvg_bearish")) else 0.0,
        "smc_sweep_low": 1.0 if bool(trigger_row.get("liquidity_sweep_low")) else 0.0,
        "smc_sweep_high": 1.0 if bool(trigger_row.get("liquidity_sweep_high")) else 0.0,
        "smc_sweep_low_vol": 1.0 if bool(trigger_row.get("liquidity_sweep_low_vol")) else 0.0,
        "smc_sweep_high_vol": 1.0 if bool(trigger_row.get("liquidity_sweep_high_vol")) else 0.0,
        "rvol": float(trigger_row.get("rvol", 1.0) or 1.0),
        "risk_reward_ratio": rr,
    }


def features_from_signal(
    signal: Signal, trigger_row: pd.Series, trend: TrendDirection
) -> dict[str, float]:
    """Convenience wrapper using an actionable ``Signal``."""
    return extract_setup_features(
        trigger_row=trigger_row,
        trend=trend,
        signal_type=signal.signal_type,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )


def features_to_vector(features: dict[str, float]) -> list[float]:
    return [float(features.get(col, 0.0)) for col in FEATURE_COLUMNS]
