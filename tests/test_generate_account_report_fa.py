"""Tests for Persian account performance report helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.reporting.account_report_fa import (
    _fa_num,
    _fa_pct,
    build_summary,
    enrich_trades,
)


def test_fa_num_uses_persian_digits() -> None:
    assert _fa_num(1234.5, 1) == "۱,۲۳۴.۵"
    assert _fa_pct(42.5) == "۴۲.۵٪"


def test_enrich_trades_infers_ultra_scalp_from_s15_signal() -> None:
    opened = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    closed = [
        {
            "ticket": 1,
            "symbol": "XAUUSD",
            "direction": "buy",
            "volume": 0.5,
            "pnl": 10.0,
            "strategy": "unknown",
            "reason": "",
            "exit_reason": "external",
            "open_time": opened.isoformat(),
            "close_time": opened.replace(minute=1).isoformat(),
        }
    ]
    signals = [("XAUUSD", "S15", opened, "buy")]
    rows, dropped = enrich_trades(closed, signals)
    assert dropped == 0
    assert len(rows) == 1
    assert rows[0]["strategy"] == "ultra_scalp"
    assert rows[0]["symbol"] == "XAUUSD"


def test_build_summary_symbol_win_leader() -> None:
    rows = [
        {
            "symbol": "XAUUSD",
            "strategy": "ultra_scalp",
            "pnl": 100.0,
            "win": True,
            "loss": False,
            "volume": 1.0,
            "local_hour": 12,
            "local_date": "2026-07-30",
            "open_time": "2026-07-30T09:00:00+00:00",
        },
        {
            "symbol": "XAUUSD",
            "strategy": "ultra_scalp",
            "pnl": -20.0,
            "win": False,
            "loss": True,
            "volume": 1.0,
            "local_hour": 12,
            "local_date": "2026-07-30",
            "open_time": "2026-07-30T09:05:00+00:00",
        },
        {
            "symbol": "BTCUSD",
            "strategy": "ultra_scalp",
            "pnl": -5.0,
            "win": False,
            "loss": True,
            "volume": 0.1,
            "local_hour": 3,
            "local_date": "2026-07-30",
            "open_time": "2026-07-30T00:05:00+00:00",
        },
    ]
    summary = build_summary(rows, {"balance": 1000.0, "equity": 1000.0})
    assert summary["n"] == 3
    assert summary["wins"] == 1
    assert summary["symbol_stats"][0]["key"] == "XAUUSD"
    assert summary["symbol_stats"][0]["wins"] == 1
