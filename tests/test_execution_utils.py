from __future__ import annotations

from datetime import datetime, timezone

import pytest

from chronoscalp.execution.mt5_utils import spread_points_to_pips
from chronoscalp.execution.position_logic import check_sl_tp_hit, exit_price_for_hit
from chronoscalp.utils.types import Position, SignalType


def test_spread_points_to_pips_eurusd_five_digit():
    # 20 points * 0.00001 point / 0.0001 pip = 2.0 pips
    assert spread_points_to_pips(20, point=0.00001, pip_size=0.0001) == pytest.approx(2.0)


def test_spread_points_to_pips_xauusd():
    # 35 points * 0.01 point / 0.01 pip = 35 pips
    assert spread_points_to_pips(35, point=0.01, pip_size=0.01) == pytest.approx(35.0)


def test_check_sl_tp_hit_buy_stop_loss():
    position = Position(
        ticket=1,
        symbol="XAUUSD",
        direction=SignalType.BUY,
        volume=0.1,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2025.0,
        open_time=datetime.now(tz=timezone.utc),
    )
    hit = check_sl_tp_hit(position, bar_high=2005.0, bar_low=1989.0)
    assert hit.hit_sl is True
    assert hit.hit_tp is False
    assert exit_price_for_hit(position, hit) == 1990.0


def test_check_sl_tp_hit_sell_take_profit():
    position = Position(
        ticket=2,
        symbol="EURUSD",
        direction=SignalType.SELL,
        volume=0.1,
        entry_price=1.1000,
        stop_loss=1.1010,
        take_profit=1.0970,
        open_time=datetime.now(tz=timezone.utc),
    )
    hit = check_sl_tp_hit(position, bar_high=1.1005, bar_low=1.0965)
    assert hit.hit_tp is True
    assert exit_price_for_hit(position, hit) == pytest.approx(1.0970)
