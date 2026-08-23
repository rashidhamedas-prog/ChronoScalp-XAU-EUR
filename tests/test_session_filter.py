from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.filters.session_filter import SessionFilter, SessionWindow


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 11, hour, minute, tzinfo=UTC)


def test_session_window_contains_normal_range():
    window = SessionWindow(name="london", start=_dt(8).time(), end=_dt(11).time())
    assert window.contains(_dt(9, 30))
    assert not window.contains(_dt(12))
    assert not window.contains(_dt(7, 59))


def test_session_window_contains_overnight_range():
    window = SessionWindow(name="sydney", start=_dt(22).time(), end=_dt(2).time())
    assert window.contains(_dt(23))
    assert window.contains(_dt(1))
    assert not window.contains(_dt(12))


def test_session_filter_from_config():
    cfg = {
        "windows": {
            "london": {"start": "08:00", "end": "11:00"},
            "new_york": {"start": "13:30", "end": "16:30"},
        },
        "trade_outside_sessions": False,
        "market_timezones": {"london": "UTC", "new_york": "UTC"},
    }
    session_filter = SessionFilter.from_config(cfg)

    assert session_filter.is_within_session(_dt(9, 0))
    assert session_filter.is_within_session(_dt(14, 0))
    assert not session_filter.is_within_session(_dt(20, 0))
    assert session_filter.active_session_name(_dt(9, 0)) == "london"


def test_session_filter_trade_outside_sessions_true_always_allows():
    cfg = {
        "windows": {"london": {"start": "08:00", "end": "11:00"}},
        "trade_outside_sessions": True,
    }
    session_filter = SessionFilter.from_config(cfg)
    assert session_filter.is_within_session(_dt(20, 0))


def test_session_filter_always_on_symbol_bypasses_windows():
    cfg = {
        "windows": {"london": {"start": "08:00", "end": "11:00"}},
        "trade_outside_sessions": False,
        "always_on_symbols": ["BTCUSD"],
    }
    session_filter = SessionFilter.from_config(cfg)
    assert not session_filter.is_within_session(_dt(20, 0))
    assert session_filter.is_within_session(_dt(20, 0), symbol="BTCUSD")
    assert not session_filter.is_within_session(_dt(20, 0), symbol="EURUSD")


def test_trading_hours_mode_london_ny_blocks_outside_all_symbols():
    cfg = {
        "trading_hours_mode": "london_ny",
        "windows": {
            "london": {"start": "08:00", "end": "11:00"},
            "new_york": {"start": "13:30", "end": "16:30"},
        },
        "always_on_symbols": ["BTCUSD"],
        "market_timezones": {"london": "UTC", "new_york": "UTC"},
    }
    session_filter = SessionFilter.from_config(cfg)
    assert session_filter.is_within_session(_dt(9, 0), symbol="BTCUSD")
    assert session_filter.is_within_session(_dt(14, 0), symbol="EURUSD")
    assert not session_filter.is_within_session(_dt(20, 0), symbol="BTCUSD")
    assert not session_filter.is_within_session(_dt(20, 0), symbol="EURUSD")


def test_trading_hours_mode_always_on_24h():
    cfg = {
        "trading_hours_mode": "always_on_24h",
        "windows": {"london": {"start": "08:00", "end": "11:00"}},
    }
    session_filter = SessionFilter.from_config(cfg)
    assert session_filter.is_within_session(_dt(3, 0), symbol="EURUSD")
    assert session_filter.active_session_name(_dt(3, 0)) == "always_on_24h"


def test_session_windows_follow_dst():
    cfg = {
        "windows": {
            "london": {"start": "08:00", "end": "11:00"},
            "new_york": {"start": "08:30", "end": "11:30"},
        },
        "market_timezones": {
            "london": "Europe/London",
            "new_york": "America/New_York",
        },
        "trading_hours_mode": "london_ny",
    }
    session_filter = SessionFilter.from_config(cfg)
    # 11 Jul 2026 is BST/EDT: 07:00 UTC = 08:00 London (in); winter GMT would be out.
    july = datetime(2026, 7, 11, 7, 0, tzinfo=UTC)
    january = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
    assert session_filter.is_within_session(july)
    assert not session_filter.is_within_session(january)
    # NY local 10:00 in July is 14:00 UTC (EDT).
    assert session_filter.is_within_session(datetime(2026, 7, 11, 14, 0, tzinfo=UTC))
    assert (
        session_filter.active_session_name(datetime(2026, 7, 11, 14, 0, tzinfo=UTC)) == "new_york"
    )


def test_invalid_timezone_fails_closed():
    cfg = {
        "windows": {"london": {"start": "08:00", "end": "11:00"}},
        "market_timezones": {"london": "Not/AZone"},
        "trading_hours_mode": "london_ny",
    }
    session_filter = SessionFilter.from_config(cfg)
    assert session_filter.timezone_ok is False
    assert not session_filter.is_within_session(_dt(9, 0))
