"""Closed set of news-straddle skip reasons (countable, no silent drops)."""

from __future__ import annotations

from enum import StrEnum


class NewsSkipReason(StrEnum):
    DISABLED = "disabled"
    NO_CALENDAR_EVENT = "no_calendar_event"
    STALE_CALENDAR = "stale_calendar"
    CURRENCY_MISMATCH = "currency_mismatch"
    TITLE_SKIP = "title_skip"
    OUTSIDE_PLACEMENT_WINDOW = "outside_placement_window"
    OUTSIDE_SESSION = "outside_session"
    SPREAD_BLOCK = "spread_block"
    ALREADY_OPEN_SAME_STRATEGY = "already_open_same_strategy"
    PORTFOLIO_HEAT = "portfolio_heat"
    MAX_CONCURRENT = "max_concurrent"
    BROKER_UNSUPPORTED = "broker_unsupported"
    RISK_REJECTED = "risk_rejected"


NEWS_SKIP_REASONS: frozenset[str] = frozenset(item.value for item in NewsSkipReason)


def idle_calendar_skip(
    *,
    events_loaded: bool,
    unfiltered_upcoming: bool,
    currency: str | None,
) -> NewsSkipReason:
    """Map an idle calendar lookup onto the closed skip-reason set."""
    if not events_loaded:
        return NewsSkipReason.STALE_CALENDAR
    if unfiltered_upcoming and currency:
        return NewsSkipReason.CURRENCY_MISMATCH
    return NewsSkipReason.NO_CALENDAR_EVENT
