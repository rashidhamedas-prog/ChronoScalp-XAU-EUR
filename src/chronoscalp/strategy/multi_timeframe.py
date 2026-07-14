"""Multi-timeframe trend alignment + entry signal generation.

Pipeline (see docs/ARCHITECTURE.md):
  M10 + M5 → TrendDirection (must agree)   →   M3 + M1 → entry trigger → Signal

Pure functions over already-indicator-enriched DataFrames (see
indicators/technical.py::enrich_with_indicators and
smc/structure.py::enrich_with_smc) — no I/O, no broker calls, so this is
fully unit-testable and reusable from both main.py (live) and
backtest/engine.py (historical).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from chronoscalp.logging_setup import logger
from chronoscalp.ml.features import extract_setup_features
from chronoscalp.ml.scorer import is_configured, predict_setup_probability
from chronoscalp.utils.types import Signal, SignalType, Timeframe, TrendDirection


def determine_trend(
    df: pd.DataFrame, ema_col: str = "ema_50", rsi_overbought: float = 70, rsi_oversold: float = 30
) -> TrendDirection:
    """Trend from the latest bar of an indicator-enriched higher-timeframe
    DataFrame: price vs EMA slope + RSI regime."""
    if df.empty or len(df) < 2:
        return TrendDirection.NEUTRAL

    last = df.iloc[-1]
    prev = df.iloc[-2]

    if pd.isna(last.get(ema_col)) or pd.isna(prev.get(ema_col)):
        return TrendDirection.NEUTRAL

    ema_rising = last[ema_col] > prev[ema_col]
    price_above_ema = last["close"] > last[ema_col]
    rsi_value = last.get("rsi", 50.0)

    if price_above_ema and ema_rising and rsi_value > 50:
        return TrendDirection.BULLISH
    if not price_above_ema and not ema_rising and rsi_value < 50:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL


def trends_aligned(higher_trends: list[TrendDirection]) -> TrendDirection:
    """Require every higher-timeframe trend to agree; otherwise NEUTRAL
    (no trade permitted). See config/settings.yaml strategy.require_trend_alignment."""
    unique = set(higher_trends)
    if len(unique) == 1 and TrendDirection.NEUTRAL not in unique:
        return unique.pop()
    return TrendDirection.NEUTRAL


def _smc_confirms(row: pd.Series, direction: TrendDirection) -> bool:
    """Require SMC confluence: an order block, FVG, or liquidity sweep in the
    signal's direction on the trigger timeframe. Only checked when
    strategy.use_smc_confluence is true in config."""
    if direction == TrendDirection.BULLISH:
        return bool(
            row.get("bullish_ob") or row.get("fvg_bullish") or row.get("liquidity_sweep_low")
        )
    if direction == TrendDirection.BEARISH:
        return bool(
            row.get("bearish_ob") or row.get("fvg_bearish") or row.get("liquidity_sweep_high")
        )
    return False


def generate_entry_signal(
    symbol: str,
    trigger_df: pd.DataFrame,
    trend: TrendDirection,
    timeframe: Timeframe,
    use_smc_confluence: bool = True,
    min_reward_risk_ratio: float = 1.5,
    atr_stop_multiple: float = 1.5,
    atr_target_multiple: float = 2.5,
) -> Signal:
    """Entry trigger on the lower timeframe: MACD crossover in the direction
    of `trend`, confirmed by Bollinger Band mean-reversion-into-trend and
    (optionally) SMC confluence. Stop-loss/take-profit are ATR-based.
    """
    if trend == TrendDirection.NEUTRAL or trigger_df.empty or len(trigger_df) < 2:
        return _no_signal(symbol, timeframe)

    last = trigger_df.iloc[-1]
    prev = trigger_df.iloc[-2]

    required_cols = ["macd", "signal", "bb_lower", "bb_upper", "atr", "close"]
    if any(pd.isna(last.get(c)) for c in required_cols):
        return _no_signal(symbol, timeframe)

    macd_cross_up = prev["macd"] <= prev["signal"] and last["macd"] > last["signal"]
    macd_cross_down = prev["macd"] >= prev["signal"] and last["macd"] < last["signal"]

    signal_type = SignalType.NONE
    reason_parts: list[str] = []

    if trend == TrendDirection.BULLISH and macd_cross_up and last["close"] <= last["bb_upper"]:
        if use_smc_confluence and not _smc_confirms(last, trend):
            return _no_signal(symbol, timeframe)
        signal_type = SignalType.BUY
        reason_parts = ["trend=bullish", "macd_cross_up"]
    elif trend == TrendDirection.BEARISH and macd_cross_down and last["close"] >= last["bb_lower"]:
        if use_smc_confluence and not _smc_confirms(last, trend):
            return _no_signal(symbol, timeframe)
        signal_type = SignalType.SELL
        reason_parts = ["trend=bearish", "macd_cross_down"]
    else:
        return _no_signal(symbol, timeframe)

    if use_smc_confluence:
        reason_parts.append("smc_confirmed")

    entry_price = float(last["close"])
    atr_value = float(last["atr"])
    if signal_type == SignalType.BUY:
        stop_loss = entry_price - atr_stop_multiple * atr_value
        take_profit = entry_price + atr_target_multiple * atr_value
    else:
        stop_loss = entry_price + atr_stop_multiple * atr_value
        take_profit = entry_price - atr_target_multiple * atr_value

    signal = Signal(
        symbol=symbol,
        signal_type=signal_type,
        timestamp=last.name if isinstance(last.name, datetime) else datetime.utcnow(),
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=score_setup_probability(
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
    )

    if signal.risk_reward_ratio < min_reward_risk_ratio:
        logger.debug(
            "{} signal discarded: R:R {:.2f} below minimum {:.2f}",
            symbol,
            signal.risk_reward_ratio,
            min_reward_risk_ratio,
        )
        return _no_signal(symbol, timeframe)

    return signal


def score_setup_probability(features: dict) -> float:
    """Return P(setup wins) from the loaded ML model, or 0.5 if none configured."""
    return predict_setup_probability(features)


def _no_signal(symbol: str, timeframe: Timeframe) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=SignalType.NONE,
        timestamp=datetime.utcnow(),
        entry_price=0.0,
        stop_loss=0.0,
        take_profit=0.0,
        timeframe=timeframe,
    )


class MultiTimeframeStrategy:
    """Orchestrates trend detection + entry generation for a single symbol
    given already-fetched, indicator/SMC-enriched DataFrames per timeframe."""

    def __init__(self, strategy_cfg: dict, indicators_cfg: dict) -> None:
        self.strategy_cfg = strategy_cfg
        self.indicators_cfg = indicators_cfg

    def evaluate(
        self,
        symbol: str,
        data_by_timeframe: dict[Timeframe, pd.DataFrame],
        higher_timeframes: list[Timeframe],
        trigger_timeframe: Timeframe,
        *,
        ignore_confidence_gate: bool = False,
    ) -> Signal:
        ema_period = self.indicators_cfg.get("ema_period_trend", 50)
        higher_trends = [
            determine_trend(data_by_timeframe[tf], ema_col=f"ema_{ema_period}")
            for tf in higher_timeframes
            if tf in data_by_timeframe
        ]

        if self.strategy_cfg.get("require_trend_alignment", True):
            trend = trends_aligned(higher_trends)
        else:
            trend = higher_trends[-1] if higher_trends else TrendDirection.NEUTRAL

        trigger_df = data_by_timeframe.get(trigger_timeframe)
        if trigger_df is None:
            return _no_signal(symbol, trigger_timeframe)

        signal = generate_entry_signal(
            symbol=symbol,
            trigger_df=trigger_df,
            trend=trend,
            timeframe=trigger_timeframe,
            use_smc_confluence=self.strategy_cfg.get("use_smc_confluence", True),
        )

        min_conf = float(self.strategy_cfg.get("min_signal_confidence", 0.0))
        if (
            not ignore_confidence_gate
            and is_configured()
            and signal.is_actionable
            and min_conf > 0
            and signal.confidence < min_conf
        ):
            logger.debug(
                "{} signal rejected: confidence {:.2f} < min {:.2f}",
                symbol,
                signal.confidence,
                min_conf,
            )
            return _no_signal(symbol, trigger_timeframe)

        return signal
