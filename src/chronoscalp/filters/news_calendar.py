"""High-impact news calendar countdown helpers for the news-straddle strategy.

Wraps the existing :class:`~chronoscalp.filters.news_filter.NewsFilter` event
list — no MetaTrader SDK imports. Spread-shield helpers live here so the
straddle engine stays pure.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from chronoscalp.filters.news_filter import NewsEvent, NewsFilter, _ensure_utc
from chronoscalp.logging_setup import logger


@dataclass(frozen=True)
class UpcomingNews:
    """Next high-impact event relative to ``now``."""

    event: NewsEvent
    seconds_until: float

    @property
    def title(self) -> str:
        return self.event.title

    @property
    def currency(self) -> str:
        return self.event.currency


class NewsCalendarManager:
    """Countdown + spread-shield utilities over a loaded news calendar."""

    def __init__(
        self,
        news_filter: NewsFilter,
        *,
        impact_level: str = "high",
    ) -> None:
        self.news_filter = news_filter
        self.impact_level = impact_level.strip().lower() or "high"

    @classmethod
    def from_news_filter(cls, news_filter: NewsFilter) -> NewsCalendarManager:
        return cls(news_filter)

    def _eligible_events(self, currency: str | None = None) -> list[NewsEvent]:
        events: list[NewsEvent] = []
        for event in self.news_filter.events:
            if self.impact_level == "high" and event.impact != "high":
                continue
            if currency and event.currency not in (currency, "ALL"):
                continue
            events.append(event)
        return events

    def next_event(
        self, moment: datetime | None = None, currency: str | None = None
    ) -> UpcomingNews | None:
        """Return the nearest future high-impact event (or least-past within 5m)."""
        now = _ensure_utc(moment or datetime.now(tz=UTC))
        future: list[UpcomingNews] = []
        recent_past: list[UpcomingNews] = []
        for event in self._eligible_events(currency):
            ts = _ensure_utc(event.timestamp)
            seconds = (ts - now).total_seconds()
            if seconds < -300:
                continue
            candidate = UpcomingNews(event=event, seconds_until=seconds)
            if seconds >= 0:
                future.append(candidate)
            else:
                recent_past.append(candidate)
        if future:
            return min(future, key=lambda c: c.seconds_until)
        if recent_past:
            return max(recent_past, key=lambda c: c.seconds_until)
        return None

    def is_news_event_upcoming(
        self,
        window_minutes: float = 2.0,
        moment: datetime | None = None,
        currency: str | None = None,
    ) -> tuple[bool, UpcomingNews | None]:
        """True when a high-impact release is within ``window_minutes`` ahead."""
        try:
            upcoming = self.next_event(moment, currency=currency)
            if upcoming is None:
                return False, None
            if 0 <= upcoming.seconds_until <= window_minutes * 60:
                return True, upcoming
            return False, upcoming
        except Exception as exc:  # noqa: BLE001 - never crash the trading loop
            logger.warning("[NewsCalendar] Error checking news event: {}", exc)
            return False, None

    def is_scalp_paused(
        self,
        moment: datetime,
        *,
        pause_minutes_before: float = 2.0,
        pause_seconds_after: float = 120.0,
        currency: str | None = None,
    ) -> tuple[bool, UpcomingNews | None]:
        """Pause normal scalping from T-pause until T+after around a release."""
        upcoming = self.next_event(moment, currency=currency)
        if upcoming is None:
            return False, None
        before = pause_minutes_before * 60.0
        after = pause_seconds_after
        if -after <= upcoming.seconds_until <= before:
            return True, upcoming
        return False, upcoming

    def is_straddle_placement_window(
        self,
        moment: datetime,
        *,
        place_seconds_before: float = 30.0,
        currency: str | None = None,
    ) -> tuple[bool, UpcomingNews | None]:
        """True in the [0, place_seconds_before] countdown before release."""
        upcoming = self.next_event(moment, currency=currency)
        if upcoming is None:
            return False, None
        if 0 < upcoming.seconds_until <= place_seconds_before:
            return True, upcoming
        return False, upcoming

    @staticmethod
    def is_spread_acceptable(current_spread_pips: float, max_allowed_pips: float = 2.0) -> bool:
        """Spread Guard Filter — veto when news-time spread expands too far."""
        if current_spread_pips < 0 or max_allowed_pips <= 0:
            return False
        return current_spread_pips <= max_allowed_pips

    def events_in_range(
        self,
        start: datetime,
        end: datetime,
        currency: str | None = None,
    ) -> list[NewsEvent]:
        """Events whose timestamps fall inside ``[start, end]`` (UTC)."""
        start_u = _ensure_utc(start)
        end_u = _ensure_utc(end)
        out: list[NewsEvent] = []
        for event in self._eligible_events(currency):
            ts = _ensure_utc(event.timestamp)
            if start_u <= ts <= end_u:
                out.append(event)
        return out


def build_manual_high_impact_titles(titles: Iterable[str] | None = None) -> frozenset[str]:
    """Canonical high-impact title tokens (NFP, CPI, FOMC, rate decisions)."""
    defaults = (
        "nfp",
        "nonfarm",
        "non-farm",
        "cpi",
        "fomc",
        "interest rate",
        "rate decision",
        "federal funds",
        "ecb rate",
        "boe rate",
    )
    merged = {t.lower() for t in defaults}
    if titles:
        merged.update(str(t).lower() for t in titles)
    return frozenset(merged)


def event_matches_straddle_titles(event: NewsEvent, titles: frozenset[str] | None = None) -> bool:
    """Optional title filter — empty/None titles means accept all high-impact."""
    needles = titles if titles is not None else build_manual_high_impact_titles()
    if not needles:
        return True
    hay = (event.title or "").lower()
    return any(token in hay for token in needles)


def seconds_until(event: NewsEvent, moment: datetime | None = None) -> float:
    now = _ensure_utc(moment or datetime.now(tz=UTC))
    return (_ensure_utc(event.timestamp) - now).total_seconds()


def window_bounds(
    event: NewsEvent,
    *,
    before: timedelta,
    after: timedelta,
) -> tuple[datetime, datetime]:
    ts = _ensure_utc(event.timestamp)
    return ts - before, ts + after
