"""Trading-session window filter.

Restricts trading to configured liquidity windows (default: London / New
York, GMT). This is a veto-only gate — it can suppress a signal, never
generate or upgrade one. See docs/ARCHITECTURE.md data-flow diagram.

NOTE: windows are treated as fixed GMT (not GMT-with-DST / "Europe/London"
local time). If you need broker-server-time or DST-aware sessions, extend
`SessionFilter` to accept a timezone-aware window definition rather than
patching this filter's call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


@dataclass(frozen=True)
class SessionWindow:
    name: str
    start: time
    end: time

    def contains(self, moment: datetime) -> bool:
        t = moment.time()
        if self.start <= self.end:
            return self.start <= t < self.end
        # Overnight window (e.g. 22:00-02:00) wraps past midnight.
        return t >= self.start or t < self.end


class SessionFilter:
    def __init__(self, windows: list[SessionWindow], trade_outside_sessions: bool = False) -> None:
        self.windows = windows
        self.trade_outside_sessions = trade_outside_sessions

    @classmethod
    def from_config(cls, sessions_cfg: dict) -> "SessionFilter":
        windows = []
        for name, spec in sessions_cfg.get("windows", {}).items():
            start = _parse_hhmm(spec["start"])
            end = _parse_hhmm(spec["end"])
            windows.append(SessionWindow(name=name, start=start, end=end))
        return cls(
            windows=windows,
            trade_outside_sessions=bool(sessions_cfg.get("trade_outside_sessions", False)),
        )

    def is_within_session(self, moment: datetime) -> bool:
        """`moment` must be a GMT/UTC timestamp — convert before calling if
        your data source uses broker-server time or local time."""
        if self.trade_outside_sessions:
            return True
        return any(window.contains(moment) for window in self.windows)

    def active_session_name(self, moment: datetime) -> str | None:
        for window in self.windows:
            if window.contains(moment):
                return window.name
        return None


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))
