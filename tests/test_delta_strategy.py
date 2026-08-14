from __future__ import annotations

import numpy as np
import pandas as pd

from chronoscalp.strategy.delta import delta_regime, generate_delta_signal
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy
from chronoscalp.utils.types import SignalType, Timeframe, TrendDirection


def _higher(direction: str, n: int = 80) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    close = np.linspace(100.0, 104.0, n) if direction == "up" else np.linspace(104.0, 100.0, n)
    ema = close - 0.25 if direction == "up" else close + 0.25
    rsi = np.full(n, 58.0 if direction == "up" else 42.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "ema_50": ema,
            "rsi": rsi,
            "atr": np.full(n, 0.5),
        },
        index=index,
    )


def _long_sweep_trigger() -> pd.DataFrame:
    n = 17
    index = pd.date_range("2026-01-02", periods=n, freq="min", tz="UTC")
    open_ = np.full(n, 100.2)
    high = np.full(n, 100.5)
    low = np.full(n, 100.0)
    close = np.full(n, 100.3)
    # Penultimate bar sweeps the established 100.00 low and reclaims it.
    open_[-2], high[-2], low[-2], close[-2] = 100.15, 100.3, 99.8, 100.1
    # Last bar confirms with a strong bullish close.
    open_[-1], high[-1], low[-1], close[-1] = 100.1, 100.75, 100.05, 100.7
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 1.4),
        },
        index=index,
    )


def test_delta_regime_requires_two_aligned_frames():
    assert delta_regime([_higher("up"), _higher("up")]) == TrendDirection.BULLISH
    assert delta_regime([_higher("up"), _higher("down")]) == TrendDirection.NEUTRAL
    assert delta_regime([_higher("up")]) == TrendDirection.NEUTRAL


def test_delta_long_sweep_has_structural_cost_aware_geometry():
    signal = generate_delta_signal(
        "XAUUSD_o",
        _long_sweep_trigger(),
        [_higher("up"), _higher("up")],
        config={"reward_risk_ratio": 1.8, "max_atr_close_ratio": 0.01},
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy == "delta"
    assert "sweep_reclaim" in signal.reason
    assert signal.risk_reward_ratio >= 1.8
    assert signal.entry_price - signal.stop_loss >= 0.4  # 2x a $0.20 spread


def test_delta_rejects_unapproved_symbol_and_low_volume():
    blocked = generate_delta_signal("BTCUSD", _long_sweep_trigger(), [_higher("up"), _higher("up")])
    assert blocked.signal_type == SignalType.NONE
    assert blocked.reason == "delta:symbol_blocked"

    low_volume = _long_sweep_trigger()
    low_volume.loc[low_volume.index[-1], "rvol"] = 0.8
    rejected = generate_delta_signal(
        "XAUUSD",
        low_volume,
        [_higher("up"), _higher("up")],
        config={"max_atr_close_ratio": 0.01},
    )
    assert rejected.signal_type == SignalType.NONE
    assert rejected.reason == "delta:low_rvol"


def test_delta_rejects_stop_that_is_too_wide_for_atr():
    trigger = _long_sweep_trigger()
    trigger.loc[trigger.index[-2], "low"] = 95.0
    signal = generate_delta_signal(
        "XAUUSD",
        trigger,
        [_higher("up"), _higher("up")],
        config={"max_stop_atr": 2.0, "max_atr_close_ratio": 0.01},
    )
    assert signal.signal_type == SignalType.NONE
    assert signal.reason == "delta:stop_too_wide"


def test_delta_is_wired_into_multi_timeframe_strategy():
    strategy = MultiTimeframeStrategy(
        {
            "enabled_strategies": ["delta"],
            "delta": {"max_atr_close_ratio": 0.01},
            "entry_engine": "institutional",
        },
        {"ema_period_trend": 50},
        {"XAUUSD_o": {"pip_size": 0.01, "typical_spread_pips": 20}},
    )
    signal = strategy.evaluate(
        "XAUUSD_o",
        {
            Timeframe.M15: _higher("up"),
            Timeframe.M5: _higher("up"),
            Timeframe.M1: _long_sweep_trigger(),
        },
        higher_timeframes=[Timeframe.M15, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        ignore_confidence_gate=True,
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy == "delta"


def test_delta_only_does_not_run_institutional_path():
    """Selecting only Delta must not also fire SMC/liquidity institutional entries."""
    strategy = MultiTimeframeStrategy(
        {
            "enabled_strategies": ["delta"],
            "delta": {"max_atr_close_ratio": 0.01},
            "entry_engine": "institutional",
            "use_smc_confluence": False,
            "use_liquidity_volume": False,
        },
        {"ema_period_trend": 50},
        {"XAUUSD_o": {"pip_size": 0.01, "typical_spread_pips": 20}},
    )
    # Neutral M1 (no sweep) — Delta should stay silent; institutional must not sneak in.
    n = 17
    index = pd.date_range("2026-01-02", periods=n, freq="min", tz="UTC")
    flat = pd.DataFrame(
        {
            "open": np.full(n, 100.2),
            "high": np.full(n, 100.5),
            "low": np.full(n, 100.0),
            "close": np.full(n, 100.3),
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 1.4),
            "macd": np.zeros(n),
            "macd_signal": np.zeros(n),
            "macd_hist": np.zeros(n),
            "bb_upper": np.full(n, 101.0),
            "bb_lower": np.full(n, 99.0),
            "bb_mid": np.full(n, 100.0),
        },
        index=index,
    )
    signal = strategy.evaluate(
        "XAUUSD_o",
        {
            Timeframe.M15: _higher("up"),
            Timeframe.M5: _higher("up"),
            Timeframe.M1: flat,
        },
        higher_timeframes=[Timeframe.M15, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        ignore_confidence_gate=True,
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.NONE
    assert "delta:" in (signal.reason or "")
