"""Round-turn backtest costs and the chronological holdout split."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from chronoscalp.backtest.engine import (
    chronological_holdout_bounds,
    evaluate_chronological_holdout,
    run_backtest,
)
from chronoscalp.config import Settings
from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.utils.types import Signal, SignalType, Timeframe


def test_round_turn_costs_reduce_a_winning_fill() -> None:
    spec = {
        "XAUUSD": {
            "pip_size": 0.01,
            "pip_value_per_lot": 1.0,
            "typical_spread_pips": 20.0,
            "contract_size": 100,
        }
    }
    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2020.0,
        timeframe=Timeframe.M1,
        reason="test",
        confidence=1.0,
    )
    plain = PaperBroker(spec, slippage_pips=0.5)
    costly = PaperBroker(
        spec,
        slippage_pips=0.5,
        charge_round_turn_costs=True,
        commission_per_lot_fallback=7.0,
    )
    plain_pos = plain.place_order(signal, 1.0)
    cost_pos = costly.place_order(signal, 1.0)
    plain_trade = plain.close_position(plain_pos.ticket, exit_price=2010.0, reason="test")
    cost_trade = costly.close_position(cost_pos.ticket, exit_price=2010.0, reason="test")
    assert cost_pos.entry_price > plain_pos.entry_price
    assert cost_trade.exit_price < plain_trade.exit_price
    assert cost_trade.pnl < plain_trade.pnl - 7.0


def test_holdout_windows_do_not_share_a_bar() -> None:
    index = pd.date_range("2026-01-05", periods=10, freq="min", tz="UTC")
    start, dev_end, hold_start, end = chronological_holdout_bounds(index, 0.30)
    assert start == index[0]
    assert end == index[-1]
    assert dev_end < hold_start
    assert hold_start == index[7]


def test_single_backtest_reports_cost_model_without_blending_holdout() -> None:
    settings = Settings()
    index = pd.date_range("2026-01-05 08:00", periods=80, freq="min", tz="UTC")
    close = pd.Series(range(80), index=index, dtype=float) + 2000.0
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
        },
        index=index,
    )
    enriched = enrich_with_smc(enrich_with_indicators(frame))
    data = {Timeframe.M1: enriched, Timeframe.M5: enriched, Timeframe.M10: enriched}
    result = run_backtest(
        symbol="XAUUSD",
        data_by_timeframe=data,
        higher_timeframes=[Timeframe.M10, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        settings=settings,
    )
    costs = result.summary()["execution_costs"]
    assert costs["charge_round_turn_costs"] is True
    assert costs["holdout_applied_in_single_run"] is False
    assert costs["commission_per_lot_fallback"] == 0.0

    split = evaluate_chronological_holdout(
        symbol="XAUUSD",
        data_by_timeframe=data,
        higher_timeframes=[Timeframe.M10, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        settings=settings,
        holdout_fraction=0.25,
    )
    assert split["development_end"] < split["holdout_start"]
    assert "win_rate_pct" not in split
    assert "total_trades" in split["development"]
    assert "total_trades" in split["holdout"]
