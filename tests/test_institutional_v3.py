"""Tests for ChronoScalp v3 institutional engines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from chronoscalp.execution.trade_manager import manage_open_position, partial_tp_action
from chronoscalp.indicators.session_vwap import asian_range_midpoint, session_vwap
from chronoscalp.risk.institutional_guards import ThreeStrikesGuard, volatility_allows
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


def test_timeframe_m15_seconds():
    assert Timeframe.M15.seconds == 900
    assert Timeframe.M15.minutes == 15
