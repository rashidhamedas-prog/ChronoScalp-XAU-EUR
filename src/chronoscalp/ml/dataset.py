"""Build labeled training datasets by replaying historical bars."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from chronoscalp.backtest.engine import _as_of
from chronoscalp.execution.position_logic import check_sl_tp_hit
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.logging_setup import logger
from chronoscalp.ml.features import extract_setup_features
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.strategy.multi_timeframe import (
    MultiTimeframeStrategy,
    determine_trend,
    trends_aligned,
)
from chronoscalp.utils.types import Position, SignalType, Timeframe, TrendDirection


def _label_outcome(
    trigger_df: pd.DataFrame,
    entry_idx: int,
    signal_type: SignalType,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> int | None:
    """Return 1 if TP hit before SL on subsequent bars, 0 if SL first, None if inconclusive."""
    position = Position(
        ticket=0,
        symbol="",
        direction=signal_type,
        volume=0.1,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        open_time=datetime.now(tz=UTC),
    )
    for i in range(entry_idx + 1, len(trigger_df)):
        bar = trigger_df.iloc[i]
        hit = check_sl_tp_hit(position, float(bar["high"]), float(bar["low"]))
        if hit.hit_tp:
            return 1
        if hit.hit_sl:
            return 0
    return None


def build_labeled_dataset(
    symbol: str,
    data_by_timeframe: dict[Timeframe, pd.DataFrame],
    higher_timeframes: list[Timeframe],
    trigger_timeframe: Timeframe,
    settings,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Walk trigger bars, collect features + win/loss labels for each setup."""
    trigger_df = data_by_timeframe[trigger_timeframe]
    if start is not None:
        trigger_df = trigger_df[trigger_df.index >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        trigger_df = trigger_df[trigger_df.index <= pd.Timestamp(end, tz="UTC")]

    session_filter = SessionFilter.from_config(settings.sessions)
    from chronoscalp.config import CONFIG_DIR

    news_filter = NewsFilter.from_config(
        settings.news_filter, CONFIG_DIR / "news_events.yaml", settings.secrets.news_api_key
    )
    strategy = MultiTimeframeStrategy(settings.strategy, settings.indicators)
    risk_manager = RiskManager(
        risk_cfg=settings.risk,
        spread_cfg=settings.spread_filter,
        symbols_cfg=settings.symbols_raw,
        starting_equity=float(settings.backtest.get("initial_balance", 10_000)),
    )

    ema_period = settings.indicators.get("ema_period_trend", 50)
    warmup = max(50, ema_period + 5)
    rows: list[dict[str, float | int]] = []
    open_until_idx: int | None = None

    for i in range(warmup, len(trigger_df)):
        if open_until_idx is not None and i <= open_until_idx:
            continue

        t = trigger_df.index[i]
        if not session_filter.is_within_session(t.to_pydatetime()):
            continue
        if news_filter.is_blackout(t.to_pydatetime()):
            continue

        sliced = {tf: _as_of(df, t) for tf, df in data_by_timeframe.items()}
        higher_trends = [
            determine_trend(sliced[tf], ema_col=f"ema_{ema_period}")
            for tf in higher_timeframes
            if tf in sliced
        ]
        trend = (
            trends_aligned(higher_trends)
            if settings.strategy.get("require_trend_alignment", True)
            else (higher_trends[-1] if higher_trends else TrendDirection.NEUTRAL)
        )

        signal = strategy.evaluate(
            symbol=symbol,
            data_by_timeframe=sliced,
            higher_timeframes=higher_timeframes,
            trigger_timeframe=trigger_timeframe,
            ignore_confidence_gate=True,
        )
        if signal.signal_type == SignalType.NONE:
            continue

        spread_pips = float(settings.symbols_raw.get(symbol, {}).get("typical_spread_pips", 1.0))
        if not risk_manager.validate_signal(signal, spread_pips):
            continue

        trigger_row = sliced[trigger_timeframe].iloc[-1]
        features = extract_setup_features(
            trigger_row=trigger_row,
            trend=trend,
            signal_type=signal.signal_type,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )
        label = _label_outcome(
            trigger_df,
            i,
            signal.signal_type,
            signal.entry_price,
            signal.stop_loss,
            signal.take_profit,
        )
        if label is None:
            continue

        row = {**features, "label": label}
        rows.append(row)

        for j in range(i + 1, len(trigger_df)):
            bar = trigger_df.iloc[j]
            hit = check_sl_tp_hit(
                Position(
                    ticket=0,
                    symbol=symbol,
                    direction=signal.signal_type,
                    volume=0.1,
                    entry_price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    open_time=t.to_pydatetime(),
                ),
                float(bar["high"]),
                float(bar["low"]),
            )
            if hit.triggered:
                open_until_idx = j
                break

    df = pd.DataFrame(rows)
    logger.info("Built labeled dataset for {}: {} samples", symbol, len(df))
    return df
