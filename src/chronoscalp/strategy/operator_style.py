"""Standalone operator-style engine: ADX trend strength + Stochastic timing.

Measured on AUSCommercial-Demo magic=0 fills, 14d to 2026-09-03:

* Gold: 7 bursts, 6 winners, +$57k. Every burst sat in Iran 13:00–18:00
  with M15 ADX ≥ 22. The large SELL baskets faded RSI/Stoch spikes
  (RSI 69–78, Stoch 80+) on a strong ADX tape; the BUY baskets were M5
  pullbacks (Stoch 21–33) while H1/M15 stayed above the fast EMA.
* One gold SELL was a rollover: M15 still stretched, M5 already dumped.
* EUR: 0.01 grids plus occasional 5-lot hedges. The directional subset
  sold M5 overbought prints (Stoch 88–98, RSI often ~62) while H1 was
  below its EMA. The grid/hedge and 6–25 lot gold scale-in are **not**
  copied — 1% risk and a single ticket stay.

This module is its own strategy id (``operator_style``). It does not
claim a 75% ticket win rate and it does not loosen the 1.5 R:R floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from chronoscalp.indicators.technical import adx, ema, rsi, stochastic
from chronoscalp.strategy.delta import reference_stop_atr
from chronoscalp.strategy.symbol_catalog import merge_symbol_overrides
from chronoscalp.utils.types import Signal, SignalType, Timeframe, TrendDirection

STRATEGY_ID = "operator_style"
_DEFAULT_SETUPS = ("fade_extension", "fade_rollover", "htf_pullback")


@dataclass(frozen=True)
class OperatorStyleVerdict:
    """Result of the ADX + Stochastic classifier."""

    allow: bool
    setup: str
    direction: TrendDirection
    reason: str
    adx: float | None = None
    stoch_k: float | None = None
    rsi: float | None = None


def _none(symbol: str, reason: str) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=SignalType.NONE,
        timestamp=datetime.now(UTC),
        entry_price=0.0,
        stop_loss=0.0,
        take_profit=0.0,
        timeframe=Timeframe.M5,
        reason=f"{STRATEGY_ID}:{reason}",
        strategy=STRATEGY_ID,
    )


def _root(symbol: str) -> str:
    return str(symbol).upper().split("_", 1)[0]


def _last_float(frame: pd.DataFrame | None, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    value = frame[column].iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _with_timing_columns(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    """Attach ADX / Stoch / RSI / EMA20 when the live enrich path missed them."""
    if frame is None or frame.empty:
        return frame
    out = frame
    need_ohlc = all(col in out.columns for col in ("high", "low", "close"))
    if not need_ohlc:
        return out
    if "adx" not in out.columns:
        out = out.join(adx(out))
    if "stoch_k" not in out.columns:
        out = out.join(stochastic(out))
    if "rsi" not in out.columns:
        out = out.copy()
        out["rsi"] = rsi(out["close"])
    if "ema_20" not in out.columns:
        out = out.copy()
        out["ema_20"] = ema(out["close"], 20)
    return out


def _parse_hhmm(value: str) -> time | None:
    parts = str(value).strip().split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return time(hour, minute)
    except (TypeError, ValueError, IndexError):
        return None


def in_operator_session(moment: datetime, cfg: dict[str, Any]) -> bool:
    """True when ``moment`` falls in the configured Iran-afternoon window."""
    if not bool(cfg.get("require_session", True)):
        return True
    tz_name = str(cfg.get("session_timezone") or "Asia/Tehran")
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError, Exception):
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(zone).time()
    start = _parse_hhmm(str(cfg.get("session_start") or "13:00"))
    end = _parse_hhmm(str(cfg.get("session_end") or "18:30"))
    if start is None or end is None:
        return False
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def _bar_time(frame: pd.DataFrame) -> datetime:
    last = frame.iloc[-1]
    name = last.name
    if isinstance(name, pd.Timestamp):
        ts = name.to_pydatetime()
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts
    return datetime.now(UTC)


def _m5_confirms(m5: pd.DataFrame, direction: TrendDirection) -> bool:
    """Pullback/rollover confirmation: last M5 closed with the setup."""
    if m5 is None or len(m5) < 2:
        return False
    last = m5.iloc[-1]
    prev = m5.iloc[-2]
    close = float(last["close"])
    opened = float(last["open"])
    prev_close = float(prev["close"])
    if direction == TrendDirection.BULLISH:
        return close > opened or close > prev_close
    return close < opened or close < prev_close


def evaluate_operator_style(
    m15: pd.DataFrame | None,
    m5: pd.DataFrame | None,
    *,
    config: dict[str, Any] | None = None,
) -> OperatorStyleVerdict:
    """Return a fade, rollover, or HTF-pullback verdict from M15 ADX and M5 Stoch.

    Gold money required Stochastic **and** RSI extremes (``fade_require_both``).
    EUR directional sells were Stochastic-extreme with RSI often only ~62, so
    that symbol sets ``fade_require_both: false``.
    """
    cfg = config or {}
    min_adx = float(cfg.get("min_adx", 25.0))
    fade_rsi = float(cfg.get("fade_rsi", 70.0))
    fade_stoch = float(cfg.get("fade_stoch", 80.0))
    pullback_stoch = float(cfg.get("pullback_stoch", 25.0))
    require_both = bool(cfg.get("fade_require_both", True))
    allowed = {str(item) for item in (cfg.get("allowed_setups") or [])} or set(_DEFAULT_SETUPS)

    m15_x = _with_timing_columns(m15)
    m5_x = _with_timing_columns(m5 if m5 is not None else m15)
    adx_value = _last_float(m15_x, "adx") if m15_x is not None else None
    if adx_value is None or adx_value < min_adx:
        return OperatorStyleVerdict(
            False, "", TrendDirection.NEUTRAL, "weak_adx", adx=adx_value
        )

    stoch_k = _last_float(m5_x, "stoch_k")
    rsi_m5 = _last_float(m5_x, "rsi")
    rsi_m15 = _last_float(m15_x, "rsi")
    stoch_m15 = _last_float(m15_x, "stoch_k")
    close_m15 = _last_float(m15_x, "close")
    ema20_m15 = _last_float(m15_x, "ema_20")
    above_fast = (
        close_m15 is not None and ema20_m15 is not None and close_m15 > ema20_m15
    )

    stoch_high = stoch_k is not None and stoch_k >= fade_stoch
    stoch_low = stoch_k is not None and stoch_k <= (100.0 - fade_stoch)
    rsi_m5_high = rsi_m5 is not None and rsi_m5 >= fade_rsi
    rsi_m5_low = rsi_m5 is not None and rsi_m5 <= (100.0 - fade_rsi)
    rsi_any_high = rsi_m5_high or (rsi_m15 is not None and rsi_m15 >= fade_rsi)
    rsi_any_low = rsi_m5_low or (rsi_m15 is not None and rsi_m15 <= (100.0 - fade_rsi))
    if require_both:
        sell_stretch = stoch_high and rsi_m5_high
        buy_stretch = stoch_low and rsi_m5_low
    else:
        sell_stretch = stoch_high or rsi_any_high
        buy_stretch = stoch_low or rsi_any_low

    if "fade_extension" in allowed:
        if sell_stretch and not buy_stretch:
            return OperatorStyleVerdict(
                True,
                "fade_extension",
                TrendDirection.BEARISH,
                "ok",
                adx=adx_value,
                stoch_k=stoch_k,
                rsi=rsi_m5 if rsi_m5 is not None else rsi_m15,
            )
        if buy_stretch and not sell_stretch:
            return OperatorStyleVerdict(
                True,
                "fade_extension",
                TrendDirection.BULLISH,
                "ok",
                adx=adx_value,
                stoch_k=stoch_k,
                rsi=rsi_m5 if rsi_m5 is not None else rsi_m15,
            )

    m15_sell_stretch = (rsi_m15 is not None and rsi_m15 >= fade_rsi) or (
        stoch_m15 is not None and stoch_m15 >= fade_stoch
    )
    m15_buy_stretch = (rsi_m15 is not None and rsi_m15 <= (100.0 - fade_rsi)) or (
        stoch_m15 is not None and stoch_m15 <= (100.0 - fade_stoch)
    )
    m5_dumped = stoch_k is not None and stoch_k <= pullback_stoch
    m5_bounced = stoch_k is not None and stoch_k >= (100.0 - pullback_stoch)
    if "fade_rollover" in allowed:
        if m15_sell_stretch and m5_dumped:
            return OperatorStyleVerdict(
                True,
                "fade_rollover",
                TrendDirection.BEARISH,
                "ok",
                adx=adx_value,
                stoch_k=stoch_k,
                rsi=rsi_m5,
            )
        if m15_buy_stretch and m5_bounced:
            return OperatorStyleVerdict(
                True,
                "fade_rollover",
                TrendDirection.BULLISH,
                "ok",
                adx=adx_value,
                stoch_k=stoch_k,
                rsi=rsi_m5,
            )

    if "htf_pullback" in allowed and stoch_k is not None and ema20_m15 is not None:
        if above_fast and stoch_k <= pullback_stoch:
            return OperatorStyleVerdict(
                True,
                "htf_pullback",
                TrendDirection.BULLISH,
                "ok",
                adx=adx_value,
                stoch_k=stoch_k,
                rsi=rsi_m5,
            )
        if (not above_fast) and stoch_k >= (100.0 - pullback_stoch):
            return OperatorStyleVerdict(
                True,
                "htf_pullback",
                TrendDirection.BEARISH,
                "ok",
                adx=adx_value,
                stoch_k=stoch_k,
                rsi=rsi_m5,
            )

    return OperatorStyleVerdict(
        False,
        "",
        TrendDirection.NEUTRAL,
        "no_style_setup",
        adx=adx_value,
        stoch_k=stoch_k,
        rsi=rsi_m5,
    )


def _structural_stop(m5: pd.DataFrame, signal_type: SignalType, lookback: int) -> float:
    window = m5.iloc[-max(2, lookback) :]
    if signal_type == SignalType.BUY:
        return float(window["low"].min())
    return float(window["high"].max())


def generate_operator_style_signal(
    symbol: str,
    trigger_df: pd.DataFrame,
    higher_frames: list[pd.DataFrame],
    *,
    config: dict[str, Any] | None = None,
    symbol_spec: dict[str, Any] | None = None,
    spread_pips: float | None = None,
) -> Signal:
    """Build a single-ticket operator-style signal from completed M5/M15 bars.

    Geometry copies Delta's cost-aware stop (HTF ATR, cost fraction, 1.5R
    floor). Session, ADX, and setup filters are this engine's own.
    """
    cfg = merge_symbol_overrides(config or {}, symbol)
    if cfg.get("enabled") is False:
        return _none(symbol, "disabled")
    allowed = {_root(item) for item in cfg.get("allowed_symbols", ["XAUUSD", "EURUSD"])}
    if _root(symbol) not in allowed:
        return _none(symbol, "symbol_blocked")
    m5 = trigger_df
    if m5 is None or len(m5) < 8:
        return _none(symbol, "insufficient_bars")
    m15 = higher_frames[0] if higher_frames else m5
    if not in_operator_session(_bar_time(m5), cfg):
        return _none(symbol, "outside_session")

    last = m5.iloc[-1]
    if any(pd.isna(last.get(key)) for key in ("open", "high", "low", "close")):
        return _none(symbol, "indicators_nan")
    atr = float(last["atr"]) if "atr" in m5.columns and not pd.isna(last.get("atr")) else 0.0
    if atr <= 0:
        return _none(symbol, "atr_zero")

    verdict = evaluate_operator_style(m15, m5, config=cfg)
    if not verdict.allow:
        return _none(symbol, verdict.reason or "no_style_setup")

    needs_confirm = verdict.setup in {"htf_pullback", "fade_rollover"}
    if needs_confirm and not _m5_confirms(m5, verdict.direction):
        return _none(symbol, "no_confirmation")

    signal_type = (
        SignalType.BUY if verdict.direction == TrendDirection.BULLISH else SignalType.SELL
    )
    lookback = max(2, int(cfg.get("structure_lookback", 3)))
    structural_stop = _structural_stop(m5, signal_type, lookback)
    close = float(last["close"])
    if signal_type == SignalType.BUY and structural_stop >= close:
        return _none(symbol, "bad_stop")
    if signal_type == SignalType.SELL and structural_stop <= close:
        return _none(symbol, "bad_stop")

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

    rr = max(1.5, float(cfg.get("reward_risk_ratio", 1.5)))
    if signal_type == SignalType.BUY:
        stop_loss, take_profit = close - stop_distance, close + rr * stop_distance
    else:
        stop_loss, take_profit = close + stop_distance, close - rr * stop_distance

    adx_txt = f"{verdict.adx:.1f}" if verdict.adx is not None else "?"
    stoch_txt = f"{verdict.stoch_k:.1f}" if verdict.stoch_k is not None else "?"
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        timestamp=_bar_time(m5),
        entry_price=close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=0.62,
        reason=(
            f"{STRATEGY_ID},{verdict.setup},trend={verdict.direction.value},"
            f"adx={adx_txt},stoch={stoch_txt}"
        ),
        timeframe=Timeframe.M5,
        strategy=STRATEGY_ID,
    )
