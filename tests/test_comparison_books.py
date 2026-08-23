from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.orchestration.comparison_books import ComparisonBooks, r_normalized_stats
from chronoscalp.utils.types import SignalType, TradeResult


def test_comparison_books_have_independent_equity():
    symbols = {
        "XAUUSD": {
            "pip_size": 0.01,
            "pip_value_per_lot": 1.0,
            "typical_spread_pips": 20,
            "min_lot": 0.01,
            "lot_step": 0.01,
            "max_lot": 10,
        }
    }
    books = ComparisonBooks(symbols_cfg=symbols, starting_balance=10_000, slippage_pips=0.5)
    a = books.broker_for("delta")
    b = books.broker_for("liquidity_volume")
    assert a is not b
    assert a.get_balance() == 10_000
    a.balance = 9_500
    assert b.get_balance() == 10_000


def test_r_normalized_stats_rank_by_r_not_dollars():
    trades = [
        TradeResult(
            symbol="XAUUSD",
            direction=SignalType.BUY,
            entry_price=2000,
            exit_price=2010,
            volume=0.1,
            open_time=datetime(2026, 7, 13, tzinfo=UTC),
            close_time=datetime(2026, 7, 13, 1, tzinfo=UTC),
            pnl=10.0,
            r_multiple=2.0,
        ),
        TradeResult(
            symbol="XAUUSD",
            direction=SignalType.BUY,
            entry_price=2000,
            exit_price=1990,
            volume=1.0,
            open_time=datetime(2026, 7, 13, tzinfo=UTC),
            close_time=datetime(2026, 7, 13, 1, tzinfo=UTC),
            pnl=-50.0,
            r_multiple=-1.0,
        ),
    ]
    stats = r_normalized_stats(trades)
    assert stats["expectancy_r"] == 0.5
    assert stats["trades"] == 2
