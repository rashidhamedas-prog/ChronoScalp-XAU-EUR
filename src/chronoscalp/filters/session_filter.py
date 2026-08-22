"""Trading-session window filter.

Restricts trading to configured liquidity windows (default: London / New
York). This is a veto-only gate — it can suppress a signal, never generate
or upgrade one. See docs/ARCHITECTURE.md data-flow diagram.

``trading_hours_mode``:
- ``london_ny`` — only configured London / New York windows (all symbols)
- ``always_on_24h`` — trade any time (all symbols)

Windows are interpreted in each session's IANA timezone (DST-aware) when
``sessions.market_timezones`` is set. Invalid timezones fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from chronoscalp.logging_setup import logger

TRADING_HOURS_LONDON_NY = "london_ny"
TRADING_HOURS_ALWAYS_ON_24H = "always_on_24h"
KNOWN_TRADING_HOURS_MODES = (TRADING_HOURS_LONDON_NY, TRADING_HOURS_ALWAYS_ON_24H)

DEFAULT_MARKET_TIMEZONES = {
    "london": "Europe/London",
    "new_york": "America/New_York",
}


def normalize_trading_hours_mode(raw: str | None) -> str:
    """Map user/config aliases onto a canonical trading-hours mode."""
    value = str(raw or TRADING_HOURS_LONDON_NY).strip().lower().replace("-", "_")
    aliases = {
        "london_ny": TRADING_HOURS_LONDON_NY,
        "london": TRADING_HOURS_LONDON_NY,
        "sessions": TRADING_HOURS_LONDON_NY,
        "session": TRADING_HOURS_LONDON_NY,
        "ny_london": TRADING_HOURS_LONDON_NY,
        "always_on_24h": TRADING_HOURS_ALWAYS_ON_24H,
        "always_on": TRADING_HOURS_ALWAYS_ON_24H,
        "24h": TRADING_HOURS_ALWAYS_ON_24H,
        "24_7": TRADING_HOURS_ALWAYS_ON_24H,
        "all_day": TRADING_HOURS_ALWAYS_ON_24H,
    }
    return aliases.get(value, TRADING_HOURS_LONDON_NY)


def _resolve_zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError, Exception):
        logger.error("Session timezone {!r} is invalid — failing closed", name)
        return None


@dataclass(frozen=True)
class SessionWindow:
    name: str
    start: time
    end: time
    timezone: str = "UTC"

    def contains(self, moment: datetime) -> bool:
        zone = _resolve_zone(self.timezone)
        if zone is None:
            return False
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        local = moment.astimezone(zone)
        t = local.timetz().replace(tzinfo=None)
        if self.start <= self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end


class SessionFilter:
    def __init__(
        self,
        windows: list[SessionWindow],
        trade_outside_sessions: bool = False,
        always_on_symbols: set[str] | None = None,
        trading_hours_mode: str = TRADING_HOURS_LONDON_NY,
        *,
        strict_session_mode: bool = False,
        timezone_ok: bool = True,
    ) -> None:
        self.windows = windows
        self.trading_hours_mode = normalize_trading_hours_mode(trading_hours_mode)
        self.trade_outside_sessions = bool(trade_outside_sessions) or (
            self.trading_hours_mode == TRADING_HOURS_ALWAYS_ON_24H
        )
        self.always_on_symbols = set(always_on_symbols or ())
        self.strict_session_mode = bool(strict_session_mode)
        self.timezone_ok = bool(timezone_ok)
        if self.strict_session_mode:
            self.always_on_symbols = set()

    @classmethod
    def from_config(cls, sessions_cfg: dict) -> SessionFilter:
        tz_map = dict(DEFAULT_MARKET_TIMEZONES)
        raw_tz = sessions_cfg.get("market_timezones") or {}
        if isinstance(raw_tz, dict):
            for key, value in raw_tz.items():
                if value:
                    tz_map[str(key).strip().lower()] = str(value).strip()
        timezone_ok = True
        windows = []
        for name, spec in sessions_cfg.get("windows", {}).items():
            start = _parse_hhmm(spec["start"])
            end = _parse_hhmm(spec["end"])
            tz_name = tz_map.get(str(name).strip().lower(), "UTC")
            if _resolve_zone(tz_name) is None:
                timezone_ok = False
            windows.append(SessionWindow(name=name, start=start, end=end, timezone=tz_name))
        always_on = {str(s) for s in (sessions_cfg.get("always_on_symbols") or [])}
        raw_mode = sessions_cfg.get("trading_hours_mode")
        legacy_outside = bool(sessions_cfg.get("trade_outside_sessions", False))

        if raw_mode is None:
            mode = TRADING_HOURS_ALWAYS_ON_24H if legacy_outside else TRADING_HOURS_LONDON_NY
            return cls(
                windows=windows,
                trade_outside_sessions=legacy_outside,
                always_on_symbols=always_on,
                trading_hours_mode=mode,
                strict_session_mode=False,
                timezone_ok=timezone_ok,
            )

        mode = normalize_trading_hours_mode(raw_mode)
        if mode == TRADING_HOURS_ALWAYS_ON_24H:
            return cls(
                windows=windows,
                trade_outside_sessions=True,
                always_on_symbols=always_on,
                trading_hours_mode=mode,
                strict_session_mode=False,
                timezone_ok=timezone_ok,
            )
        return cls(
            windows=windows,
            trade_outside_sessions=False,
            always_on_symbols=always_on,
            trading_hours_mode=mode,
            strict_session_mode=True,
            timezone_ok=timezone_ok,
        )

    def is_within_session(self, moment: datetime, symbol: str | None = None) -> bool:
        """``moment`` should be timezone-aware UTC. Naive values are treated as UTC.

        Invalid configured timezones fail closed (no session).
        """
        if not self.timezone_ok:
            return False
        if self.trade_outside_sessions or self.trading_hours_mode == TRADING_HOURS_ALWAYS_ON_24H:
            return True
        if symbol and symbol in self.always_on_symbols:
            return True
        return any(window.contains(moment) for window in self.windows)

    def active_session_name(self, moment: datetime) -> str | None:
        if not self.timezone_ok:
            return None
        if self.trading_hours_mode == TRADING_HOURS_ALWAYS_ON_24H:
            return "always_on_24h"
        for window in self.windows:
            if window.contains(moment):
                return window.name
        return None


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))
