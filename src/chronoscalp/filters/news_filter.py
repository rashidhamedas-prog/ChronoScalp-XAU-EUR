"""High-impact economic news blackout filter.

Two event sources, in priority order:
1. A live economic-calendar API, if `news_api_key` is configured (Phase 3
   extension point — no specific provider is wired in yet; implement
   `_fetch_events_from_api()` for your chosen provider, e.g. FinancialModelingPrep,
   TradingEconomics, or Finnhub).
2. A manual event list in config/news_events.yaml (git-tracked, zero external
   dependency, works out of the box) — maintain this list manually if you
   don't want an API dependency.

Like SessionFilter, this is veto-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from chronoscalp.logging_setup import logger


@dataclass(frozen=True)
class NewsEvent:
    timestamp: datetime
    currency: str
    impact: str  # "high" | "medium" | "low"
    title: str


class NewsFilter:
    def __init__(
        self,
        events: list[NewsEvent],
        blackout_before: timedelta,
        blackout_after: timedelta,
        high_impact_only: bool = True,
        enabled: bool = True,
    ) -> None:
        self.events = events
        self.blackout_before = blackout_before
        self.blackout_after = blackout_after
        self.high_impact_only = high_impact_only
        self.enabled = enabled

    @classmethod
    def from_config(
        cls, news_cfg: dict[str, Any], events_yaml_path: str | Path, api_key: str = ""
    ) -> NewsFilter:
        events = _load_manual_events(events_yaml_path)
        if api_key:
            try:
                events = _fetch_events_from_api(api_key) or events
            except Exception as exc:  # noqa: BLE001 - never let a news-API outage crash trading
                logger.warning("News API fetch failed, falling back to manual events file: {}", exc)

        return cls(
            events=events,
            blackout_before=timedelta(minutes=int(news_cfg.get("blackout_minutes_before", 30))),
            blackout_after=timedelta(minutes=int(news_cfg.get("blackout_minutes_after", 30))),
            high_impact_only=bool(news_cfg.get("high_impact_only", True)),
            enabled=bool(news_cfg.get("enabled", True)),
        )

    def is_blackout(self, moment: datetime, currency: str | None = None) -> bool:
        if not self.enabled:
            return False
        for event in self.events:
            if self.high_impact_only and event.impact != "high":
                continue
            if currency and event.currency not in (currency, "ALL"):
                continue
            window_start = event.timestamp - self.blackout_before
            window_end = event.timestamp + self.blackout_after
            if window_start <= moment <= window_end:
                return True
        return False


def _load_manual_events(path: str | Path) -> list[NewsEvent]:
    path = Path(path)
    if not path.exists():
        logger.warning("No manual news events file at {} — news filter has no events loaded", path)
        return []
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    events = []
    for item in raw:
        events.append(
            NewsEvent(
                timestamp=datetime.fromisoformat(item["timestamp"]),
                currency=item.get("currency", "ALL"),
                impact=item.get("impact", "high"),
                title=item.get("title", ""),
            )
        )
    return events


def _fetch_events_from_api(api_key: str) -> list[NewsEvent] | None:
    """Extension point: implement against your chosen economic-calendar
    provider. Intentionally not wired to a specific vendor — pick one that
    fits your budget/reliability needs and implement the HTTP call + mapping
    to NewsEvent here. Must return None (not raise) on any failure so the
    caller falls back to the manual events file.
    """
    logger.debug("_fetch_events_from_api() is a stub — using manual events file instead")
    return None
