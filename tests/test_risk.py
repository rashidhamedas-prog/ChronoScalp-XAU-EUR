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


BTC_LITEFINANCE_SPEC = {
    "pip_size": 1.0,
    "contract_size": 1,
    "min_lot": 0.01,
    "lot_step": 0.01,
    "max_lot": 10,
    "pip_value_per_lot": 1.0,
    "typical_spread_pips": 20,
    "commission_pct_notional": 0.0012,  # ≈$78/lot round-turn at 65k
}


def test_commission_included_in_position_size():
    """Real BTC trade lost $434 on a $94 (1%) risk budget because the $78/lot
    commission was ignored — sizing must keep price-risk + commission ≤ 1%."""
    from chronoscalp.risk.position_sizing import commission_per_lot

    equity, entry, stop = 9_426.47, 64_660.0, 64_685.0  # 25-point SL
    comm = commission_per_lot(BTC_LITEFINANCE_SPEC, entry)
    assert comm == pytest.approx(77.6, abs=1.0)

    volume = calculate_position_size(equity, 1.0, entry, stop, BTC_LITEFINANCE_SPEC)
    worst_case_loss = volume * (abs(entry - stop) + comm / 1.0)
    assert worst_case_loss <= equity * 0.011  # 1% + lot-step rounding slack
    # Old behavior gave 3.76 lots → $434 realized loss (4.6%).
    assert volume < 1.5


def test_validate_signal_rejects_commission_uneconomic_scalp():
    """A 25-point BTC target cannot clear a $78/lot round-turn commission."""
    rm = RiskManager(
        risk_cfg={
            "min_reward_risk_ratio": 1.5,
            "max_daily_loss_pct": 99,
            "active_risk_per_trade_pct": 1.0,
        },
        spread_cfg={"enabled": False},
        symbols_cfg={"BTCUSD": BTC_LITEFINANCE_SPEC, "XAUUSD": XAUUSD_SPEC},
        starting_equity=10_000,
    )
    doomed = Signal(
        symbol="BTCUSD",
        signal_type=SignalType.SELL,
        timestamp=datetime.now(tz=UTC),
        entry_price=64_685.0,
        stop_loss=64_710.0,
        take_profit=64_660.0,  # 1:1, 25 points
        timeframe=Timeframe.S15,
    )
    assert not rm.validate_signal(doomed, current_spread_pips=1.0, min_reward_risk_ratio=1.0)

    # Commission-free gold with the same geometry still passes.
    gold = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(tz=UTC),
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2010.0,
        timeframe=Timeframe.S15,
    )
    assert rm.validate_signal(gold, current_spread_pips=1.0, min_reward_risk_ratio=1.0)


def test_validate_signal_rejects_spread_burning_scalp():
    """0.77-pip EURJPY target vs 0.3-pip spread = negative expectancy — reject."""
    eurjpy_spec = {
        "pip_size": 0.01,
        "contract_size": 100000,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "max_lot": 100,
        "pip_value_per_lot": 6.5,
    }
    rm = RiskManager(
        risk_cfg={
            "min_reward_risk_ratio": 1.5,
            "max_daily_loss_pct": 99,
            "active_risk_per_trade_pct": 1.0,
        },
        spread_cfg={"enabled": False},
        symbols_cfg={"EURJPY_o": eurjpy_spec},
        starting_equity=10_000,
    )
    micro = Signal(
        symbol="EURJPY_o",
        signal_type=SignalType.SELL,
        timestamp=datetime.now(tz=UTC),
        entry_price=186.192,
        stop_loss=186.1997,  # 0.77 pips
        take_profit=186.1843,
        timeframe=Timeframe.S15,
    )
    assert not rm.validate_signal(micro, current_spread_pips=0.3, min_reward_risk_ratio=1.0)

    # Sub-spread stop distance is floored out even when live spread is ~0.
    floored_spec = dict(eurjpy_spec, typical_spread_pips=1.5)
    rm_floor = RiskManager(
        risk_cfg={
            "min_reward_risk_ratio": 1.5,
            "max_daily_loss_pct": 99,
            "active_risk_per_trade_pct": 1.0,
        },
        spread_cfg={"enabled": False},
        symbols_cfg={"USDJPY_o": floored_spec},
        starting_equity=10_000,
    )
    sub_pip = Signal(
        symbol="USDJPY_o",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(tz=UTC),
        entry_price=163.706,
        stop_loss=163.70212,  # 0.39 pips — the real "No money" 35-lot trade
        take_profit=163.70988,
        timeframe=Timeframe.S15,
    )
    assert not rm_floor.validate_signal(
        sub_pip, current_spread_pips=0.01, min_reward_risk_ratio=1.0
    )

    # A 5-pip stop / 8-pip target clears the 0.3-pip spread comfortably.
    healthy = Signal(
        symbol="EURJPY_o",
        signal_type=SignalType.SELL,
        timestamp=datetime.now(tz=UTC),
        entry_price=186.192,
        stop_loss=186.242,
        take_profit=186.112,
        timeframe=Timeframe.S15,
    )
    assert rm.validate_signal(healthy, current_spread_pips=0.3, min_reward_risk_ratio=1.0)

def test_fit_economic_scalp_widens_eurjpy_sub_spread_stop():
    """S15 ATR stops under 2x typical spread must widen, then clear net R:R."""
    from chronoscalp.risk.position_sizing import fit_economic_scalp_geometry

    eurjpy = {
        "pip_size": 0.01,
        "pip_value_per_lot": 6.5,
        "typical_spread_pips": 2.0,
        "contract_size": 100000,
    }
    # ATR 0.92 pips with 1.0x stop was the live reject (0.92 < 4.0 floor).
    geometry = fit_economic_scalp_geometry(
        entry=186.192,
        is_buy=False,
        atr=0.0092,
        atr_stop_multiple=1.0,
        atr_target_multiple=1.0,
        symbol_spec=eurjpy,
        spread_pips=0.3,
        min_reward_risk_ratio=1.0,
        net_rr_floor=1.0,
    )
    assert geometry is not None
    stop, tp = geometry
    sl_pips = abs(stop - 186.192) / 0.01
    assert sl_pips >= 4.0 - 1e-9
    rm = RiskManager(
        risk_cfg={
            "min_reward_risk_ratio": 1.5,
            "max_daily_loss_pct": 99,
            "active_risk_per_trade_pct": 1.0,
        },
        spread_cfg={"enabled": False},
        symbols_cfg={"EURJPY_o": eurjpy},
        starting_equity=10_000,
    )
    signal = Signal(
        symbol="EURJPY_o",
        signal_type=SignalType.SELL,
        timestamp=datetime.now(tz=UTC),
        entry_price=186.192,
        stop_loss=stop,
        take_profit=tp,
        timeframe=Timeframe.S15,
        reason="ultra_scalp_v3",
    )
    assert rm.validate_signal(signal, current_spread_pips=0.3, min_reward_risk_ratio=1.0)


def test_fit_economic_scalp_clears_btc_commission():
    """1:1 micro ATR BTC scalp must expand TP past LiteFinance commission."""
    from chronoscalp.risk.position_sizing import fit_economic_scalp_geometry

    entry = 65_000.0
    geometry = fit_economic_scalp_geometry(
        entry=entry,
        is_buy=True,
        atr=20.0,
        atr_stop_multiple=1.0,
        atr_target_multiple=1.0,
        symbol_spec=BTC_LITEFINANCE_SPEC,
        spread_pips=20.0,
        min_reward_risk_ratio=1.0,
        net_rr_floor=1.0,
    )
    assert geometry is not None
    stop, tp = geometry
    assert abs(entry - stop) >= 40.0  # 2x typical_spread_pips=20
    rm = RiskManager(
        risk_cfg={
            "min_reward_risk_ratio": 1.5,
            "max_daily_loss_pct": 99,
            "active_risk_per_trade_pct": 1.0,
        },
        spread_cfg={"enabled": False},
        symbols_cfg={"BTCUSD": BTC_LITEFINANCE_SPEC},
        starting_equity=10_000,
    )
    signal = Signal(
        symbol="BTCUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(tz=UTC),
        entry_price=entry,
        stop_loss=stop,
        take_profit=tp,
        timeframe=Timeframe.S15,
        reason="ultra_scalp_v3",
    )
    assert rm.validate_signal(signal, current_spread_pips=20.0, min_reward_risk_ratio=1.0)


def test_fit_economic_scalp_returns_none_when_caps_too_tight():
    from chronoscalp.risk.position_sizing import fit_economic_scalp_geometry

    # Tiny ATR + huge commission cannot fit inside max_target_atr_multiple=2.
    assert (
        fit_economic_scalp_geometry(
            entry=65_000.0,
            is_buy=True,
            atr=5.0,
            atr_stop_multiple=1.0,
            atr_target_multiple=1.0,
            symbol_spec=BTC_LITEFINANCE_SPEC,
            spread_pips=20.0,
            max_stop_atr_multiple=2.0,
            max_target_atr_multiple=2.0,
        )
        is None
    )
