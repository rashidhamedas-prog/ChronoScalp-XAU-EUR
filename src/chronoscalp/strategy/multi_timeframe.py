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
from chronoscalp.strategy.confluence import confluence_ok, liquidity_volume_confirms, smc_confirms
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


def ultra_scalp_trend(
    higher_trends: list[TrendDirection], mode: str = "primary"
) -> TrendDirection:
    """Trend gate for ultra-scalp.

    - ``strict``: same as ``trends_aligned`` (every TF must agree, none neutral).
    - ``primary`` (default): use the first higher TF when non-neutral; reject only
      if a later TF is explicitly opposite (neutral on M1 is allowed). Crypto
      S15 scalps rarely see M5+M1 both fully aligned on EMA50+RSI.
    """
    if not higher_trends:
        return TrendDirection.NEUTRAL
    if mode == "strict":
        return trends_aligned(higher_trends)
    primary = higher_trends[0]
    if primary == TrendDirection.NEUTRAL:
        return TrendDirection.NEUTRAL
    for t in higher_trends[1:]:
        if t != TrendDirection.NEUTRAL and t != primary:
            return TrendDirection.NEUTRAL
    return primary


def _smc_confirms(row: pd.Series, direction: TrendDirection) -> bool:
    return smc_confirms(row, direction)


def _liquidity_volume_confirms(row: pd.Series, direction: TrendDirection) -> bool:
    return liquidity_volume_confirms(row, direction)


def resolve_enabled_strategies(strategy_cfg: dict) -> tuple[bool, bool, bool]:
    """Return ``(use_smc, use_liquidity_volume, use_ultra_scalp)`` from config.

    Prefers ``enabled_strategies`` list when present; otherwise falls back to
    the boolean flags. Empty list means no confluence filter (MACD/trend only).
    """
    enabled = strategy_cfg.get("enabled_strategies")
    if isinstance(enabled, list):
        names = {str(x).strip().lower() for x in enabled}
        return (
            "smc_confluence" in names,
            "liquidity_volume" in names,
            "ultra_scalp" in names,
        )
    return (
        bool(strategy_cfg.get("use_smc_confluence", True)),
        bool(strategy_cfg.get("use_liquidity_volume", False)),
        bool(strategy_cfg.get("use_ultra_scalp", False)),
    )


def _confluence_ok(
    row: pd.Series,
    direction: TrendDirection,
    *,
    use_smc_confluence: bool,
    use_liquidity_volume: bool,
) -> tuple[bool, list[str]]:
    return confluence_ok(
        row,
        direction,
        use_smc_confluence=use_smc_confluence,
        use_liquidity_volume=use_liquidity_volume,
    )

def generate_ultra_scalp_signal(
    symbol: str,
    trigger_df: pd.DataFrame,
    trend: TrendDirection,
    timeframe: Timeframe,
    use_smc_confluence: bool = False,
    use_liquidity_volume: bool = False,
    min_reward_risk_ratio: float = 1.0,
    atr_stop_multiple: float = 1.0,
    atr_target_multiple: float = 1.0,
    rvol_min: float = 1.05,
    impulse_body_atr_multiple: float = 0.35,
) -> Signal:
    """High-frequency scalp entry on sub-minute (or M1 fallback) bars.

    Industry-style short-burst filters.
    R:R floor may be set to 1.0 via ``min_reward_risk_ratio`` for ultra-scalp
    only (global strategies remain at risk.min_reward_risk_ratio).
    - Micro-trend from higher TFs must be non-neutral
    - Impulse candle in trend direction (body ≥ ``impulse_body_atr_multiple``×ATR)
    - Relative volume ≥ ``rvol_min``
    - Optional SMC / liquidity-volume confluence (OR) — off by default for
      S15 (order-blocks on 15s bars almost never fire)
    """
    if trigger_df.empty or len(trigger_df) < 2:
        return _no_signal(symbol, timeframe, reason="no_bars")
    if trend == TrendDirection.NEUTRAL:
        return _no_signal(symbol, timeframe, reason="trend_neutral")

    last = trigger_df.iloc[-1]
    prev = trigger_df.iloc[-2]
    required = ["open", "high", "low", "close", "atr"]
    if any(pd.isna(last.get(c)) for c in required):
        return _no_signal(symbol, timeframe, reason="indicators_nan")

    atr_value = float(last["atr"])
    if atr_value <= 0:
        return _no_signal(symbol, timeframe, reason="atr_zero")

    body = abs(float(last["close"]) - float(last["open"]))
    rvol = float(last.get("rvol", 1.0) or 1.0)
    body_ok = body >= impulse_body_atr_multiple * atr_value
    rvol_ok = rvol >= rvol_min
    if not body_ok:
        return _no_signal(symbol, timeframe, reason="weak_impulse")
    if not rvol_ok:
        return _no_signal(symbol, timeframe, reason="low_rvol")

    signal_type = SignalType.NONE
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

    ok, tags = _confluence_ok(
        last,
        trend,
        use_smc_confluence=use_smc_confluence,
        use_liquidity_volume=use_liquidity_volume,
    )
    if not ok:
        return _no_signal(symbol, timeframe, reason="no_confluence")

    entry_price = float(last["close"])
    if signal_type == SignalType.BUY:
        stop_loss = entry_price - atr_stop_multiple * atr_value
        take_profit = entry_price + atr_target_multiple * atr_value
    else:
        stop_loss = entry_price + atr_stop_multiple * atr_value
        take_profit = entry_price - atr_target_multiple * atr_value

    reason_parts = [
        "ultra_scalp",
        f"trend={trend.value}",
        f"rvol={rvol:.2f}",
        *tags,
    ]
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
        return _no_signal(symbol, timeframe, reason="rr_fail")
    return signal


def generate_entry_signal(
    symbol: str,
    trigger_df: pd.DataFrame,
    trend: TrendDirection,
    timeframe: Timeframe,
    use_smc_confluence: bool = True,
    use_liquidity_volume: bool = False,
    min_reward_risk_ratio: float = 1.5,
    atr_stop_multiple: float = 1.5,
    atr_target_multiple: float = 2.5,
) -> Signal:
    """Entry trigger on the lower timeframe: MACD crossover in the direction
    of `trend`, confirmed by Bollinger Band mean-reversion-into-trend and
    (optionally) one or more strategy modes (OR). Stop-loss / take-profit
    are ATR-based.
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
        ok, tags = _confluence_ok(
            last,
            trend,
            use_smc_confluence=use_smc_confluence,
            use_liquidity_volume=use_liquidity_volume,
        )
        if not ok:
            return _no_signal(symbol, timeframe)
        signal_type = SignalType.BUY
        reason_parts = ["trend=bullish", "macd_cross_up", *tags]
    elif trend == TrendDirection.BEARISH and macd_cross_down and last["close"] >= last["bb_lower"]:
        ok, tags = _confluence_ok(
            last,
            trend,
            use_smc_confluence=use_smc_confluence,
            use_liquidity_volume=use_liquidity_volume,
        )
        if not ok:
            return _no_signal(symbol, timeframe)
        signal_type = SignalType.SELL
        reason_parts = ["trend=bearish", "macd_cross_down", *tags]
    else:
        return _no_signal(symbol, timeframe)

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
        use_smc, use_liq, use_scalp = resolve_enabled_strategies(self.strategy_cfg)
        scalp_cfg = self.strategy_cfg.get("ultra_scalp") or {}
        trend_engine = str(self.strategy_cfg.get("trend_engine", "session_vwap"))

        higher_frames = [
            data_by_timeframe[tf] for tf in higher_timeframes if tf in data_by_timeframe
        ]
        if trend_engine == "session_vwap":
            from chronoscalp.strategy.trend_filter import (
                aligned_institutional_bias,
                institutional_bias,
            )

            if use_scalp and str(scalp_cfg.get("trend_mode", "strict")) == "primary":
                # Primary = first higher TF (usually M15); reject if later TF opposes.
                if not higher_frames:
                    trend = TrendDirection.NEUTRAL
                else:
                    primary = institutional_bias(higher_frames[0])
                    trend = primary
                    if primary != TrendDirection.NEUTRAL:
                        for frame in higher_frames[1:]:
                            other = institutional_bias(frame)
                            if other != TrendDirection.NEUTRAL and other != primary:
                                trend = TrendDirection.NEUTRAL
                                break
            else:
                trend = aligned_institutional_bias(higher_frames)
        else:
            ema_period = self.indicators_cfg.get("ema_period_trend", 50)
            higher_trends = [
                determine_trend(data_by_timeframe[tf], ema_col=f"ema_{ema_period}")
                for tf in higher_timeframes
                if tf in data_by_timeframe
            ]
            if use_scalp:
                trend = ultra_scalp_trend(
                    higher_trends, mode=str(scalp_cfg.get("trend_mode", "primary"))
                )
            elif self.strategy_cfg.get("require_trend_alignment", True):
                trend = trends_aligned(higher_trends)
            else:
                trend = higher_trends[-1] if higher_trends else TrendDirection.NEUTRAL

        trigger_df = data_by_timeframe.get(trigger_timeframe)
        if trigger_df is None:
            return _no_signal(symbol, trigger_timeframe, reason="no_trigger_data")

        entry_engine = str(self.strategy_cfg.get("entry_engine", "institutional"))
        if use_scalp:
            from chronoscalp.strategy.entry_trigger import generate_ultra_scalp_v3

            signal = generate_ultra_scalp_v3(
                symbol=symbol,
                trigger_df=trigger_df,
                trend=trend,
                timeframe=trigger_timeframe,
                min_reward_risk_ratio=float(scalp_cfg.get("min_reward_risk_ratio", 1.0)),
                atr_stop_multiple=float(scalp_cfg.get("atr_stop_multiple", 1.0)),
                atr_target_multiple=float(scalp_cfg.get("atr_target_multiple", 1.0)),
                rvol_min=float(scalp_cfg.get("rvol_min", 1.3)),
                impulse_body_atr_multiple=float(
                    scalp_cfg.get("impulse_body_atr_multiple", 0.4)
                ),
                vwap_df=trigger_df,
            )
        elif entry_engine == "institutional":
            from chronoscalp.strategy.entry_trigger import generate_institutional_entry

            signal = generate_institutional_entry(
                symbol=symbol,
                trigger_df=trigger_df,
                trend=trend,
                timeframe=trigger_timeframe,
                use_smc_confluence=use_smc,
                use_liquidity_volume=use_liq,
                min_reward_risk_ratio=float(
                    self.strategy_cfg.get("min_reward_risk_ratio", 1.5)
                ),
                atr_stop_multiple=float(self.strategy_cfg.get("atr_stop_multiple", 1.5)),
                atr_target_multiple=float(self.strategy_cfg.get("atr_target_multiple", 2.25)),
                rvol_min=float(self.strategy_cfg.get("entry_rvol_min", 1.5)),
            )
        else:
            signal = generate_entry_signal(
                symbol=symbol,
                trigger_df=trigger_df,
                trend=trend,
                timeframe=trigger_timeframe,
                use_smc_confluence=use_smc,
                use_liquidity_volume=use_liq,
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
            return _no_signal(symbol, trigger_timeframe, reason="low_confidence")

        return signal
