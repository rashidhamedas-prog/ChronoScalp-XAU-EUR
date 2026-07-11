from __future__ import annotations

from datetime import datetime, timezone

from chronoscalp.filters.session_filter import SessionFilter, SessionWindow


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 11, hour, minute, tzinfo=timezone.utc)


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
    }
    session_filter = SessionFilter.from_config(cfg)

    assert session_filter.is_within_session(_dt(9, 0))
    assert session_filter.is_within_session(_dt(14, 0))
    assert not session_filter.is_within_session(_dt(20, 0))
    assert session_filter.active_session_name(_dt(9, 0)) == "london"


def test_session_filter_trade_outside_sessions_true_always_allows():
    cfg = {"windows": {"london": {"start": "08:00", "end": "11:00"}}, "trade_outside_sessions": True}
    session_filter = SessionFilter.from_config(cfg)
    assert session_filter.is_within_session(_dt(20, 0))
