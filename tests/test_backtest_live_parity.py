"""Backtest/live parity for stop management and entry guards.

The live loop polls every few seconds; the backtest used to touch each bar
once, at its close. That single difference let a stop the bot had already
trailed sit unreachable until the next bar, so the engine reported far fewer
stop-outs than the VPS produced on the same geometry. These tests pin the
intrabar path model that closes the gap, and the guards main.py applies at
entry that the engine now applies too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from chronoscalp.backtest.engine import (
    LIVE_ONLY_GATES,
    PARITY_GATES,
    BacktestResult,
    _intrabar_path,
    _manage_open_position,
    _stop_check_segments,
    _volatility_allows,
)
from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.utils.types import Position, Signal, SignalType, Timeframe

SYMBOLS_CFG = {
    "XAUUSD": {
        "pip_size": 0.1,
        "pip_value_per_lot": 1.0,
        "typical_spread_pips": 2.0,
        "min_lot": 0.01,
        "max_lot": 10.0,
        "lot_step": 0.01,
        "contract_size": 100.0,
    }
}

RISK_CFG = {
    "max_risk_per_trade_pct": 1.0,
    "min_reward_risk_ratio": 1.5,
    "max_daily_loss_pct": 3.0,
    "breakeven_at_r_multiple": 1.0,
    "trailing_stop_atr_multiple": 1.5,
    "trailing_start_r_multiple": 1.0,
}


def _bar(open_: float, high: float, low: float, close: float, atr: float = 1.0) -> pd.Series:
    return pd.Series({"open": open_, "high": high, "low": low, "close": close, "atr": atr})


def _risk_manager(**overrides) -> RiskManager:
    cfg = {**RISK_CFG, **overrides}
    return RiskManager(
        risk_cfg=cfg, spread_cfg={"enabled": False}, symbols_cfg=SYMBOLS_CFG, starting_equity=10_000
    )


def _long_position(broker: PaperBroker, entry: float, sl: float, tp: float) -> Position:
    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
    )
    position = broker.place_order(signal, volume=0.10, fill_price=entry)
    # place_order applies slippage; pin the geometry the test reasons about.
    position.entry_price = entry
    position.stop_loss = sl
    position.initial_stop_loss = sl
    position.take_profit = tp
    return position


def test_intrabar_path_is_adverse_first_for_both_bar_directions():
    up = _intrabar_path(_bar(100.0, 102.0, 99.0, 101.0))
    assert up == (100.0, 99.0, 102.0, 101.0)
    down = _intrabar_path(_bar(100.0, 102.0, 99.0, 98.5))
    assert down == (100.0, 102.0, 99.0, 98.5)


def test_intrabar_segments_split_the_bar_into_monotonic_legs():
    segments = _stop_check_segments(_bar(100.0, 102.0, 99.0, 101.0), intrabar=True)
    assert segments == (
        (100.0, 99.0, 99.0),
        (102.0, 99.0, 102.0),
        (102.0, 101.0, 101.0),
    )


def test_legacy_mode_is_one_leg_spanning_the_bar_with_close_as_trail_point():
    segments = _stop_check_segments(_bar(100.0, 102.0, 99.0, 101.0), intrabar=False)
    assert segments == ((102.0, 99.0, 101.0),)


def test_stop_trailed_on_the_high_is_hit_by_the_pullback_in_the_same_bar():
    """The core live divergence: trail up, then get taken out before the close.

    Long from 100 with a 1.0 stop. The bar runs to 104 (4R) and closes back at
    101.0. Live trails the stop up during the run and the pullback takes it;
    the engine must now do the same.
    """
    broker = PaperBroker(symbols_cfg=SYMBOLS_CFG, starting_balance=10_000, slippage_pips=0.0)
    risk = _risk_manager()
    position = _long_position(broker, entry=100.0, sl=99.0, tp=110.0)
    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000)
    t = pd.Timestamp("2026-01-05 08:01", tz="UTC")

    remaining = _manage_open_position(
        broker,
        risk,
        position.ticket,
        _bar(100.0, 104.0, 99.5, 101.0, atr=1.0),
        t,
        result,
        intrabar=True,
    )

    assert remaining is None, "trailed stop must be reachable inside the same bar"
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    # Trailed to high - 1.5*ATR = 104 - 1.5 = 102.5, so the exit locks profit.
    assert trade.exit_price == pytest.approx(102.5)
    assert trade.pnl > 0


def test_bar_close_model_misses_that_same_stop_out():
    """Documents the gap that was closed — legacy mode leaves the trade open."""
    broker = PaperBroker(symbols_cfg=SYMBOLS_CFG, starting_balance=10_000, slippage_pips=0.0)
    risk = _risk_manager()
    position = _long_position(broker, entry=100.0, sl=99.0, tp=110.0)
    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000)
    t = pd.Timestamp("2026-01-05 08:01", tz="UTC")

    remaining = _manage_open_position(
        broker,
        risk,
        position.ticket,
        _bar(100.0, 104.0, 99.5, 101.0, atr=1.0),
        t,
        result,
        intrabar=False,
    )

    assert remaining == position.ticket
    assert result.trades == []
    # Legacy trails from the close (101), not the high (104), so the stop is
    # both looser and only effective from the next bar.
    assert broker._positions[position.ticket].stop_loss == pytest.approx(100.0)


def test_intrabar_trailing_advances_from_the_favourable_extreme():
    """A bar that never retraces past the trail keeps the position open."""
    broker = PaperBroker(symbols_cfg=SYMBOLS_CFG, starting_balance=10_000, slippage_pips=0.0)
    risk = _risk_manager()
    position = _long_position(broker, entry=100.0, sl=99.0, tp=110.0)
    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000)
    t = pd.Timestamp("2026-01-05 08:01", tz="UTC")

    remaining = _manage_open_position(
        broker,
        risk,
        position.ticket,
        _bar(100.0, 103.0, 99.8, 102.9, atr=0.5),
        t,
        result,
        intrabar=True,
    )

    assert remaining == position.ticket
    # Trailed off the high (103 - 0.75), not the close (102.9 - 0.75).
    assert broker._positions[position.ticket].stop_loss == pytest.approx(102.25)


def test_adverse_leg_still_stops_out_before_any_trailing():
    """A bar that hits the stop first must not be rescued by a later high."""
    broker = PaperBroker(symbols_cfg=SYMBOLS_CFG, starting_balance=10_000, slippage_pips=0.0)
    risk = _risk_manager()
    position = _long_position(broker, entry=100.0, sl=99.0, tp=110.0)
    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000)
    t = pd.Timestamp("2026-01-05 08:01", tz="UTC")

    remaining = _manage_open_position(
        broker,
        risk,
        position.ticket,
        _bar(100.0, 105.0, 98.0, 104.0, atr=1.0),
        t,
        result,
        intrabar=True,
    )

    assert remaining is None
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_price == pytest.approx(99.0)


def test_short_position_trails_down_and_is_taken_by_the_bounce():
    broker = PaperBroker(symbols_cfg=SYMBOLS_CFG, starting_balance=10_000, slippage_pips=0.0)
    risk = _risk_manager()
    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.SELL,
        timestamp=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        entry_price=100.0,
        stop_loss=101.0,
        take_profit=90.0,
    )
    position = broker.place_order(signal, volume=0.10, fill_price=100.0)
    position.entry_price = 100.0
    position.stop_loss = 101.0
    position.initial_stop_loss = 101.0
    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000)

    remaining = _manage_open_position(
        broker,
        risk,
        position.ticket,
        # Down bar: pops to 100.4 first, sells off to 96, closes back at 99.
        _bar(100.0, 100.4, 96.0, 99.0, atr=1.0),
        pd.Timestamp("2026-01-05 08:01", tz="UTC"),
        result,
        intrabar=True,
    )

    assert remaining is None
    trade = result.trades[0]
    assert trade.exit_reason == "stop_loss"
    # Trailed to low + 1.5*ATR = 96 + 1.5 = 97.5.
    assert trade.exit_price == pytest.approx(97.5)
    assert trade.pnl > 0


def test_closed_trade_is_reported_to_the_three_strikes_callback():
    broker = PaperBroker(symbols_cfg=SYMBOLS_CFG, starting_balance=10_000, slippage_pips=0.0)
    risk = _risk_manager()
    position = _long_position(broker, entry=100.0, sl=99.0, tp=110.0)
    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000)
    seen: list[float] = []

    _manage_open_position(
        broker,
        risk,
        position.ticket,
        _bar(100.0, 100.2, 98.0, 98.5, atr=1.0),
        pd.Timestamp("2026-01-05 08:01", tz="UTC"),
        result,
        intrabar=True,
        on_trade_closed=lambda trade: seen.append(trade.pnl),
    )

    assert len(seen) == 1
    assert seen[0] < 0


def test_daily_loss_limit_uses_bar_time_not_wall_clock():
    """Without ``at`` the tracker rolls its day over against the real calendar.

    Historical P&L recorded at bar time then looks like "yesterday" and the
    limit never fires, which is why daily_loss_limit was listed as live-only.
    """
    risk = _risk_manager()
    bar_time = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    risk.daily_tracker.record_trade_pnl(-400.0, at=bar_time)

    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=bar_time,
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=102.0,
    )

    assert risk.validate_signal(signal, 1.0, at=bar_time + timedelta(minutes=5)) is False
    # A later bar on the next day is allowed again.
    assert risk.validate_signal(signal, 1.0, at=bar_time + timedelta(days=1)) is True


def test_volatility_guard_blocks_a_dead_regime_and_allows_a_normal_one():
    def frame(atr: float, close: float) -> pd.DataFrame:
        return pd.DataFrame(
            {"atr": [atr], "close": [close]},
            index=pd.DatetimeIndex(["2026-01-05 08:00"], tz="UTC"),
        )

    cfg = {"min_atr_close_ratio": 0.00005, "max_atr_close_ratio": 0.05}
    dead = {Timeframe.M5: frame(0.001, 2000.0)}
    normal = {Timeframe.M5: frame(2.0, 2000.0)}

    assert _volatility_allows(dead, Timeframe.M5, Timeframe.M1, cfg) is False
    assert _volatility_allows(normal, Timeframe.M5, Timeframe.M1, cfg) is True


def test_volatility_guard_falls_back_when_configured_frame_is_missing():
    cfg = {"min_atr_close_ratio": 0.00005, "max_atr_close_ratio": 0.05}
    only_trigger = {
        Timeframe.M1: pd.DataFrame(
            {"atr": [2.0], "close": [2000.0]},
            index=pd.DatetimeIndex(["2026-01-05 08:00"], tz="UTC"),
        )
    }
    assert _volatility_allows(only_trigger, Timeframe.M15, Timeframe.M1, cfg) is True
    assert _volatility_allows({}, Timeframe.M5, Timeframe.M1, cfg) is True


def test_parity_gates_are_disjoint_from_never_modelled_gates():
    """A gate must be claimed as modelled or not modelled, never both."""
    assert not set(LIVE_ONLY_GATES) & set(PARITY_GATES)


def test_summary_states_which_stop_model_produced_the_numbers():
    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000)
    # A hand-built result has modelled nothing — the default must say so.
    assert set(result.summary()["live_only_gates_not_modelled"]) == set(LIVE_ONLY_GATES) | set(
        PARITY_GATES
    )
    assert result.summary()["stop_management"] == "bar_close"
