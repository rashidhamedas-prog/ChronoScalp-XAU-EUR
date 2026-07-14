from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from chronoscalp.filters.news_filter import NewsEvent, NewsFilter


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
