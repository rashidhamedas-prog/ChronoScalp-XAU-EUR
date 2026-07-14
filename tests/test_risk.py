from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chronoscalp.risk.position_sizing import (
    DailyRiskTracker,
    calculate_position_size,
    kelly_fraction,
    passes_reward_risk_filter,
    passes_spread_filter,
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

    risk_amount = equity * (risk_pct / 100)
    price_risk_pips = abs(entry - stop) / XAUUSD_SPEC["pip_size"]
    implied_loss = price_risk_pips * XAUUSD_SPEC["pip_value_per_lot"] * volume
    assert implied_loss == pytest.approx(risk_amount, rel=0.05)


def test_calculate_position_size_rejects_zero_risk():
    with pytest.raises(ValueError):
        calculate_position_size(10_000, 1.0, 2000.0, 2000.0, XAUUSD_SPEC)


def test_kelly_fraction_is_capped_at_max_risk():
    # Even a very favorable win_rate/R:R must never exceed cap_pct.
    result = kelly_fraction(win_rate=0.9, reward_risk_ratio=5.0, cap_pct=1.0)
    assert result <= 1.0


def test_kelly_fraction_negative_edge_is_zero():
    result = kelly_fraction(win_rate=0.3, reward_risk_ratio=1.0, cap_pct=2.0)
    assert result == 0.0


def test_passes_spread_filter():
    assert passes_spread_filter(current_spread_pips=10, max_allowed_pips=35)
    assert not passes_spread_filter(current_spread_pips=40, max_allowed_pips=35)


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
