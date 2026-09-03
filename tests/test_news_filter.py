from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from chronoscalp.filters.news_filter import NewsEvent, NewsFilter


def test_is_blackout_naive_event_vs_aware_moment():
    """Finnhub often returns naive timestamps; main loop uses UTC-aware now."""
    naive_ev = datetime(2026, 7, 23, 12, 0, 0)  # no tzinfo
    filt = NewsFilter(
        events=[
            NewsEvent(timestamp=naive_ev, currency="USD", impact="high", title="CPI"),
        ],
        blackout_before=timedelta(minutes=30),
        blackout_after=timedelta(minutes=30),
    )
    moment = datetime(2026, 7, 23, 12, 10, tzinfo=UTC)
    assert filt.is_blackout(moment, currency="USD") is True
    assert filt.is_blackout(moment, currency="EUR") is False


def test_is_blackout_respects_currency_filter():
    event_time = datetime(2026, 7, 15, 13, 30, tzinfo=UTC)
    events = [
        NewsEvent(timestamp=event_time, currency="EUR", impact="high", title="ECB rate"),
    ]
    filt = NewsFilter(
        events=events,
        blackout_before=timedelta(minutes=30),
        blackout_after=timedelta(minutes=30),
    )
    moment = event_time
    assert filt.is_blackout(moment, currency="EUR") is True
    assert filt.is_blackout(moment, currency="USD") is False


def test_finnhub_failure_returns_none():
    import requests

    with patch("requests.get", side_effect=requests.RequestException("network down")):
        from chronoscalp.filters.news_filter import _fetch_events_from_api

        assert _fetch_events_from_api("key") is None


def test_manual_calendar_includes_nfp_4_sep_2026():
    from pathlib import Path

    from chronoscalp.filters.news_filter import _load_manual_events

    events = _load_manual_events(Path("config/news_events.yaml"))
    titles = {e.title.lower() for e in events}
    stamps = {e.timestamp.isoformat() for e in events}
    assert any("nfp" in t or "payroll" in t for t in titles)
    assert any(s.startswith("2026-09-04T12:30:00") for s in stamps)


def test_from_config_keeps_yaml_when_finnhub_403(tmp_path):
    yaml_path = tmp_path / "news_events.yaml"
    yaml_path.write_text(
        '- timestamp: "2026-09-04T12:30:00"\n'
        "  currency: USD\n"
        "  impact: high\n"
        "  title: Non-Farm Payrolls (NFP)\n",
        encoding="utf-8",
    )
    fake = type("R", (), {"status_code": 403, "text": '{"error":"denied"}'})()
    with patch("requests.get", return_value=fake):
        filt = NewsFilter.from_config(
            {"blackout_minutes_before": 30, "blackout_minutes_after": 30},
            yaml_path,
            api_key="dummy",
        )
    assert len(filt.events) == 1
    assert "nfp" in filt.events[0].title.lower()
