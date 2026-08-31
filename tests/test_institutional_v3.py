"""Tests for ChronoScalp v3 institutional engines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from chronoscalp.execution.trade_manager import manage_open_position, partial_tp_action
from chronoscalp.indicators.session_vwap import asian_range_midpoint, session_vwap
from chronoscalp.risk.institutional_guards import (
    SpreadMovingAverageGuard,
    ThreeStrikesGuard,
    correlation_blocks,
    correlation_guard_enabled,
    effective_max_concurrent_positions,
    volatility_allows,
)
from chronoscalp.strategy.trend_filter import institutional_bias
from chronoscalp.utils.types import Position, SignalType, Timeframe, TrendDirection


def _session_frame(n: int = 120, bias: str = "up") -> pd.DataFrame:
    start = pd.Timestamp("2026-07-25 00:00:00", tz="UTC")
    idx = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    base = np.linspace(100, 110, n) if bias == "up" else np.linspace(110, 100, n)
    close = base
    df = pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "tick_volume": np.full(n, 10.0),
        },
        index=idx,
    )
    return df


def test_session_vwap_and_asian_mid_exist():
    df = _session_frame()
    assert session_vwap(df) is not None
    assert asian_range_midpoint(df) is not None


def test_institutional_bias_bullish_when_above_vwap_and_asia_mid():
    df = _session_frame(bias="up")
    # Force last close clearly above session means
    df.iloc[-1, df.columns.get_loc("close")] = float(df["close"].max()) + 5
    df.iloc[-1, df.columns.get_loc("high")] = float(df.iloc[-1]["close"]) + 0.1
    assert institutional_bias(df) in (TrendDirection.BULLISH, TrendDirection.NEUTRAL)


def test_three_strikes_pauses_symbol():
    guard = ThreeStrikesGuard(max_losses=3, pause_hours=12)
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    guard.record_result("BTCUSD", -10, at=now)
    guard.record_result("BTCUSD", -10, at=now)
    assert not guard.is_paused("BTCUSD", at=now)
    guard.record_result("BTCUSD", -10, at=now)
    assert guard.is_paused("BTCUSD", at=now)
    guard.record_result("BTCUSD", 5, at=now + timedelta(hours=13))
    assert not guard.is_paused("BTCUSD", at=now + timedelta(hours=13))


def test_spread_guard_passes_through_until_enough_samples():
    guard = SpreadMovingAverageGuard(window=100, multiplier=2.5)
    assert guard.baseline("EURUSD") is None
    assert guard.allows("EURUSD", 5.0)
    for _ in range(4):
        guard.observe("EURUSD", 0.1)
    assert guard.allows("EURUSD", 5.0)


def test_spread_guard_median_baseline_ignores_spike_skew():
    """Regression: a mean baseline let a few spikes block normal spreads.

    Live EURUSD samples sit near 0.10-0.14 pips with occasional news spikes.
    Those spikes drag the mean above the typical quote, and the old
    ``mean * 1.2`` test then rejected ordinary 0.30-pip spreads.
    """
    guard = SpreadMovingAverageGuard(window=100, multiplier=2.5)
    for _ in range(95):
        guard.observe("EURUSD", 0.12)
    for _ in range(5):
        guard.observe("EURUSD", 8.0)

    assert guard.baseline("EURUSD") == pytest.approx(0.12)
    # A normal quote is accepted even though it is well above the mean (0.51).
    assert guard.allows("EURUSD", 0.28)
    # A genuine blow-out is still rejected.
    assert not guard.allows("EURUSD", 1.5)


def test_spread_guard_still_blocks_outliers_on_a_wide_symbol():
    guard = SpreadMovingAverageGuard(window=20, multiplier=2.5)
    for _ in range(20):
        guard.observe("XAUUSD", 12.0)
    assert guard.allows("XAUUSD", 28.0)
    assert not guard.allows("XAUUSD", 35.0)


def test_spread_guard_gold_floor_accepts_typical_live_quote():
    """Live 2026-08-31: gold printed 13 against a quiet median of 4-5.

    That is a normal AUSCommercial-Demo gold spread, not an outlier. Floor
    the baseline at 12 so 13 passes while 40 still fails.
    """
    guard = SpreadMovingAverageGuard(
        window=20,
        multiplier=2.5,
        symbol_overrides={"XAUUSD": {"min_baseline_pips": 12.0, "multiplier": 2.5}},
    )
    for _ in range(20):
        guard.observe("XAUUSD", 4.0)
    assert guard.allows("XAUUSD", 13.0)
    assert not guard.allows("XAUUSD", 40.0)


def test_volatility_allows_bounds():
    assert volatility_allows(1.0, 1000.0, min_ratio=0.0005, max_ratio=0.02)
    assert not volatility_allows(0.1, 1000.0, min_ratio=0.0005, max_ratio=0.02)
    assert not volatility_allows(50.0, 1000.0, min_ratio=0.0005, max_ratio=0.02)


def test_volatility_decision_reasons():
    from chronoscalp.risk.institutional_guards import volatility_decision

    ok, reason, ratio = volatility_decision(1.0, 1000.0, min_ratio=0.0005, max_ratio=0.02)
    assert ok and reason == "ok" and ratio is not None
    ok, reason, ratio = volatility_decision(0.1, 1000.0, min_ratio=0.0005, max_ratio=0.02)
    assert not ok and reason == "low"
    ok, reason, ratio = volatility_decision(50.0, 1000.0, min_ratio=0.0005, max_ratio=0.02)
    assert not ok and reason == "high"
    ok, reason, ratio = volatility_decision(float("nan"), 1000.0)
    assert not ok and reason == "invalid" and ratio is None


def test_volatility_defaults_allow_m5_fx_and_crypto():
    """Defaults must allow typical M5 ATR/close for FX + crypto (not S15)."""
    # EURUSD M5 ~3.5 pips, BTC M5 quiet, ETH M5 normal
    assert volatility_allows(0.00035, 1.08)
    assert volatility_allows(100.0, 118_000.0)
    assert volatility_allows(12.0, 3500.0)
    # S15-scale FX ratio must not be the regime input; still reject dead flat
    assert not volatility_allows(0.00001, 1.08)


def test_partial_tp_at_one_point_two_r():
    pos = Position(
        ticket=1,
        symbol="EURUSD",
        direction=SignalType.BUY,
        volume=1.0,
        entry_price=1.1000,
        stop_loss=1.0900,
        take_profit=1.1300,
        open_time=datetime(2026, 7, 25, tzinfo=UTC),
        initial_volume=1.0,
        initial_stop_loss=1.0900,
    )
    # 1.2R = +0.012
    action = partial_tp_action(pos, 1.1120, r_trigger=1.2, spread_price=0.0001)
    assert action is not None
    assert abs(action.close_volume - 0.5) < 1e-9
    assert action.new_stop_loss >= pos.entry_price


def test_manage_open_uses_partial_before_chandelier():
    pos = Position(
        ticket=2,
        symbol="EURUSD",
        direction=SignalType.BUY,
        volume=1.0,
        entry_price=1.1000,
        stop_loss=1.0900,
        take_profit=1.1300,
        open_time=datetime(2026, 7, 25, tzinfo=UTC),
        initial_volume=1.0,
        initial_stop_loss=1.0900,
    )
    idx = pd.date_range("2026-07-25", periods=30, freq="min", tz="UTC")
    close = np.linspace(1.10, 1.112, 30)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.001,
            "low": close - 0.001,
            "close": close,
            "atr": np.full(30, 0.002),
        },
        index=idx,
    )
    action = manage_open_position(pos, 1.1120, df, spread_price=0.0001)
    assert action.partial is not None


def test_correlation_blocks_high_abs_corr():
    idx = pd.date_range("2026-07-25", periods=30, freq="5min", tz="UTC")
    a = pd.Series(np.linspace(1.0, 1.3, 30), index=idx)
    b = pd.Series(np.linspace(2.0, 2.6, 30), index=idx)  # perfectly correlated
    open_pos = [
        Position(
            ticket=1,
            symbol="EURUSD_o",
            direction=SignalType.BUY,
            volume=1.0,
            entry_price=1.1,
            stop_loss=1.0,
            take_profit=1.2,
            open_time=datetime(2026, 7, 25, tzinfo=UTC),
        )
    ]
    assert correlation_blocks(
        "XAUUSD_o",
        a,
        open_pos,
        {"XAUUSD_o": a, "EURUSD_o": b},
        period=20,
        max_abs_corr=0.80,
    )
    # Uncorrelated noise should not block
    rng = np.random.default_rng(0)
    noise = pd.Series(rng.normal(size=30).cumsum(), index=idx)
    assert not correlation_blocks(
        "BTCUSD",
        noise,
        open_pos,
        {"BTCUSD": noise, "EURUSD_o": b},
        period=20,
        max_abs_corr=0.99,
    )


def test_independent_symbol_entries_raises_concurrent_and_disables_corr_by_default():
    risk = {
        "max_concurrent_positions": 2,
        "independent_symbol_entries": True,
        "correlation": {},
    }
    assert effective_max_concurrent_positions(risk, n_symbols=5) == 5
    assert correlation_guard_enabled(risk) is False
    # Explicit re-enable still honored
    risk["correlation"] = {"enabled": True}
    assert correlation_guard_enabled(risk) is True
    # Legacy mode keeps prior defaults
    legacy = {"max_concurrent_positions": 3, "independent_symbol_entries": False}
    assert effective_max_concurrent_positions(legacy, n_symbols=5) == 3
    assert correlation_guard_enabled(legacy) is True


def test_timeframe_m15_seconds():
    assert Timeframe.M15.seconds == 900
    assert Timeframe.M15.minutes == 15
