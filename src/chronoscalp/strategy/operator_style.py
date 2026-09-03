"""Operator-style selectivity: ADX trend strength + Stochastic timing.

Measured on AUSCommercial-Demo magic=0 fills, 14d to 2026-09-03:

* Gold: 7 bursts, 6 winners, +$57k. Every burst sat in Iran 13:00–18:00
  with M15 ADX ≥ 22. The large SELL baskets faded RSI/Stoch spikes
  (RSI 69–78, Stoch 80+) on a strong ADX tape; the BUY baskets were M5
  pullbacks (Stoch 21–33) while H1/M15 stayed above the fast EMA.
* EUR: 0.01 grids plus occasional 5-lot hedges. The directional subset
  sold M5 overbought prints while H1 was below its EMA. The grid/hedge
  and 6–25 lot gold scale-in are **not** copied — 1% risk stays.

These two indicators raise selectivity. They do not claim a 75% win rate
and they do not loosen the 1.5 R:R floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from chronoscalp.indicators.technical import adx, ema, rsi, stochastic
from chronoscalp.utils.types import TrendDirection


@dataclass(frozen=True)
class OperatorStyleVerdict:
    """Result of the ADX + Stochastic gate."""

    allow: bool
    setup: str
    direction: TrendDirection
    reason: str
    adx: float | None = None
    stoch_k: float | None = None
    rsi: float | None = None


def _last_float(frame: pd.DataFrame, column: str) -> float | None:
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


def evaluate_operator_style(
    m15: pd.DataFrame | None,
    m5: pd.DataFrame | None,
    *,
    config: dict[str, Any] | None = None,
) -> OperatorStyleVerdict:
    """Return a fade or HTF-pullback verdict from M15 ADX and M5 Stochastic.

    ``weak_adx`` is a hard skip. ``no_style_setup`` means the tape is strong
    enough for the legacy Delta sweep path to still try.
    """
    cfg = config or {}
    min_adx = float(cfg.get("min_adx", 25.0))
    fade_rsi = float(cfg.get("fade_rsi", 70.0))
    fade_stoch = float(cfg.get("fade_stoch", 80.0))
    pullback_stoch = float(cfg.get("pullback_stoch", 25.0))
    allowed = {str(item) for item in (cfg.get("allowed_setups") or [])} or {
        "fade_extension",
        "htf_pullback",
        "sweep_reclaim",
        "breakout_retest",
    }

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
    close_m15 = _last_float(m15_x, "close")
    ema20_m15 = _last_float(m15_x, "ema_20")
    above_fast = (
        close_m15 is not None and ema20_m15 is not None and close_m15 > ema20_m15
    )

    if "fade_extension" in allowed:
        sell_stretch = (stoch_k is not None and stoch_k >= fade_stoch) or (
            rsi_m5 is not None and rsi_m5 >= fade_rsi
        ) or (rsi_m15 is not None and rsi_m15 >= fade_rsi)
        buy_stretch = (stoch_k is not None and stoch_k <= (100.0 - fade_stoch)) or (
            rsi_m5 is not None and rsi_m5 <= (100.0 - fade_rsi)
        ) or (rsi_m15 is not None and rsi_m15 <= (100.0 - fade_rsi))
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
