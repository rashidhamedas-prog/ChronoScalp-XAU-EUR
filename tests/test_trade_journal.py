"""Tests for the live/paper trade journal and dashboard stats."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from chronoscalp.orchestration.trade_journal import (
    ClosedTradeRecord,
    TradeJournal,
    compute_trading_stats,
    load_journal_snapshot,
    sum_closed_pnl_today,
)
from chronoscalp.utils.types import Position, SignalType, TradeResult


def test_compute_trading_stats_basic() -> None:
    closed = [
        ClosedTradeRecord(
            ticket=1,
            symbol="EURUSD",
            direction="buy",
            volume=0.1,
            entry_price=1.1,
            exit_price=1.11,
            open_time="2026-07-17T10:00:00+00:00",
            close_time="2026-07-17T11:00:00+00:00",
            pnl=50.0,
            r_multiple=1.5,
        ),
        ClosedTradeRecord(
            ticket=2,
            symbol="EURUSD",
            direction="sell",
            volume=0.1,
            entry_price=1.1,
            exit_price=1.105,
            open_time="2026-07-17T12:00:00+00:00",
            close_time="2026-07-17T13:00:00+00:00",
            pnl=-20.0,
            r_multiple=-0.5,
        ),
    ]
    # Pin "today" to the fixture close date so the assertion is not flaky.
    as_of = datetime(2026, 7, 17, 23, 0, tzinfo=UTC)
    stats = compute_trading_stats(closed, [], reference_equity=10_000, as_of=as_of)
    assert stats.closed_trades == 2
    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.net_pnl == 30.0
    assert stats.win_rate_pct == 50.0
    assert stats.profit_factor == 2.5
    assert stats.avg_pnl == 15.0
    assert stats.avg_r_multiple == 0.5
    assert stats.today_trades == 2
    assert stats.today_pnl == 30.0


def test_sum_closed_pnl_today_seeds_daily_tracker() -> None:
    """Restarting the bot must not forget today's realized losses (3% stop)."""
    closed = [
        ClosedTradeRecord(
            ticket=1,
            symbol="BTCUSD",
            direction="sell",
            volume=3.76,
            entry_price=64660.0,
            exit_price=64698.0,
            open_time="2026-07-27T15:03:50+00:00",
            close_time="2026-07-27T15:04:49+00:00",
            pnl=-434.59,
            r_multiple=-11.8,
        ),
        ClosedTradeRecord(
            ticket=2,
            symbol="ETHUSD",
            direction="buy",
            volume=1.98,
            entry_price=1968.99,
            exit_price=1968.18,
            open_time="2026-07-25T10:50:02+00:00",
            close_time="2026-07-25T10:50:18+00:00",  # older day — excluded
            pnl=-1.6,
            r_multiple=-1.0,
        ),
    ]
    now = datetime(2026, 7, 27, 16, 0, tzinfo=UTC)
    assert sum_closed_pnl_today(closed, now=now) == -434.59
    assert sum_closed_pnl_today(closed, now=datetime(2026, 7, 28, 1, 0, tzinfo=UTC)) == 0.0


def test_today_stats_ignore_older_closes() -> None:
    closed = [
        ClosedTradeRecord(
            ticket=1,
            symbol="EURUSD",
            direction="buy",
            volume=0.1,
            entry_price=1.1,
            exit_price=1.11,
            open_time="2026-07-16T10:00:00+00:00",
            close_time="2026-07-16T11:00:00+00:00",
            pnl=10.0,
            r_multiple=0.5,
        ),
        ClosedTradeRecord(
            ticket=2,
            symbol="EURUSD",
            direction="buy",
            volume=0.1,
            entry_price=1.1,
            exit_price=1.12,
            open_time="2026-07-17T10:00:00+00:00",
            close_time="2026-07-17T11:00:00+00:00",
            pnl=20.0,
            r_multiple=1.0,
        ),
    ]
    stats = compute_trading_stats(
        closed,
        [],
        as_of=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
    )
    assert stats.closed_trades == 2
    assert stats.today_trades == 1
    assert stats.today_pnl == 20.0


def test_journal_open_close_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "trade_journal_paper.json"
    journal = TradeJournal(path, mode="paper")
    journal.load()

    position = Position(
        ticket=42,
        symbol="XAUUSD",
        direction=SignalType.BUY,
        volume=0.05,
        entry_price=2300.0,
        stop_loss=2290.0,
        take_profit=2320.0,
        open_time=datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
    )
    journal.record_open(position)
    assert 42 in journal.open_trades

    trade = TradeResult(
        symbol="XAUUSD",
        direction=SignalType.BUY,
        entry_price=2300.0,
        exit_price=2310.0,
        volume=0.05,
        open_time=position.open_time,
        close_time=datetime(2026, 7, 17, 9, 0, tzinfo=UTC),
        pnl=100.0,
        r_multiple=1.0,
        exit_reason="take_profit",
    )
    journal.record_close(trade, ticket=42)

    reloaded = TradeJournal(path, mode="paper")
    reloaded.load()
    assert reloaded.open_trades == {}
    assert len(reloaded.closed_trades) == 1
    assert reloaded.closed_trades[0].pnl == 100.0

    snap = load_journal_snapshot(tmp_path, "paper", reference_equity=10_000)
    assert snap.stats.closed_trades == 1
    assert snap.stats.net_pnl == 100.0
    assert snap.stats.open_trades == 0


def test_external_close_uses_open_record(tmp_path: Path) -> None:
    journal = TradeJournal(tmp_path / "j.json", mode="live")
    journal.record_open(
        Position(
            ticket=7,
            symbol="EURUSD",
            direction=SignalType.SELL,
            volume=0.2,
            entry_price=1.08,
            stop_loss=1.085,
            take_profit=1.07,
            open_time=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        )
    )
    closed = journal.record_external_close(
        7, "EURUSD", 25.5, at=datetime(2026, 7, 17, 11, 0, tzinfo=UTC)
    )
    assert closed is not None
    assert closed.pnl == 25.5
    assert closed.direction == "sell"
    assert 7 not in journal.open_trades


def test_sync_open_from_broker_drops_ghosts(tmp_path: Path) -> None:
    journal = TradeJournal(tmp_path / "j.json", mode="live")
    journal.record_open(
        Position(
            ticket=100,
            symbol="BTCUSD",
            direction=SignalType.BUY,
            volume=0.1,
            entry_price=60000.0,
            stop_loss=59000.0,
            take_profit=61000.0,
            open_time=datetime(2026, 7, 25, 10, 0, tzinfo=UTC),
        )
    )
    journal.record_open(
        Position(
            ticket=200,
            symbol="ETHUSD",
            direction=SignalType.SELL,
            volume=0.1,
            entry_price=2000.0,
            stop_loss=2050.0,
            take_profit=1900.0,
            open_time=datetime(2026, 7, 25, 10, 0, tzinfo=UTC),
        )
    )
    # Broker only still has ticket 200
    still_open = Position(
        ticket=200,
        symbol="ETHUSD",
        direction=SignalType.SELL,
        volume=0.1,
        entry_price=2000.0,
        stop_loss=2050.0,
        take_profit=1900.0,
        open_time=datetime(2026, 7, 25, 10, 0, tzinfo=UTC),
    )
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    journal.sync_open_from_broker([still_open], ghost_grace_seconds=90.0, now=now)
    assert 100 not in journal.open_trades
    assert 200 in journal.open_trades
    # Empty broker clears all ghosts (past grace)
    journal.sync_open_from_broker([], ghost_grace_seconds=90.0, now=now)
    assert journal.open_trades == {}


def test_sync_open_from_broker_keeps_recent_within_grace(tmp_path: Path) -> None:
    journal = TradeJournal(tmp_path / "j.json", mode="live")
    opened = datetime(2026, 7, 27, 13, 50, 2, tzinfo=UTC)
    journal.record_open(
        Position(
            ticket=306425496,
            symbol="ETHUSD",
            direction=SignalType.BUY,
            volume=1.98,
            entry_price=1968.99,
            stop_loss=1968.34,
            take_profit=1970.0,
            open_time=opened,
        )
    )
    # 26s later broker briefly reports empty — keep within 90s grace
    journal.sync_open_from_broker(
        [],
        ghost_grace_seconds=90.0,
        now=datetime(2026, 7, 27, 13, 50, 28, tzinfo=UTC),
    )
    assert 306425496 in journal.open_trades
    # After grace, drop
    journal.sync_open_from_broker(
        [],
        ghost_grace_seconds=90.0,
        now=datetime(2026, 7, 27, 13, 52, 0, tzinfo=UTC),
    )
    assert 306425496 not in journal.open_trades
