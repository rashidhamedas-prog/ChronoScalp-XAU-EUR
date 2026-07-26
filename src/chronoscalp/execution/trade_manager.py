"""Position management: partial TP @ 1.2R and Chandelier trailing exit."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position, SignalType


@dataclass(frozen=True)
class PartialTpAction:
    close_volume: float
    new_stop_loss: float


@dataclass(frozen=True)
class ManageAction:
    partial: PartialTpAction | None = None
    new_stop_loss: float | None = None


def initial_risk(position: Position) -> float:
    sl0 = position.initial_stop_loss if position.initial_stop_loss is not None else position.stop_loss
    return abs(position.entry_price - sl0)


def favorable_r_multiple(position: Position, current_price: float) -> float:
    risk = initial_risk(position)
    if risk <= 0:
        return 0.0
    if position.direction == SignalType.BUY:
        return (current_price - position.entry_price) / risk
    return (position.entry_price - current_price) / risk


def true_breakeven_stop(position: Position, spread_price: float) -> float:
    """Entry +/- spread buffer (commission approximated via spread pad)."""
    if position.direction == SignalType.BUY:
        return position.entry_price + max(spread_price, 0.0)
    return position.entry_price - max(spread_price, 0.0)


def partial_tp_action(
    position: Position,
    current_price: float,
    *,
    r_trigger: float = 1.2,
    close_fraction: float = 0.5,
    spread_price: float = 0.0,
) -> PartialTpAction | None:
    """At 1.2R close half and move SL to true breakeven."""
    if position.partial_taken:
        return None
    if favorable_r_multiple(position, current_price) < r_trigger:
        return None
    base_vol = position.initial_volume if position.initial_volume is not None else position.volume
    close_vol = round(base_vol * close_fraction, 8)
    if close_vol <= 0 or close_vol >= position.volume:
        close_vol = round(position.volume * close_fraction, 8)
    if close_vol <= 0:
        return None
    return PartialTpAction(
        close_volume=close_vol,
        new_stop_loss=true_breakeven_stop(position, spread_price),
    )


def chandelier_stop(
    df: pd.DataFrame,
    position: Position,
    *,
    lookback: int = 22,
    atr_multiple: float = 2.5,
) -> float | None:
    """Chandelier Exit from OHLC (+ atr column preferred)."""
    if df is None or len(df) < lookback:
        return None
    tail = df.iloc[-lookback:]
    if "atr" in df.columns and not pd.isna(df.iloc[-1].get("atr")):
        atr = float(df.iloc[-1]["atr"])
    else:
        prev_close = tail["close"].shift(1)
        tr = pd.concat(
            [
                (tail["high"] - tail["low"]).abs(),
                (tail["high"] - prev_close).abs(),
                (tail["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = float(tr.mean())
    if atr <= 0:
        return None
    if position.direction == SignalType.BUY:
        candidate = float(tail["high"].max()) - atr_multiple * atr
        if candidate > position.stop_loss:
            return candidate
    else:
        candidate = float(tail["low"].min()) + atr_multiple * atr
        if candidate < position.stop_loss:
            return candidate
    return None


def manage_open_position(
    position: Position,
    current_price: float,
    m1_df: pd.DataFrame,
    *,
    spread_price: float = 0.0,
    partial_r: float = 1.2,
    chandelier_lookback: int = 22,
    chandelier_atr_multiple: float = 2.5,
) -> ManageAction:
    """Compute partial-TP and/or Chandelier SL update for an open position."""
    partial = partial_tp_action(
        position, current_price, r_trigger=partial_r, spread_price=spread_price
    )
    if partial is not None:
        logger.info(
            "Partial TP ready ticket={} close_vol={} be_sl={:.5f}",
            position.ticket,
            partial.close_volume,
            partial.new_stop_loss,
        )
        return ManageAction(partial=partial, new_stop_loss=partial.new_stop_loss)

    if position.partial_taken or position.breakeven_moved:
        trail = chandelier_stop(
            m1_df,
            position,
            lookback=chandelier_lookback,
            atr_multiple=chandelier_atr_multiple,
        )
        if trail is not None:
            return ManageAction(new_stop_loss=trail)
    return ManageAction()
