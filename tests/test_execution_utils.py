from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from chronoscalp.execution.mt5_utils import (
    resolve_order_filling_mode,
    sanitize_mt5_comment,
    spread_points_to_pips,
)
from chronoscalp.execution.position_logic import check_sl_tp_hit, exit_price_for_hit
from chronoscalp.utils.types import Position, SignalType


def test_resolve_order_filling_mode_without_symbol_filling_attrs():
    """Older MetaTrader5 builds expose ORDER_FILLING_* but not SYMBOL_FILLING_*."""
    mt5_mod = SimpleNamespace(
        ORDER_FILLING_FOK=0,
        ORDER_FILLING_IOC=1,
        ORDER_FILLING_RETURN=2,
        symbol_info=lambda _s: SimpleNamespace(filling_mode=2),  # IOC bit
    )
    with (
        patch("chronoscalp.execution.mt5_utils._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": mt5_mod}),
    ):
        assert resolve_order_filling_mode("BTCUSD") == 1


def test_sanitize_mt5_comment_ascii_and_length():
    assert sanitize_mt5_comment("chronoscalp:sweep+MSS/rvol") == "chronoscalp_sweep_MSS_rvol"[:31]
    assert len(sanitize_mt5_comment("x" * 100)) == 31
    assert sanitize_mt5_comment("سیگنال تست") == "ChronoScalp"
    assert sanitize_mt5_comment("") == "ChronoScalp"


def test_resolve_order_filling_mode_fok_bit():
    mt5_mod = SimpleNamespace(
        ORDER_FILLING_FOK=0,
        ORDER_FILLING_IOC=1,
        ORDER_FILLING_RETURN=2,
        SYMBOL_FILLING_FOK=1,
        SYMBOL_FILLING_IOC=2,
        SYMBOL_FILLING_RETURN=4,
        symbol_info=lambda _s: SimpleNamespace(filling_mode=1),
    )
    with (
        patch("chronoscalp.execution.mt5_utils._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": mt5_mod}),
    ):
        assert resolve_order_filling_mode("XAUUSD") == 0


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
        open_time=datetime.now(tz=UTC),
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
        open_time=datetime.now(tz=UTC),
    )
    hit = check_sl_tp_hit(position, bar_high=1.1005, bar_low=1.0965)
    assert hit.hit_tp is True
    assert exit_price_for_hit(position, hit) == pytest.approx(1.0970)
