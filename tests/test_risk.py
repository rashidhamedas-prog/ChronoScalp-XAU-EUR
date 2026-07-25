from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chronoscalp.risk.position_sizing import (
    DailyRiskTracker,
    RiskManager,
    calculate_position_size,
    kelly_fraction,
    passes_reward_risk_filter,
    passes_spread_filter,
    resolve_active_risk_pct,
    round_to_lot_step,
)
from chronoscalp.utils.types import Signal, SignalType, Timeframe

XAUUSD_SPEC = {
    "pip_size": 0.01,
    "contract_size": 100,
    "min_lot": 0.01,
    "lot_step": 0.01,
    "max_lot": 50,
    "pip_value_per_lot": 1.0,
}


def test_round_to_lot_step_respects_bounds():
    assert round_to_lot_step(0.003, 0.01, 50, 0.01) == 0.01
    assert round_to_lot_step(100, 0.01, 50, 0.01) == 50
    assert round_to_lot_step(1.234, 0.01, 50, 0.01) == pytest.approx(1.23)


def test_calculate_position_size_risks_expected_amount():
    equity = 10_000
    risk_pct = 1.0
    entry = 2000.0
    stop = 1990.0  # 1000 pips at pip_size 0.01
    volume = calculate_position_size(equity, risk_pct, entry, stop, XAUUSD_SPEC)

    # risk_amount = 100; stop distance in price = 10; pip distance = 1000
    # lot ≈ risk / (pips * pip_value) = 100 / 1000 = 0.1
    assert volume == pytest.approx(0.1)


def test_kelly_fraction_hard_capped():
    assert kelly_fraction(0.9, 2.0, cap_pct=1.0) <= 1.0
    assert kelly_fraction(0.4, 1.0, cap_pct=1.0) == 0.0


def test_passes_spread_filter():
    assert passes_spread_filter(1.0, 2.0)
    assert not passes_spread_filter(3.0, 2.0)


def test_passes_reward_risk_filter():
    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(tz=UTC),
        entry_price=2000,
        stop_loss=1990,
        take_profit=2020,
        timeframe=Timeframe.M1,
    )
    assert signal.risk_reward_ratio == pytest.approx(2.0)
    assert passes_reward_risk_filter(signal, min_ratio=1.5)
    assert not passes_reward_risk_filter(signal, min_ratio=3.0)


def test_daily_loss_limit_triggers_and_resets_next_day():
    tracker = DailyRiskTracker(max_daily_loss_pct=3.0, starting_equity=10_000)
    now = datetime.now(tz=UTC)

    assert not tracker.daily_loss_limit_hit(now)
    tracker.record_trade_pnl(-350, at=now)  # 3.5% loss > 3% limit
    assert tracker.daily_loss_limit_hit(now)

    next_day = now + timedelta(days=1)
    assert not tracker.daily_loss_limit_hit(next_day)


def test_daily_tracker_manual_reset():
    tracker = DailyRiskTracker(max_daily_loss_pct=3.0, starting_equity=10_000)
    now = datetime.now(tz=UTC)
    tracker.record_trade_pnl(-400, at=now)
    assert tracker.daily_loss_limit_hit(now)
    tracker.reset()
    assert not tracker.daily_loss_limit_hit(now)


def test_resolve_active_risk_pct_default_and_presets():
    assert resolve_active_risk_pct({"active_risk_per_trade_pct": 0.5}) == 0.5
    assert resolve_active_risk_pct({"active_risk_per_trade_pct": 1.0}) == 1.0
    # 1.5% requested but hard-capped at 1%
    assert (
        resolve_active_risk_pct({"active_risk_per_trade_pct": 1.5, "max_risk_per_trade_pct": 1.0})
        == 1.0
    )


def test_risk_manager_accepts_scalp_one_to_one_override():
    rm = RiskManager(
        risk_cfg={
            "min_reward_risk_ratio": 1.5,
            "max_daily_loss_pct": 99,
            "active_risk_per_trade_pct": 1.0,
        },
        spread_cfg={"enabled": False},
        symbols_cfg={"XAUUSD": XAUUSD_SPEC},
        starting_equity=10_000,
    )
    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(tz=UTC),
        entry_price=2000,
        stop_loss=1990,
        take_profit=2010,  # exactly 1:1
        timeframe=Timeframe.S15,
        reason="ultra_scalp,trend=bullish",
    )
    assert signal.risk_reward_ratio == pytest.approx(1.0)
    assert not rm.validate_signal(signal, current_spread_pips=1.0)
    assert rm.validate_signal(signal, current_spread_pips=1.0, min_reward_risk_ratio=1.0)


def test_btcusd_position_size_positive():
    spec = {
        "pip_size": 1.0,
        "contract_size": 1,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "max_lot": 10,
        "pip_value_per_lot": 1.0,
    }
    volume = calculate_position_size(10_000, 1.0, 65000.0, 64000.0, spec)
    assert volume >= 0.01
    assert volume <= 10
