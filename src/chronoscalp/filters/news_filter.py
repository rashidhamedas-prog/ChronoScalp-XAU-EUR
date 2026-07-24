"""High-impact economic news blackout filter.

Two event sources, in priority order:
1. A live economic-calendar API, if `news_api_key` is configured (Phase 3
   extension point — Finnhub economic calendar is wired via
   ``_fetch_events_from_api()``).
2. A manual event list in config/news_events.yaml (git-tracked, zero external
   dependency, works out of the box) — maintain this list manually if you
   don't want an API dependency.

Like SessionFilter, this is veto-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from chronoscalp.logging_setup import logger


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize to timezone-aware UTC (naive values treated as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class NewsEvent:
    timestamp: datetime
    currency: str
    impact: str  # "high" | "medium" | "low"
    title: str


def _normalize_event(event: NewsEvent) -> NewsEvent:
    return NewsEvent(
        timestamp=_ensure_utc(event.timestamp),
        currency=event.currency,
        impact=event.impact,
        title=event.title,
    )


class NewsFilter:
    def __init__(
        self,
        events: list[NewsEvent],
        blackout_before: timedelta,
        blackout_after: timedelta,
        high_impact_only: bool = True,
        enabled: bool = True,
    ) -> None:
        self.events = [_normalize_event(e) for e in events]
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
        moment = _ensure_utc(moment)
        # #region agent log
        try:
            import json as _json
            from pathlib import Path as _P

            _log = _P(__file__).resolve().parents[3] / "debug-eb4742.log"
            _ev0 = self.events[0].timestamp if self.events else None
            with _log.open("a", encoding="utf-8") as _f:
                _f.write(
                    _json.dumps(
                        {
                            "sessionId": "eb4742",
                            "runId": "post-fix",
                            "hypothesisId": "A",
                            "location": "news_filter.py:is_blackout:entry",
                            "message": "tzinfo after normalize",
                            "data": {
                                "moment_tz": str(moment.tzinfo),
                                "moment_aware": moment.tzinfo is not None,
                                "n_events": len(self.events),
                                "event0_tz": str(_ev0.tzinfo) if _ev0 else None,
                                "event0_aware": (_ev0.tzinfo is not None) if _ev0 else None,
                                "currency": currency,
                            },
                            "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000),
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion
        for event in self.events:
            if self.high_impact_only and event.impact != "high":
                continue
            if currency and event.currency not in (currency, "ALL"):
                continue
            event_ts = _ensure_utc(event.timestamp)
            window_start = event_ts - self.blackout_before
            window_end = event_ts + self.blackout_after
            # #region agent log
            try:
                import json as _json
                from pathlib import Path as _P

                _log = _P(__file__).resolve().parents[3] / "debug-eb4742.log"
                with _log.open("a", encoding="utf-8") as _f:
                    _f.write(
                        _json.dumps(
                            {
                                "sessionId": "eb4742",
                                "runId": "post-fix",
                                "hypothesisId": "B",
                                "location": "news_filter.py:is_blackout:compare",
                                "message": "compare after UTC normalize",
                                "data": {
                                    "event_tz": str(event_ts.tzinfo),
                                    "window_start_tz": str(window_start.tzinfo),
                                    "moment_tz": str(moment.tzinfo),
                                    "mismatch": (event_ts.tzinfo is None)
                                    != (moment.tzinfo is None),
                                    "title": event.title[:80],
                                },
                                "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000),
                            }
                        )
                        + "\n"
                    )
            except Exception:
                pass
            # #endregion
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
                timestamp=_ensure_utc(datetime.fromisoformat(item["timestamp"])),
                currency=item.get("currency", "ALL"),
                impact=item.get("impact", "high"),
                title=item.get("title", ""),
            )
        )
    return events


def _fetch_events_from_api(api_key: str) -> list[NewsEvent] | None:
    """Fetch high-impact events from Finnhub economic calendar (last 7d + next 14d)."""
    import requests

    today = date.today()
    params = {
        "from": (today - timedelta(days=7)).isoformat(),
        "to": (today + timedelta(days=14)).isoformat(),
        "token": api_key,
    }
    try:
        response = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params=params,
            timeout=10,
        )
        if response.status_code >= 400:
            logger.warning(
                "Finnhub calendar HTTP {}: {}", response.status_code, response.text[:200]
            )
            return None
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("Finnhub calendar request failed: {}", exc)
        return None

    raw_events = payload.get("economicCalendar") or payload.get("data") or []
    if not raw_events:
        return None

    country_to_currency = {
        "US": "USD",
        "EU": "EUR",
        "DE": "EUR",
        "GB": "GBP",
        "JP": "JPY",
        "AU": "AUD",
        "CA": "CAD",
        "CH": "CHF",
        "NZ": "NZD",
    }

    events: list[NewsEvent] = []
    for item in raw_events:
        impact_raw = str(item.get("impact", item.get("importance", ""))).lower()
        if impact_raw not in ("high", "3", "3.0"):
            continue

        country = str(item.get("country", item.get("region", ""))).upper()
        currency = country_to_currency.get(country, country[:3] if country else "ALL")

        time_str = item.get("time") or item.get("date")
        if not time_str:
            continue
        try:
            ts = datetime.fromisoformat(str(time_str).replace("Z", "+00:00"))
        except ValueError:
            continue
        ts = _ensure_utc(ts)
        # #region agent log
        try:
            import json as _json
            from pathlib import Path as _P

            _log = _P(__file__).resolve().parents[3] / "debug-eb4742.log"
            with _log.open("a", encoding="utf-8") as _f:
                _f.write(
                    _json.dumps(
                        {
                            "sessionId": "eb4742",
                            "runId": "post-fix",
                            "hypothesisId": "C",
                            "location": "news_filter.py:_fetch_events_from_api",
                            "message": "parsed Finnhub timestamp normalized",
                            "data": {
                                "time_str_sample": str(time_str)[:40],
                                "ts_aware": ts.tzinfo is not None,
                                "ts_tz": str(ts.tzinfo),
                            },
                            "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000),
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion

        events.append(
            NewsEvent(
                timestamp=ts,
                currency=currency,
                impact="high",
                title=str(item.get("event", item.get("title", "economic release"))),
            )
        )

    logger.info("Fetched {} high-impact events from Finnhub", len(events))
    return events or None
