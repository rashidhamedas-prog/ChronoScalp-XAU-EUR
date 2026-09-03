from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chronoscalp.strategy.delta import (
    delta_regime,
    generate_delta_signal,
    merge_symbol_config,
    reference_stop_atr,
)
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy
from chronoscalp.utils.types import SignalType, Timeframe, TrendDirection


def _higher(direction: str, n: int = 80, atr: float = 0.5) -> pd.DataFrame:
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
            "atr": np.full(n, atr),
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


def _quiet_trigger(atr: float = 0.2) -> pd.DataFrame:
    """Sweep-reclaim trigger whose own ATR is far below the higher timeframes'.

    Mirrors live XAUUSD: M1 ATR $1.57 against M5 ATR $4.26, so the structural
    stop is several M1 ATRs wide and only fits inside an M5-scaled band.
    """
    trigger = _long_sweep_trigger()
    trigger["atr"] = np.full(len(trigger), atr)
    return trigger


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


def test_merge_symbol_config_applies_override_across_broker_suffix():
    cfg = {
        "min_stop_atr": 0.8,
        "reward_risk_ratio": 1.8,
        "symbol_overrides": {"EURUSD": {"min_stop_atr": 1.5, "reward_risk_ratio": 2.0}},
    }
    assert merge_symbol_config(cfg, "XAUUSD_o")["min_stop_atr"] == 0.8
    merged = merge_symbol_config(cfg, "EURUSD_o")
    assert merged["min_stop_atr"] == 1.5
    assert merged["reward_risk_ratio"] == 2.0
    # The base config must not be mutated.
    assert cfg["min_stop_atr"] == 0.8


def test_reference_stop_atr_prefers_requested_higher_frame():
    frames = [_higher("up", atr=3.0), _higher("up", atr=2.0)]
    assert reference_stop_atr({}, 0.2, frames) == pytest.approx(0.2)
    assert reference_stop_atr({"stop_atr_source": "htf"}, 0.2, frames) == pytest.approx(3.0)
    cfg = {"stop_atr_source": "htf", "stop_atr_htf_index": 1}
    assert reference_stop_atr(cfg, 0.2, frames) == pytest.approx(2.0)
    # Out-of-range index clamps to the last supplied frame.
    cfg_high = {"stop_atr_source": "htf", "stop_atr_htf_index": 9}
    assert reference_stop_atr(cfg_high, 0.2, frames) == pytest.approx(2.0)


def test_reference_stop_atr_falls_back_when_higher_frame_atr_unusable():
    cfg = {"stop_atr_source": "htf"}
    assert reference_stop_atr(cfg, 0.4, []) == pytest.approx(0.4)

    missing_col = _higher("up", atr=3.0).drop(columns=["atr"])
    assert reference_stop_atr(cfg, 0.4, [missing_col]) == pytest.approx(0.4)

    nan_atr = _higher("up", atr=3.0)
    nan_atr.loc[nan_atr.index[-1], "atr"] = np.nan
    assert reference_stop_atr(cfg, 0.4, [nan_atr]) == pytest.approx(0.4)


def test_trigger_atr_anchoring_rejects_a_normal_structural_stop():
    """Regression: M1-ATR anchoring made ordinary structure look "too wide".

    The sweep low is $0.90 below entry — a textbook structural stop — but at an
    M1 ATR of 0.2 the 2.5x cap is only $0.50, so Delta discarded the setup.
    """
    signal = generate_delta_signal(
        "XAUUSD",
        _quiet_trigger(),
        [_higher("up", atr=2.0), _higher("up", atr=2.0)],
        config={"max_atr_close_ratio": 0.01},
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.NONE
    assert signal.reason == "delta:stop_too_wide"


def test_htf_anchoring_accepts_the_same_setup_with_a_survivable_stop():
    trigger_atr = 0.2
    signal = generate_delta_signal(
        "XAUUSD",
        _quiet_trigger(trigger_atr),
        [_higher("up", atr=2.0), _higher("up", atr=2.0)],
        config={
            "stop_atr_source": "htf",
            "min_stop_atr": 0.8,
            "max_stop_atr": 2.0,
            "max_atr_close_ratio": 0.01,
        },
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.BUY
    stop_distance = signal.entry_price - signal.stop_loss
    assert stop_distance == pytest.approx(1.6)
    # The whole point: the stop is many M1 ATRs wide, not a fraction of one.
    assert stop_distance > 4 * trigger_atr


def test_cost_floor_widens_the_stop_so_spread_is_a_minor_share_of_risk():
    signal = generate_delta_signal(
        "XAUUSD",
        _quiet_trigger(),
        [_higher("up", atr=2.0), _higher("up", atr=2.0)],
        config={
            "stop_atr_source": "htf",
            "min_stop_atr": 0.8,
            "max_stop_atr": 2.0,
            "max_cost_fraction_of_risk": 0.15,
            "max_atr_close_ratio": 0.01,
        },
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.BUY
    stop_distance = signal.entry_price - signal.stop_loss
    round_trip_cost = 2 * 20 * 0.01
    assert stop_distance == pytest.approx(round_trip_cost / 0.15)
    assert round_trip_cost / stop_distance <= 0.15


def test_delta_rejects_setup_when_spread_cost_cannot_fit_the_stop_cap():
    signal = generate_delta_signal(
        "XAUUSD",
        _quiet_trigger(),
        [_higher("up", atr=2.0), _higher("up", atr=2.0)],
        config={
            "stop_atr_source": "htf",
            "max_stop_atr": 2.0,
            "max_cost_fraction_of_risk": 0.15,
            "max_atr_close_ratio": 0.01,
        },
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 200},
        spread_pips=200,
    )
    assert signal.signal_type == SignalType.NONE
    assert signal.reason == "delta:cost_exceeds_stop_cap"


def test_eurusd_override_gets_its_own_stop_band_and_target():
    config = {
        "allowed_symbols": ["XAUUSD", "EURUSD"],
        "stop_atr_source": "htf",
        "min_stop_atr": 0.8,
        "max_stop_atr": 2.0,
        "reward_risk_ratio": 1.8,
        "max_atr_close_ratio": 0.01,
        "symbol_overrides": {
            "EURUSD": {"min_stop_atr": 1.5, "max_stop_atr": 3.5, "reward_risk_ratio": 2.0}
        },
    }
    frames = [_higher("up", atr=2.0), _higher("up", atr=2.0)]

    gold = generate_delta_signal(
        "XAUUSD",
        _quiet_trigger(),
        frames,
        config=config,
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    euro = generate_delta_signal(
        "EURUSD",
        _quiet_trigger(),
        frames,
        config=config,
        symbol_spec={"pip_size": 0.0001, "typical_spread_pips": 1.0},
        spread_pips=1.0,
    )

    assert gold.signal_type == SignalType.BUY
    assert euro.signal_type == SignalType.BUY
    gold_stop = gold.entry_price - gold.stop_loss
    euro_stop = euro.entry_price - euro.stop_loss
    assert gold_stop == pytest.approx(1.6)
    assert euro_stop == pytest.approx(3.0)
    assert euro.risk_reward_ratio >= 2.0
    assert gold.risk_reward_ratio == pytest.approx(1.8)


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


def _stamp_style(frame: pd.DataFrame, *, adx: float, stoch: float, rsi: float) -> pd.DataFrame:
    out = frame.copy()
    out["adx"] = adx
    out["stoch_k"] = stoch
    out["rsi"] = rsi
    out["ema_20"] = out["close"] - 2.0
    return out


def test_operator_style_fade_sells_an_extended_spike() -> None:
    frames = [
        _stamp_style(_higher("up"), adx=40.0, stoch=70.0, rsi=72.0),
        _stamp_style(_higher("up"), adx=38.0, stoch=86.0, rsi=78.0),
    ]
    signal = generate_delta_signal(
        "XAUUSD",
        _quiet_trigger(),
        frames,
        config={
            "operator_style": {"enabled": True, "min_adx": 25.0},
            "stop_atr_source": "htf",
            "max_atr_close_ratio": 0.01,
            "reward_risk_ratio": 1.5,
        },
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.SELL
    assert "fade_extension" in signal.reason
    assert signal.risk_reward_ratio >= 1.5


def test_operator_style_adx_filter_does_not_block_a_normal_gold_sweep() -> None:
    frames = [
        _stamp_style(_higher("up"), adx=40.0, stoch=50.0, rsi=58.0),
        _stamp_style(_higher("up"), adx=36.0, stoch=48.0, rsi=56.0),
    ]
    signal = generate_delta_signal(
        "XAUUSD",
        _quiet_trigger(),
        frames,
        config={
            "operator_style": {
                "enabled": True,
                "min_adx": 25.0,
                "allowed_setups": [
                    "sweep_reclaim",
                    "breakout_retest",
                    "fade_extension",
                    "htf_pullback",
                ],
            },
            "stop_atr_source": "htf",
            "max_atr_close_ratio": 0.01,
        },
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.BUY
    assert "sweep_reclaim" in signal.reason


def test_eur_fade_only_rejects_the_failed_sweep_path() -> None:
    frames = [
        _stamp_style(_higher("up"), adx=30.0, stoch=50.0, rsi=55.0),
        _stamp_style(_higher("up"), adx=28.0, stoch=48.0, rsi=54.0),
    ]
    signal = generate_delta_signal(
        "EURUSD",
        _quiet_trigger(),
        frames,
        config={
            "allowed_symbols": ["EURUSD"],
            "operator_style": {
                "enabled": True,
                "min_adx": 20.0,
                "allowed_setups": ["fade_extension", "htf_pullback"],
            },
            "stop_atr_source": "htf",
            "max_atr_close_ratio": 0.01,
        },
        symbol_spec={"pip_size": 0.0001, "typical_spread_pips": 1.0},
        spread_pips=1.0,
    )
    assert signal.signal_type == SignalType.NONE
    assert signal.reason == "delta:no_style_setup"
