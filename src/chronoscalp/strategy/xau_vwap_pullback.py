"""XAUUSD VWAP pullback continuation — research candidate, not live-ready.

Closed M15 regime, M5 impulse, M1 rejection trigger. Fail-closed on stale
data, invalid ATR/spread, or any hard gate. Default config is disabled +
shadow_only; this module never enables live trading by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from chronoscalp.filters.spread_shield import spread_allowed
from chronoscalp.indicators.session_vwap import session_vwap
from chronoscalp.indicators.technical import ema
from chronoscalp.risk.position_sizing import HARD_MIN_GROSS_RR, commission_per_lot
from chronoscalp.utils.types import Signal, SignalType, Timeframe, TrendDirection

STRATEGY_ID = "xau_vwap_pullback"


def _root(symbol: str) -> str:
    return str(symbol).upper().split("_", 1)[0]


def _none(symbol: str, reason: str) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=SignalType.NONE,
        timestamp=datetime.now(UTC),
        entry_price=0.0,
        stop_loss=0.0,
        take_profit=0.0,
        timeframe=Timeframe.M1,
        reason=f"{STRATEGY_ID}:{reason}",
        strategy=STRATEGY_ID,
    )


def _ensure_ema(df: pd.DataFrame, period: int) -> pd.DataFrame:
    col = f"ema_{period}"
    if col in df.columns and not pd.isna(df[col].iloc[-1]):
        return df
    out = df.copy()
    out[col] = ema(out["close"].astype(float), period)
    return out


def _bar_time(row: pd.Series) -> datetime:
    if isinstance(row.name, pd.Timestamp):
        ts = row.name
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.to_pydatetime()
    return datetime.now(UTC)


@dataclass
class ImpulseState:
    direction: TrendDirection
    origin: float
    extreme: float
    broken_level: float
    started_at: datetime
    m1_bars: int = 0


@dataclass
class PendingTrigger:
    direction: TrendDirection
    entry: float
    stop_loss: float
    take_profit: float
    rejection_high: float
    rejection_low: float
    score: int
    rvol: float
    created_at: datetime
    bars_left: int
    atr: float
    reason: str
    emitted: bool = False


@dataclass
class XauVwapPullbackEngine:
    """Stateful M15/M5/M1 pullback engine. One instance is shared by live and backtest."""

    cfg: dict[str, Any] = field(default_factory=dict)
    symbols_cfg: dict[str, Any] = field(default_factory=dict)
    _impulse: dict[str, ImpulseState] = field(default_factory=dict)
    _pending: dict[str, PendingTrigger] = field(default_factory=dict)

    def reset(self) -> None:
        self._impulse.clear()
        self._pending.clear()

    def evaluate(
        self,
        symbol: str,
        *,
        m1: pd.DataFrame,
        m5: pd.DataFrame,
        m15: pd.DataFrame,
        spread_pips: float | None = None,
        median_spread_pips: float | None = None,
        broker_spread_cap_pips: float | None = None,
    ) -> Signal:
        """Evaluate closed M1/M5/M15 frames. HTF must already be as-of the M1 close."""
        cfg = self.cfg
        if not bool(cfg.get("enabled", False)) and not bool(cfg.get("shadow_only", True)):
            return _none(symbol, "disabled")
        allowed = {_root(item) for item in cfg.get("allowed_symbols", ["XAUUSD"])}
        if _root(symbol) not in allowed:
            return _none(symbol, "symbol_blocked")
        if m1 is None or m5 is None or m15 is None:
            return _none(symbol, "stale_data")
        if len(m1) < 8 or len(m5) < 12 or len(m15) < 8:
            return _none(symbol, "insufficient_bars")
        if any(pd.isna(m1.iloc[-1].get(c)) for c in ("open", "high", "low", "close", "atr")):
            return _none(symbol, "stale_data")

        spec = self.symbols_cfg.get(symbol) or self.symbols_cfg.get(_root(symbol)) or {}
        pip_size = float(spec.get("pip_size", 0.01) or 0.01)
        effective_spread = float(
            spread_pips if spread_pips is not None else spec.get("typical_spread_pips", 0.0) or 0.0
        )
        if effective_spread <= 0 or pip_size <= 0:
            return _none(symbol, "spread_invalid")
        cap = float(
            broker_spread_cap_pips
            if broker_spread_cap_pips is not None
            else spec.get("max_spread_pips", spec.get("typical_spread_pips", effective_spread))
            or effective_spread
        )
        expansion = float(cfg.get("spread_median_expansion", 1.2))
        ok, why = spread_allowed(
            effective_spread,
            broker_cap_pips=cap,
            rolling_median_pips=median_spread_pips,
            expansion=expansion,
        )
        if not ok:
            return _none(symbol, why or "spread_block")

        m15 = _ensure_ema(m15, 20)
        m15 = _ensure_ema(m15, 50)
        m5 = _ensure_ema(m5, 20)
        m5 = _ensure_ema(m5, 50)

        regime, regime_score, m15_aligned = score_m15_regime(m15, cfg)
        if regime == TrendDirection.NEUTRAL or regime_score < 2:
            self._impulse.pop(symbol, None)
            self._pending.pop(symbol, None)
            return _none(symbol, "regime_neutral")
        if m5_hard_opposite(m5, regime, cfg):
            self._impulse.pop(symbol, None)
            self._pending.pop(symbol, None)
            return _none(symbol, "m5_opposite")

        last_m1 = m1.iloc[-1]
        atr_m1 = float(last_m1["atr"])
        if atr_m1 <= 0:
            return _none(symbol, "atr_invalid")

        impulse = detect_m5_impulse(m5, regime, cfg)
        existing = self._impulse.get(symbol)
        if impulse is not None:
            self._impulse[symbol] = impulse
            existing = impulse
        elif existing is not None:
            existing.m1_bars += 1
            expire_bars = int(cfg.get("impulse_expire_m1_bars", 6))
            if existing.m1_bars > expire_bars:
                self._impulse.pop(symbol, None)
                self._pending.pop(symbol, None)
                return _none(symbol, "impulse_expired")
            if origin_violated(last_m1, existing):
                self._impulse.pop(symbol, None)
                self._pending.pop(symbol, None)
                return _none(symbol, "impulse_origin_broken")
        else:
            self._pending.pop(symbol, None)
            return _none(symbol, "no_impulse")

        pending = self._pending.get(symbol)
        if pending is not None:
            pending.bars_left -= 1
            chase_atr = float(cfg.get("no_chase_atr", 0.25))
            last_close = float(last_m1["close"])
            if abs(last_close - pending.entry) > chase_atr * pending.atr:
                self._pending.pop(symbol, None)
                return _none(symbol, "no_chase")
            if pending.bars_left <= 0:
                self._pending.pop(symbol, None)
                return _none(symbol, "trigger_expired")
            if pending.emitted:
                return _none(symbol, "awaiting_fill")
            return _none(symbol, "awaiting_trigger")

        vwap = session_vwap(m15) or session_vwap(m1)
        pullback = assess_m1_pullback(
            m1,
            existing,
            vwap,
            cfg,
        )
        if pullback is None:
            return _none(symbol, "no_pullback")

        geometry = build_geometry(
            symbol=symbol,
            spec=spec,
            m1=m1,
            impulse=existing,
            pullback=pullback,
            spread_pips=effective_spread,
            pip_size=pip_size,
            cfg=cfg,
        )
        if geometry is None:
            return _none(symbol, "geometry_reject")

        m5_aligned = not m5_hard_opposite(m5, regime, cfg) and m5_same_bias(m5, regime, cfg)
        score = setup_score(
            regime_score=regime_score,
            pullback=pullback,
            rvol=float(last_m1.get("rvol", 0.0) or 0.0),
            spread_pips=effective_spread,
            median_spread_pips=median_spread_pips,
            m5_and_m15_aligned=bool(m15_aligned and m5_aligned),
            rvol_min=float(cfg.get("m1_rvol_score_min", 1.10)),
        )
        min_score = int(cfg.get("min_score", 5))
        if score < min_score:
            return _none(symbol, f"score_{score}")

        tick = pip_size
        if pullback.direction == TrendDirection.BULLISH:
            entry = pullback.rejection_high + tick
        else:
            entry = pullback.rejection_low - tick

        reason = (
            f"{STRATEGY_ID},pullback_rejection,trend={pullback.direction.value},"
            f"score={score},rvol={pullback.rvol:.2f}"
        )
        pending = PendingTrigger(
            direction=pullback.direction,
            entry=entry,
            stop_loss=geometry[0],
            take_profit=geometry[1],
            rejection_high=pullback.rejection_high,
            rejection_low=pullback.rejection_low,
            score=score,
            rvol=pullback.rvol,
            created_at=_bar_time(last_m1),
            bars_left=int(cfg.get("trigger_expire_m1_bars", 2)),
            atr=atr_m1,
            reason=reason,
        )
        pending.emitted = True
        self._pending[symbol] = pending
        return self._signal_from_pending(symbol, pending, last_m1)

    def _signal_from_pending(self, symbol: str, pending: PendingTrigger, last: pd.Series) -> Signal:
        conf = min(0.8, 0.5 + pending.score * 0.04)
        return Signal(
            symbol=symbol,
            signal_type=(
                SignalType.BUY if pending.direction == TrendDirection.BULLISH else SignalType.SELL
            ),
            timestamp=_bar_time(last),
            entry_price=pending.entry,
            stop_loss=pending.stop_loss,
            take_profit=pending.take_profit,
            confidence=conf,
            reason=pending.reason,
            timeframe=Timeframe.M1,
            strategy=STRATEGY_ID,
        )


@dataclass(frozen=True)
class PullbackSetup:
    direction: TrendDirection
    rejection_high: float
    rejection_low: float
    rvol: float
    touched_level_and_vwap: bool
    wick_ok: bool


def score_m15_regime(m15: pd.DataFrame, cfg: dict[str, Any]) -> tuple[TrendDirection, int, bool]:
    """Return (bias, score 0-3, full 3/3 alignment). Need >=2 for a directional bias."""
    last = m15.iloc[-1]
    slope_bars = max(1, int(cfg.get("ema_slope_bars", 3)))
    if len(m15) <= slope_bars:
        return TrendDirection.NEUTRAL, 0, False
    prior = m15.iloc[-1 - slope_bars]
    ema20 = float(last.get("ema_20", float("nan")))
    ema50 = float(last.get("ema_50", float("nan")))
    if any(pd.isna(x) for x in (ema20, ema50, last["close"])):
        return TrendDirection.NEUTRAL, 0, False
    vwap = session_vwap(m15)
    close = float(last["close"])
    slope = ema20 - float(prior.get("ema_20", ema20))

    long_pts = 0
    short_pts = 0
    if vwap is not None:
        if close > vwap:
            long_pts += 1
        elif close < vwap:
            short_pts += 1
    if ema20 > ema50:
        long_pts += 1
    elif ema20 < ema50:
        short_pts += 1
    if slope > 0:
        long_pts += 1
    elif slope < 0:
        short_pts += 1

    if long_pts >= 2 and long_pts >= short_pts:
        return TrendDirection.BULLISH, long_pts, long_pts == 3
    if short_pts >= 2 and short_pts >= long_pts:
        return TrendDirection.BEARISH, short_pts, short_pts == 3
    return TrendDirection.NEUTRAL, max(long_pts, short_pts), False


def m5_same_bias(m5: pd.DataFrame, regime: TrendDirection, cfg: dict[str, Any]) -> bool:
    bias, score, _ = score_m15_regime(m5, cfg)
    return bias == regime and score >= 2


def m5_hard_opposite(m5: pd.DataFrame, regime: TrendDirection, cfg: dict[str, Any]) -> bool:
    bias, score, _ = score_m15_regime(m5, cfg)
    if bias == TrendDirection.NEUTRAL or score < 2:
        return False
    return bias != regime


def detect_m5_impulse(
    m5: pd.DataFrame, regime: TrendDirection, cfg: dict[str, Any]
) -> ImpulseState | None:
    lookback = int(cfg.get("impulse_lookback", 8))
    swing = int(cfg.get("impulse_swing_bars", 10))
    body_atr = float(cfg.get("impulse_body_atr", 0.6))
    rvol_min = float(cfg.get("impulse_rvol_min", 1.10))
    if len(m5) < max(lookback, swing) + 2:
        return None
    window = m5.iloc[-lookback:]
    last = window.iloc[-1]
    atr = float(last.get("atr", 0.0) or 0.0)
    if atr <= 0:
        return None
    body = abs(float(last["close"]) - float(last["open"]))
    if body < body_atr * atr:
        return None
    rvol = float(last.get("rvol", 0.0) or 0.0)
    if rvol < rvol_min:
        return None
    prior = m5.iloc[-(lookback + swing) : -1]
    if prior.empty:
        return None
    close = float(last["close"])
    if regime == TrendDirection.BULLISH:
        level = float(prior["high"].max())
        if close <= level:
            return None
        origin = float(window["low"].min())
        return ImpulseState(
            direction=regime,
            origin=origin,
            extreme=float(last["high"]),
            broken_level=level,
            started_at=_bar_time(last),
        )
    level = float(prior["low"].min())
    if close >= level:
        return None
    origin = float(window["high"].max())
    return ImpulseState(
        direction=regime,
        origin=origin,
        extreme=float(last["low"]),
        broken_level=level,
        started_at=_bar_time(last),
    )


def origin_violated(m1_row: pd.Series, impulse: ImpulseState) -> bool:
    close = float(m1_row["close"])
    if impulse.direction == TrendDirection.BULLISH:
        return close < impulse.origin
    return close > impulse.origin


def assess_m1_pullback(
    m1: pd.DataFrame,
    impulse: ImpulseState,
    vwap: float | None,
    cfg: dict[str, Any],
) -> PullbackSetup | None:
    last = m1.iloc[-1]
    atr = float(last["atr"])
    if atr <= 0:
        return None
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    open_ = float(last["open"])
    rng = max(high - low, 1e-12)
    body = abs(close - open_)
    if body / rng < float(cfg.get("min_body_fraction", 0.45)):
        return None
    if impulse.direction == TrendDirection.BULLISH:
        if close < impulse.origin:
            return None
        if close < open_:
            return None
        if close < high - 0.30 * rng:
            return None
        span = impulse.extreme - impulse.origin
        retrace = (impulse.extreme - close) / span if span > 0 else 1.0
        touch_tol = float(cfg.get("level_touch_atr", 0.20)) * atr
        touched_level = abs(low - impulse.broken_level) <= touch_tol
        touched_vwap = vwap is not None and abs(low - vwap) <= touch_tol
        retrace_ok = 0.30 <= retrace <= 0.65
        if not (retrace_ok or touched_level or touched_vwap):
            return None
        wick_ok = (min(open_, close) - low) / rng >= 0.25
        return PullbackSetup(
            direction=TrendDirection.BULLISH,
            rejection_high=high,
            rejection_low=low,
            rvol=float(last.get("rvol", 0.0) or 0.0),
            touched_level_and_vwap=bool(touched_level and touched_vwap),
            wick_ok=wick_ok,
        )
    if close > impulse.origin:
        return None
    if close > open_:
        return None
    if close > low + 0.30 * rng:
        return None
    span = impulse.origin - impulse.extreme
    retrace = (close - impulse.extreme) / span if span > 0 else 1.0
    touch_tol = float(cfg.get("level_touch_atr", 0.20)) * atr
    touched_level = abs(high - impulse.broken_level) <= touch_tol
    touched_vwap = vwap is not None and abs(high - vwap) <= touch_tol
    retrace_ok = 0.30 <= retrace <= 0.65
    if not (retrace_ok or touched_level or touched_vwap):
        return None
    wick_ok = (high - max(open_, close)) / rng >= 0.25
    return PullbackSetup(
        direction=TrendDirection.BEARISH,
        rejection_high=high,
        rejection_low=low,
        rvol=float(last.get("rvol", 0.0) or 0.0),
        touched_level_and_vwap=bool(touched_level and touched_vwap),
        wick_ok=wick_ok,
    )


def nearest_opposing_liquidity(
    m1: pd.DataFrame, direction: TrendDirection, lookback: int = 20
) -> float | None:
    """Nearest swing that would cap the trade before target."""
    if m1 is None or len(m1) < 5:
        return None
    window = m1.iloc[-lookback:] if len(m1) > lookback else m1
    if direction == TrendDirection.BULLISH:
        if "swing_high" in window.columns:
            hits = window[window["swing_high"].astype(bool)]
            if not hits.empty:
                return float(hits.iloc[-1]["high"])
        return float(window["high"].max())
    if "swing_low" in window.columns:
        hits = window[window["swing_low"].astype(bool)]
        if not hits.empty:
            return float(hits.iloc[-1]["low"])
    return float(window["low"].min())


def build_geometry(
    *,
    symbol: str,
    spec: dict[str, Any],
    m1: pd.DataFrame,
    impulse: ImpulseState,
    pullback: PullbackSetup,
    spread_pips: float,
    pip_size: float,
    cfg: dict[str, Any],
) -> tuple[float, float] | None:
    last = m1.iloc[-1]
    atr = float(last["atr"])
    tick = pip_size
    if pullback.direction == TrendDirection.BULLISH:
        entry = pullback.rejection_high + tick
        raw_sl = pullback.rejection_low - float(cfg.get("sl_buffer_atr", 0.15)) * atr
        stop_dist = entry - raw_sl
    else:
        entry = pullback.rejection_low - tick
        raw_sl = pullback.rejection_high + float(cfg.get("sl_buffer_atr", 0.15)) * atr
        stop_dist = raw_sl - entry
    spread_distance = spread_pips * pip_size
    min_stop = max(float(cfg.get("min_stop_atr", 0.70)) * atr, 2.0 * spread_distance)
    if stop_dist < min_stop:
        stop_dist = min_stop
    max_stop = float(cfg.get("max_stop_atr", 1.80)) * atr
    if stop_dist > max_stop:
        return None
    gross_rr = max(HARD_MIN_GROSS_RR, float(cfg.get("reward_risk_ratio", 2.0)))
    if gross_rr + 1e-12 < HARD_MIN_GROSS_RR:
        return None
    tp_dist = gross_rr * stop_dist
    cost_mult = float(cfg.get("cost_stress_multiple", 1.5))
    pip_value = float(spec.get("pip_value_per_lot", 0.0) or 0.0)
    commission = commission_per_lot(spec, entry)
    cost_price = spread_distance * cost_mult
    if pip_value > 0 and pip_size > 0:
        cost_price += (commission * cost_mult / pip_value) * pip_size
    net_rr = (tp_dist - cost_price) / (stop_dist + cost_price) if stop_dist + cost_price else 0.0
    if net_rr + 1e-12 < float(cfg.get("min_net_rr_cost_stress", 1.25)):
        return None
    opposing = nearest_opposing_liquidity(m1, pullback.direction)
    if opposing is not None:
        if pullback.direction == TrendDirection.BULLISH:
            if entry < opposing < entry + 1.5 * stop_dist:
                return None
        elif entry - 1.5 * stop_dist < opposing < entry:
            return None
    if pullback.direction == TrendDirection.BULLISH:
        return entry - stop_dist, entry + tp_dist
    return entry + stop_dist, entry - tp_dist


def setup_score(
    *,
    regime_score: int,
    pullback: PullbackSetup,
    rvol: float,
    spread_pips: float,
    median_spread_pips: float | None,
    m5_and_m15_aligned: bool,
    rvol_min: float,
) -> int:
    score = 0
    if regime_score >= 3:
        score += 2
    if pullback.touched_level_and_vwap:
        score += 2
    if rvol >= rvol_min:
        score += 1
    if pullback.wick_ok:
        score += 1
    if (
        median_spread_pips is not None
        and median_spread_pips > 0
        and spread_pips < median_spread_pips
    ):
        score += 1
    if m5_and_m15_aligned:
        score += 1
    return score


def generate_xau_vwap_pullback_signal(
    symbol: str,
    trigger_df: pd.DataFrame,
    higher_frames: list[pd.DataFrame],
    *,
    engine: XauVwapPullbackEngine | None = None,
    config: dict[str, Any] | None = None,
    symbol_spec: dict[str, Any] | None = None,
    spread_pips: float | None = None,
    median_spread_pips: float | None = None,
    broker_spread_cap_pips: float | None = None,
) -> Signal:
    """Functional wrapper used by MultiTimeframeStrategy."""
    m5 = (
        higher_frames[1]
        if len(higher_frames) > 1
        else (higher_frames[0] if higher_frames else None)
    )
    m15 = higher_frames[0] if higher_frames else None
    inst = engine or XauVwapPullbackEngine(cfg=config or {}, symbols_cfg={})
    if config:
        inst.cfg = config
    if symbol_spec is not None:
        inst.symbols_cfg[symbol] = symbol_spec
    if m5 is None or m15 is None:
        return _none(symbol, "stale_data")
    return inst.evaluate(
        symbol,
        m1=trigger_df,
        m5=m5,
        m15=m15,
        spread_pips=spread_pips,
        median_spread_pips=median_spread_pips,
        broker_spread_cap_pips=broker_spread_cap_pips,
    )
