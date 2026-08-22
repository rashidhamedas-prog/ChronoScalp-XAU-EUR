from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from chronoscalp.execution.mt5_utils import (
    StaleStopsError,
    resolve_order_filling_mode,
    sanitize_mt5_comment,
    spread_points_to_pips,
    validate_stops_vs_fill_price,
)
from chronoscalp.execution.position_logic import (
    apply_breakeven_or_trailing,
    check_sl_tp_hit,
    exit_price_for_hit,
)
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


def test_validate_stops_vs_fill_price_buy_ok():
    validate_stops_vs_fill_price(
        is_buy=True, fill_price=1965.0, stop_loss=1960.0, take_profit=1972.0
    )


def test_validate_stops_vs_fill_price_buy_stale_sl_above():
    with pytest.raises(StaleStopsError):
        validate_stops_vs_fill_price(
            is_buy=True, fill_price=1964.57, stop_loss=1967.06, take_profit=1968.34
        )


def test_validate_stops_vs_fill_price_sell_ok():
    validate_stops_vs_fill_price(
        is_buy=False, fill_price=1965.0, stop_loss=1970.0, take_profit=1958.0
    )


def test_scale_volume_to_free_margin():
    """35 lots USDJPY on a $9k account must shrink (or skip), not bounce No money."""
    from chronoscalp.execution.mt5_utils import scale_volume_to_free_margin

    # Requires 10x the free margin → shrink to ~9% of requested, floored to step.
    scaled = scale_volume_to_free_margin(
        volume=35.63,
        required_margin=89_075.0,
        free_margin=9_000.0,
        volume_step=0.01,
        volume_min=0.01,
    )
    assert 0 < scaled < 35.63
    assert scaled == pytest.approx(3.23, abs=0.02)

    # Fits already → unchanged.
    assert (
        scale_volume_to_free_margin(
            volume=0.5,
            required_margin=500.0,
            free_margin=9_000.0,
            volume_step=0.01,
            volume_min=0.01,
        )
        == 0.5
    )

    # Even min volume does not fit → 0 (skip).
    assert (
        scale_volume_to_free_margin(
            volume=0.02,
            required_margin=50_000.0,
            free_margin=100.0,
            volume_step=0.01,
            volume_min=0.01,
        )
        == 0.0
    )


def test_validate_min_stop_distance_rejects_sub_pip_stops():
    """EURJPY 0.8-pip SL vs broker stops_level — MT5 would return Invalid stops."""
    from chronoscalp.execution.mt5_utils import validate_min_stop_distance

    with pytest.raises(StaleStopsError):
        validate_min_stop_distance(
            fill_price=186.19,
            stop_loss=186.1997,
            take_profit=186.1843,
            min_distance=0.03,  # 3 pips × point 0.001... broker-configured
        )
    # Wide stops pass.
    validate_min_stop_distance(
        fill_price=186.19, stop_loss=186.40, take_profit=185.90, min_distance=0.03
    )
    # min_distance 0 (broker reports none) never rejects.
    validate_min_stop_distance(
        fill_price=186.19, stop_loss=186.1997, take_profit=186.1843, min_distance=0.0
    )


def test_validate_fill_vs_signal_entry_rejects_large_slippage():
    """BTC fill 12.7 below a 25-point-SL signal = +50% realized risk — reject."""
    from chronoscalp.execution.mt5_utils import validate_fill_vs_signal_entry

    with pytest.raises(StaleStopsError):
        validate_fill_vs_signal_entry(
            fill_price=64_660.0, signal_entry=64_672.7, stop_loss=64_697.7
        )
    # Small slippage passes.
    validate_fill_vs_signal_entry(fill_price=64_670.0, signal_entry=64_672.7, stop_loss=64_697.7)


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


def test_check_sl_tp_hit_both_in_bar_is_sl_first():
    position = Position(
        ticket=3,
        symbol="XAUUSD",
        direction=SignalType.BUY,
        volume=0.1,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2010.0,
        open_time=datetime.now(tz=UTC),
    )
    hit = check_sl_tp_hit(position, bar_high=2012.0, bar_low=1988.0)
    assert hit.hit_sl is True
    assert hit.hit_tp is True
    assert hit.exit_reason() == "stop_loss"
    assert exit_price_for_hit(position, hit) == 1990.0


def test_apply_breakeven_never_widens_after_trail():
    """ATR trail locked profit past entry — classic BE must not pull SL back."""
    from chronoscalp.risk.position_sizing import RiskManager

    rm = RiskManager(
        risk_cfg={"breakeven_at_r_multiple": 1.0, "trailing_stop_atr_multiple": 1.5},
        spread_cfg={"enabled": False},
        symbols_cfg={},
        starting_equity=10_000,
    )
    position = Position(
        ticket=9,
        symbol="XAUUSD",
        direction=SignalType.BUY,
        volume=0.1,
        entry_price=2000.0,
        stop_loss=2010.0,  # already trailed into profit
        take_profit=2030.0,
        open_time=datetime.now(tz=UTC),
        breakeven_moved=False,
        initial_stop_loss=1990.0,
    )
    # Favorable move from initial R easily clears 1R, but BE at 2000 would widen.
    new_sl = apply_breakeven_or_trailing(rm, position, current_price=2020.0, atr_value=5.0)
    assert new_sl is None or new_sl > position.stop_loss
    assert rm.breakeven_stop(position, 2020.0) is None
