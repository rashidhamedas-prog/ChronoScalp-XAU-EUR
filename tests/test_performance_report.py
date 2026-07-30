"""Tests for Persian performance HTML report builder."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from chronoscalp.orchestration.trade_journal import ClosedTradeRecord
from chronoscalp.reports.performance_report import (
    analyze_performance,
    filter_trades_since,
    render_persian_html,
    strategy_label_fa,
)


def _sample_trades() -> list[ClosedTradeRecord]:
    return [
        ClosedTradeRecord(
            ticket=1,
            symbol="XAUUSD_o",
            direction="buy",
            volume=0.1,
            entry_price=2400.0,
            exit_price=2410.0,
            open_time="2026-07-20T08:30:00+00:00",
            close_time="2026-07-20T09:00:00+00:00",
            pnl=80.0,
            r_multiple=1.5,
            strategy="ultra_scalp",
        ),
        ClosedTradeRecord(
            ticket=2,
            symbol="EURUSD_o",
            direction="sell",
            volume=0.2,
            entry_price=1.1,
            exit_price=1.105,
            open_time="2026-07-20T13:45:00+00:00",
            close_time="2026-07-20T14:30:00+00:00",
            pnl=-30.0,
            r_multiple=-0.6,
            strategy="institutional",
        ),
        ClosedTradeRecord(
            ticket=3,
            symbol="XAUUSD_o",
            direction="buy",
            volume=0.1,
            entry_price=2410.0,
            exit_price=2425.0,
            open_time="2026-07-21T09:15:00+00:00",
            close_time="2026-07-21T10:00:00+00:00",
            pnl=120.0,
            r_multiple=2.0,
            strategy="ultra_scalp",
        ),
        ClosedTradeRecord(
            ticket=4,
            symbol="BTCUSD",
            direction="buy",
            volume=0.01,
            entry_price=65000.0,
            exit_price=64800.0,
            open_time="2026-07-15T02:00:00+00:00",
            close_time="2026-07-15T03:00:00+00:00",
            pnl=-50.0,
            strategy="liquidity_volume",
        ),
    ]


def test_filter_trades_since() -> None:
    trades = _sample_trades()
    since = datetime(2026, 7, 20, tzinfo=UTC)
    filtered = filter_trades_since(trades, since)
    assert len(filtered) == 3
    assert all(t.ticket != 4 for t in filtered)


def test_analyze_performance_strategy_breakdown() -> None:
    trades = filter_trades_since(_sample_trades(), datetime(2026, 7, 20, tzinfo=UTC))
    report = analyze_performance(trades, account_login="55625500", mode="live")
    assert report.total_closed == 3
    assert report.wins == 2
    assert report.losses == 1
    by = {s.strategy: s for s in report.strategies}
    assert by["ultra_scalp"].trades == 2
    assert by["ultra_scalp"].wins == 2
    assert report.top_winning_symbol == "XAUUSD_o"
    assert report.top_winning_symbol_wins == 2
    assert report.best_strategy_win_rate == "ultra_scalp"
    assert report.best_win_hour is not None


def test_render_persian_html_contains_farsi() -> None:
    report = analyze_performance(_sample_trades(), account_login="55625500")
    html = render_persian_html(report)
    assert "گزارش عملکرد" in html
    assert strategy_label_fa("ultra_scalp") in html
    assert "۵۵۶۲۵۵۰۰" in html
    assert "<html lang=\"fa\" dir=\"rtl\">" in html


def test_write_report_from_journal(tmp_path: Path) -> None:
    from chronoscalp.orchestration.trade_journal import TradeJournal
    from chronoscalp.reports.performance_report import write_persian_html_report

    journal = TradeJournal(tmp_path / "trade_journal_live.json", mode="live")
    for trade in _sample_trades():
        journal.closed_trades.append(trade)
    journal.save()

    out = tmp_path / "report.html"
    report = write_persian_html_report(
        out,
        journal_path=journal.path,
        account_login="55625500",
        since=datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "ChronoScalp" in text
    assert report.total_closed == 3
