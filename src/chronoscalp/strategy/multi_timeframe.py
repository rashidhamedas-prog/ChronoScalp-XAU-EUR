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

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from chronoscalp.logging_setup import logger
from chronoscalp.ml.features import extract_setup_features
from chronoscalp.ml.scorer import is_configured, predict_setup_probability
from chronoscalp.strategy.confluence import confluence_ok, liquidity_volume_confirms, smc_confirms
from chronoscalp.strategy.symbol_catalog import (
    derive_from_symbols_enabled,
    merge_symbol_overrides,
    strategies_for_symbol,
    strategies_for_symbols,
)
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


def ultra_scalp_trend(higher_trends: list[TrendDirection], mode: str = "primary") -> TrendDirection:
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


@dataclass(frozen=True)
class EnabledStrategies:
    """Resolved strategy switches. Selection is simultaneous OR, not pick-best."""

    smc: bool = False
    liquidity: bool = False
    ultra_scalp: bool = False
    news_straddle: bool = False
    delta: bool = False
    xau_vwap_pullback: bool = False

    def names(self) -> list[str]:
        out: list[str] = []
        if self.smc:
            out.append("smc_confluence")
        if self.liquidity:
            out.append("liquidity_volume")
        if self.ultra_scalp:
            out.append("ultra_scalp")
        if self.news_straddle:
            out.append("news_straddle")
        if self.delta:
            out.append("delta")
        if self.xau_vwap_pullback:
            out.append("xau_vwap_pullback")
        return out

    @classmethod
    def from_names(cls, names: list[str] | set[str]) -> EnabledStrategies:
        keys = {str(n).strip().lower() for n in names}
        return cls(
            smc="smc_confluence" in keys,
            liquidity="liquidity_volume" in keys,
            ultra_scalp="ultra_scalp" in keys,
            news_straddle="news_straddle" in keys,
            delta="delta" in keys,
            xau_vwap_pullback="xau_vwap_pullback" in keys,
        )


def resolve_enabled_strategies(
    strategy_cfg: dict,
    *,
    symbol: str | None = None,
    symbols: list[str] | tuple[str, ...] | None = None,
) -> EnabledStrategies:
    """Resolve enabled strategies from the symbol catalog, list, or flags.

    When ``derive_strategies_from_symbols`` is on (the default), a ``symbol``
    argument returns that market's book and ``symbols`` returns the union.
    Research tests that pass only ``enabled_strategies`` still work — they
    omit ``symbol`` / ``symbols``.
    """
    if derive_from_symbols_enabled(strategy_cfg):
        if symbol is not None:
            return EnabledStrategies.from_names(strategies_for_symbol(strategy_cfg, symbol))
        if symbols is not None:
            return EnabledStrategies.from_names(strategies_for_symbols(strategy_cfg, symbols))
    enabled = strategy_cfg.get("enabled_strategies")
    if isinstance(enabled, list):
        return EnabledStrategies.from_names([str(x).strip().lower() for x in enabled])
    return EnabledStrategies(
        smc=bool(strategy_cfg.get("use_smc_confluence", True)),
        liquidity=bool(strategy_cfg.get("use_liquidity_volume", False)),
        ultra_scalp=bool(strategy_cfg.get("use_ultra_scalp", False)),
        news_straddle=bool(strategy_cfg.get("use_news_straddle", False)),
        delta=bool(strategy_cfg.get("use_delta", False)),
        xau_vwap_pullback=bool(strategy_cfg.get("use_xau_vwap_pullback", False)),
    )


def is_shadow_only(strategy_cfg: dict, strategy_id: str) -> bool:
    """True when this strategy must record candidates but never place live/paper orders."""
    block = strategy_cfg.get(strategy_id) or {}
    return isinstance(block, dict) and block.get("shadow_only") is True


def _canonical_symbol_root(symbol: str) -> str:
    """``EURUSD_o`` / ``EURUSD`` → ``EURUSD`` for allow/deny matching."""
    return str(symbol or "").strip().upper().split("_", 1)[0]


def ultra_scalp_allowed_for_symbol(symbol: str, scalp_cfg: dict) -> bool:
    """Gate ultra-scalp by optional allow/deny lists (live demo FX bleed fix).

    Rules (first match wins conceptually):
    - If ``allowed_symbols`` is a list (including empty), only those roots trade.
    - Else if ``disabled_symbols`` is a list, those roots are blocked.
    - Else all symbols are allowed (legacy).
    """
    root = _canonical_symbol_root(symbol)
    if not root:
        return False
    allowed = scalp_cfg.get("allowed_symbols")
    if isinstance(allowed, list):
        allowed_roots = {_canonical_symbol_root(s) for s in allowed if str(s).strip()}
        return root in allowed_roots
    disabled = scalp_cfg.get("disabled_symbols")
    if isinstance(disabled, list):
        disabled_roots = {_canonical_symbol_root(s) for s in disabled if str(s).strip()}
        return root not in disabled_roots
    return True


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


def pick_best_signal(signals: list[Signal]) -> Signal | None:
    """Choose the strongest actionable signal among parallel strategy outputs.

    Ranking: higher gross R:R, then higher confidence. Strategies on different
    timeframes are evaluated independently; this only breaks ties when more
    than one fires on the same poll tick (one position per symbol).
    """
    actionable = [s for s in signals if s is not None and s.is_actionable]
    if not actionable:
        return None
    return max(
        actionable,
        key=lambda s: (float(s.risk_reward_ratio), float(s.confidence)),
    )


class MultiTimeframeStrategy:
    """Orchestrates trend detection + entry generation for a single symbol
    given already-fetched, indicator/SMC-enriched DataFrames per timeframe."""

    def __init__(
        self,
        strategy_cfg: dict,
        indicators_cfg: dict,
        symbols_cfg: dict | None = None,
    ) -> None:
        self.strategy_cfg = strategy_cfg
        self.indicators_cfg = indicators_cfg
        self.symbols_cfg = symbols_cfg or {}
        from chronoscalp.strategy.xau_vwap_pullback import XauVwapPullbackEngine

        self.xau_vwap_engine = XauVwapPullbackEngine(
            cfg=dict(strategy_cfg.get("xau_vwap_pullback") or {}),
            symbols_cfg=self.symbols_cfg,
        )

    def evaluate(
        self,
        symbol: str,
        data_by_timeframe: dict[Timeframe, pd.DataFrame],
        higher_timeframes: list[Timeframe],
        trigger_timeframe: Timeframe,
        *,
        ignore_confidence_gate: bool = False,
        spread_pips: float | None = None,
        median_spread_pips: float | None = None,
        broker_spread_cap_pips: float | None = None,
        run_scalp: bool = True,
        run_institutional: bool = True,
    ) -> Signal:
        """Compatibility wrapper: one Signal when a single engine fires.

        Production paths must use :meth:`evaluate_candidates`. Multiple
        candidates are not collapsed with pick-best.
        """
        candidates, skip_reasons = self._collect_candidates(
            symbol,
            data_by_timeframe,
            higher_timeframes,
            trigger_timeframe,
            ignore_confidence_gate=ignore_confidence_gate,
            spread_pips=spread_pips,
            median_spread_pips=median_spread_pips,
            broker_spread_cap_pips=broker_spread_cap_pips,
            run_scalp=run_scalp,
            run_institutional=run_institutional,
        )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.info(
                "{} {} independent candidates (not pick-best): {}",
                symbol,
                len(candidates),
                ",".join((s.strategy or s.reason.split(",")[0]) for s in candidates),
            )
            return candidates[0]
        reason = "|".join(skip_reasons) if skip_reasons else "no_signal"
        return _no_signal(symbol, trigger_timeframe, reason=reason)

    def evaluate_candidates(
        self,
        symbol: str,
        data_by_timeframe: dict[Timeframe, pd.DataFrame],
        higher_timeframes: list[Timeframe],
        trigger_timeframe: Timeframe,
        *,
        ignore_confidence_gate: bool = False,
        spread_pips: float | None = None,
        median_spread_pips: float | None = None,
        broker_spread_cap_pips: float | None = None,
        skip_out: list[str] | None = None,
        run_scalp: bool = True,
        run_institutional: bool = True,
    ) -> list[Signal]:
        """Return every actionable candidate. Never winner-takes-all.

        When ``skip_out`` is provided, engine reject reasons are appended so
        the live skip heartbeat can show ``delta:low_rvol`` instead of a
        blank ``no_signal``.
        """
        candidates, skip = self._collect_candidates(
            symbol,
            data_by_timeframe,
            higher_timeframes,
            trigger_timeframe,
            ignore_confidence_gate=ignore_confidence_gate,
            spread_pips=spread_pips,
            median_spread_pips=median_spread_pips,
            broker_spread_cap_pips=broker_spread_cap_pips,
            run_scalp=run_scalp,
            run_institutional=run_institutional,
        )
        if skip_out is not None:
            skip_out.extend(skip)
        return candidates

    def _collect_candidates(
        self,
        symbol: str,
        data_by_timeframe: dict[Timeframe, pd.DataFrame],
        higher_timeframes: list[Timeframe],
        trigger_timeframe: Timeframe,
        *,
        ignore_confidence_gate: bool = False,
        spread_pips: float | None = None,
        median_spread_pips: float | None = None,
        broker_spread_cap_pips: float | None = None,
        run_scalp: bool = True,
        run_institutional: bool = True,
    ) -> tuple[list[Signal], list[str]]:
        enabled = resolve_enabled_strategies(self.strategy_cfg, symbol=symbol)
        use_smc = enabled.smc
        use_liq = enabled.liquidity
        use_scalp = enabled.ultra_scalp
        use_delta = enabled.delta
        use_xau = enabled.xau_vwap_pullback
        scalp_cfg = merge_symbol_overrides(self.strategy_cfg.get("ultra_scalp") or {}, symbol)
        inst_cfg = merge_symbol_overrides(self.strategy_cfg, symbol)
        trend_engine = str(self.strategy_cfg.get("trend_engine", "session_vwap"))
        entry_engine = str(self.strategy_cfg.get("entry_engine", "institutional"))
        symbol_allows_scalp = ultra_scalp_allowed_for_symbol(symbol, scalp_cfg)
        want_scalp = bool(use_scalp and run_scalp and symbol_allows_scalp)
        # Institutional / SMC / liquidity when those modes are on — or the
        # legacy MACD path when nothing (including Delta) is selected.
        # Delta-only must not also fire the institutional engine.
        want_institutional = bool(run_institutional) and (
            use_smc or use_liq or (not use_scalp and not use_delta and not use_xau)
        )
        want_delta = bool(run_institutional and use_delta)
        want_xau = bool(run_institutional and use_xau)

        higher_frames = [
            data_by_timeframe[tf] for tf in higher_timeframes if tf in data_by_timeframe
        ]

        def _trend(*, for_scalp: bool) -> TrendDirection:
            if trend_engine == "session_vwap":
                from chronoscalp.strategy.trend_filter import (
                    aligned_institutional_bias,
                    institutional_bias,
                )

                if for_scalp and str(scalp_cfg.get("trend_mode", "strict")) == "primary":
                    if not higher_frames:
                        return TrendDirection.NEUTRAL
                    primary = institutional_bias(higher_frames[0])
                    if primary == TrendDirection.NEUTRAL:
                        return TrendDirection.NEUTRAL
                    for frame in higher_frames[1:]:
                        other = institutional_bias(frame)
                        if other != TrendDirection.NEUTRAL and other != primary:
                            return TrendDirection.NEUTRAL
                    return primary
                return aligned_institutional_bias(higher_frames)

            ema_period = self.indicators_cfg.get("ema_period_trend", 50)
            higher_trends = [
                determine_trend(data_by_timeframe[tf], ema_col=f"ema_{ema_period}")
                for tf in higher_timeframes
                if tf in data_by_timeframe
            ]
            if for_scalp and use_scalp:
                return ultra_scalp_trend(
                    higher_trends, mode=str(scalp_cfg.get("trend_mode", "primary"))
                )
            if self.strategy_cfg.get("require_trend_alignment", True):
                return trends_aligned(higher_trends)
            return higher_trends[-1] if higher_trends else TrendDirection.NEUTRAL

        def _apply_confidence(signal: Signal) -> Signal:
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
                return _no_signal(symbol, signal.timeframe, reason="low_confidence")
            return signal

        skip_reasons: list[str] = []
        candidates: list[Signal] = []

        if use_scalp and run_scalp and not symbol_allows_scalp:
            skip_reasons.append("scalp:symbol_blocked")

        if want_scalp:
            scalp_tf = trigger_timeframe
            scalp_df = data_by_timeframe.get(scalp_tf)
            if scalp_df is None:
                skip_reasons.append("scalp:no_trigger_data")
            else:
                from chronoscalp.strategy.entry_trigger import generate_ultra_scalp_v3

                scalp_signal = generate_ultra_scalp_v3(
                    symbol=symbol,
                    trigger_df=scalp_df,
                    trend=_trend(for_scalp=True),
                    timeframe=scalp_tf,
                    min_reward_risk_ratio=max(
                        1.5, float(scalp_cfg.get("min_reward_risk_ratio", 1.5))
                    ),
                    atr_stop_multiple=float(scalp_cfg.get("atr_stop_multiple", 2.5)),
                    atr_target_multiple=float(scalp_cfg.get("atr_target_multiple", 4.0)),
                    rvol_min=float(scalp_cfg.get("rvol_min", 1.2)),
                    impulse_body_atr_multiple=float(
                        scalp_cfg.get("impulse_body_atr_multiple", 0.35)
                    ),
                    vwap_df=scalp_df,
                    symbol_spec=self.symbols_cfg.get(symbol),
                    spread_pips=spread_pips,
                    cost_aware_geometry=bool(scalp_cfg.get("cost_aware_geometry", True)),
                    min_stop_spread_multiple=float(scalp_cfg.get("min_stop_spread_multiple", 2.0)),
                    net_rr_after_costs=max(1.25, float(scalp_cfg.get("net_rr_after_costs", 1.25))),
                    max_stop_atr_multiple=float(scalp_cfg.get("max_stop_atr_multiple", 8.0)),
                    max_target_atr_multiple=float(scalp_cfg.get("max_target_atr_multiple", 12.0)),
                )
                scalp_signal = _apply_confidence(scalp_signal)
                if scalp_signal.is_actionable:
                    candidates.append(scalp_signal)
                else:
                    skip_reasons.append(f"scalp:{scalp_signal.reason or 'no_signal'}")

        if want_institutional:
            inst_tf = Timeframe.M1 if Timeframe.M1 in data_by_timeframe else trigger_timeframe
            inst_df = data_by_timeframe.get(inst_tf)
            if inst_df is None:
                skip_reasons.append("inst:no_trigger_data")
            else:
                inst_trend = _trend(for_scalp=False)
                from chronoscalp.strategy.entry_trigger import generate_institutional_entry
                from chronoscalp.utils.strategy_tags import (
                    STRATEGY_LIQUIDITY,
                    STRATEGY_SMC,
                )

                inst_passes: list[tuple[str, bool, bool]] = []
                if use_smc:
                    inst_passes.append((STRATEGY_SMC, True, False))
                if use_liq:
                    inst_passes.append((STRATEGY_LIQUIDITY, False, True))
                if not inst_passes and (not use_scalp and not use_delta and not use_xau):
                    inst_passes.append(("institutional", False, False))

                for strategy_id, smc_flag, liq_flag in inst_passes:
                    if entry_engine == "institutional" and (smc_flag or liq_flag or not use_scalp):
                        inst_signal = generate_institutional_entry(
                            symbol=symbol,
                            trigger_df=inst_df,
                            trend=inst_trend,
                            timeframe=inst_tf,
                            use_smc_confluence=smc_flag,
                            use_liquidity_volume=liq_flag,
                            min_reward_risk_ratio=float(inst_cfg.get("min_reward_risk_ratio", 1.5)),
                            atr_stop_multiple=float(inst_cfg.get("atr_stop_multiple", 1.5)),
                            atr_target_multiple=float(inst_cfg.get("atr_target_multiple", 2.25)),
                            rvol_min=float(inst_cfg.get("entry_rvol_min", 1.5)),
                            strategy_id=strategy_id,
                        )
                    else:
                        inst_signal = generate_entry_signal(
                            symbol=symbol,
                            trigger_df=inst_df,
                            trend=inst_trend,
                            timeframe=inst_tf,
                            use_smc_confluence=smc_flag,
                            use_liquidity_volume=liq_flag,
                        )
                    inst_signal = _apply_confidence(inst_signal)
                    if inst_signal.is_actionable:
                        candidates.append(inst_signal)
                    else:
                        skip_reasons.append(f"{strategy_id}:{inst_signal.reason or 'no_signal'}")

        if want_delta:
            delta_tf = Timeframe.M1 if Timeframe.M1 in data_by_timeframe else trigger_timeframe
            delta_df = data_by_timeframe.get(delta_tf)
            if delta_df is None:
                skip_reasons.append("delta:no_trigger_data")
            else:
                from chronoscalp.strategy.delta import generate_delta_signal

                delta_signal = generate_delta_signal(
                    symbol,
                    delta_df,
                    higher_frames,
                    config=dict(self.strategy_cfg.get("delta") or {}),
                    symbol_spec=self.symbols_cfg.get(symbol),
                    spread_pips=spread_pips,
                    ema_period=int(self.indicators_cfg.get("ema_period_trend", 50)),
                )
                delta_signal = _apply_confidence(delta_signal)
                if delta_signal.is_actionable:
                    candidates.append(delta_signal)
                else:
                    skip_reasons.append(delta_signal.reason or "delta:no_signal")

        if want_xau:
            xau_tf = Timeframe.M1 if Timeframe.M1 in data_by_timeframe else trigger_timeframe
            xau_df = data_by_timeframe.get(xau_tf)
            if xau_df is None:
                skip_reasons.append("xau_vwap_pullback:no_trigger_data")
            else:
                from chronoscalp.strategy.xau_vwap_pullback import (
                    generate_xau_vwap_pullback_signal,
                )

                xau_cfg = dict(self.strategy_cfg.get("xau_vwap_pullback") or {})
                xau_cfg.setdefault("enabled", True)
                xau_signal = generate_xau_vwap_pullback_signal(
                    symbol,
                    xau_df,
                    higher_frames,
                    engine=self.xau_vwap_engine,
                    config=xau_cfg,
                    symbol_spec=self.symbols_cfg.get(symbol),
                    spread_pips=spread_pips,
                    median_spread_pips=median_spread_pips,
                    broker_spread_cap_pips=broker_spread_cap_pips,
                )
                xau_signal = _apply_confidence(xau_signal)
                if xau_signal.is_actionable:
                    candidates.append(xau_signal)
                else:
                    skip_reasons.append(xau_signal.reason or "xau_vwap_pullback:no_signal")

        return candidates, skip_reasons
