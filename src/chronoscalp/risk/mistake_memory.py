"""Deterministic learn-from-mistakes veto (not ML).

Records losing setup fingerprints and blocks near-identical re-entries
for a configurable cooldown window.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from chronoscalp.logging_setup import logger


def canonical_symbol(symbol: str) -> str:
    """``XAUUSD_o`` / ``EURUSD`` → uppercase root before underscore."""
    return str(symbol or "").strip().upper().split("_", 1)[0]


def setup_reason_bucket(reason: str | None) -> str:
    """First comma-token of reason, lowercased and lightly normalized."""
    text = str(reason or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return ""
    return text.split(",")[0].strip("._ ")


def _parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class MistakeMemoryConfig:
    """Knobs loaded from ``settings.risk.mistake_memory``."""

    enabled: bool = True
    cooldown_minutes: int = 240
    max_repeats: int = 1
    min_loss_r: float = 0.0
    match_session: bool = True
    match_exit_type: bool = False
    persist: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> MistakeMemoryConfig:
        data = dict(raw or {})
        return cls(
            enabled=bool(data.get("enabled", True)),
            cooldown_minutes=int(data.get("cooldown_minutes", 240)),
            max_repeats=max(1, int(data.get("max_repeats", 1))),
            min_loss_r=float(data.get("min_loss_r", 0.0)),
            match_session=bool(data.get("match_session", True)),
            match_exit_type=bool(data.get("match_exit_type", False)),
            persist=bool(data.get("persist", True)),
        )


@dataclass
class Lesson:
    """One recorded losing setup."""

    fingerprint: str
    recorded_at: str
    symbol: str
    strategy: str
    session: str
    direction: str
    setup_reason_bucket: str
    pnl: float
    r_multiple: float
    exit_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Lesson:
        return cls(
            fingerprint=str(data.get("fingerprint") or ""),
            recorded_at=str(data.get("recorded_at") or ""),
            symbol=str(data.get("symbol") or ""),
            strategy=str(data.get("strategy") or ""),
            session=str(data.get("session") or "any"),
            direction=str(data.get("direction") or ""),
            setup_reason_bucket=str(data.get("setup_reason_bucket") or ""),
            pnl=float(data.get("pnl") or 0.0),
            r_multiple=float(data.get("r_multiple") or 0.0),
            exit_type=str(data.get("exit_type") or ""),
        )


@dataclass
class MistakeMemory:
    """Persist and gate losing setup fingerprints."""

    config: MistakeMemoryConfig
    path: Path
    mode: str = "paper"
    lessons: list[Lesson] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.config.persist:
            self.load()

    @classmethod
    def from_settings(
        cls,
        risk_cfg: dict[str, Any],
        *,
        state_dir: str | Path,
        mode: str,
    ) -> MistakeMemory:
        """Build from ``settings.risk`` and ``state_dir/lessons_{mode}.json``."""
        cfg = MistakeMemoryConfig.from_dict(risk_cfg.get("mistake_memory"))
        path = Path(state_dir) / f"lessons_{mode}.json"
        return cls(config=cfg, path=path, mode=mode)

    def fingerprint(
        self,
        *,
        symbol: str,
        strategy: str,
        session: str | None,
        direction: str,
        reason: str | None,
        exit_type: str | None = None,
    ) -> str:
        """Build the gate key for a candidate or closed trade."""
        sym = canonical_symbol(symbol)
        strat = str(strategy or "").strip().lower().replace(" ", "_").replace("-", "_")
        if self.config.match_session:
            sess = str(session or "none").strip().lower() or "none"
        else:
            sess = "any"
        direction_norm = str(direction or "").strip().lower()
        bucket = setup_reason_bucket(reason)
        parts = [sym, strat, sess, direction_norm, bucket]
        if self.config.match_exit_type:
            parts.append(str(exit_type or "").strip().lower())
        return "|".join(parts)

    def _is_incomplete(
        self,
        *,
        symbol: str,
        strategy: str,
        direction: str,
        reason: str | None,
        pnl: float | None,
        r_multiple: float | None,
    ) -> bool:
        if pnl is None or r_multiple is None:
            return True
        if not canonical_symbol(symbol):
            return True
        if not str(strategy or "").strip():
            return True
        if not str(direction or "").strip():
            return True
        return not bool(setup_reason_bucket(reason))

    def record_loss(
        self,
        *,
        symbol: str,
        strategy: str,
        session: str | None,
        direction: str,
        reason: str | None,
        pnl: float,
        r_multiple: float,
        exit_type: str | None = None,
        at: datetime | None = None,
    ) -> Lesson | None:
        """Record a losing lesson when thresholds are met."""
        if not self.config.enabled:
            return None
        if self._is_incomplete(
            symbol=symbol,
            strategy=strategy,
            direction=direction,
            reason=reason,
            pnl=pnl,
            r_multiple=r_multiple,
        ):
            return None
        if float(pnl) >= 0:
            return None
        if float(r_multiple) > float(self.config.min_loss_r):
            return None

        now = at or datetime.now(tz=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        fp = self.fingerprint(
            symbol=symbol,
            strategy=strategy,
            session=session,
            direction=direction,
            reason=reason,
            exit_type=exit_type,
        )
        lesson = Lesson(
            fingerprint=fp,
            recorded_at=now.isoformat(),
            symbol=canonical_symbol(symbol),
            strategy=str(strategy or "").strip().lower(),
            session=(
                str(session or "none").strip().lower() or "none"
                if self.config.match_session
                else "any"
            ),
            direction=str(direction or "").strip().lower(),
            setup_reason_bucket=setup_reason_bucket(reason),
            pnl=float(pnl),
            r_multiple=float(r_multiple),
            exit_type=str(exit_type or "").strip().lower(),
        )
        self.lessons.append(lesson)
        if self.config.persist:
            self.save()
        logger.info(
            "MistakeMemory lesson recorded fp={} pnl={:.2f} r={:.3f}",
            fp,
            lesson.pnl,
            lesson.r_multiple,
        )
        return lesson

    def record_from_closed_trade(
        self,
        record: Any,
        *,
        session: str | None = None,
        at: datetime | None = None,
    ) -> Lesson | None:
        """Extract fields from a journal closed-trade record and record_loss."""
        if record is None:
            return None
        pnl = getattr(record, "pnl", None)
        if pnl is None:
            return None
        try:
            pnl_f = float(pnl)
        except (TypeError, ValueError):
            return None
        if pnl_f >= 0:
            return None
        reason = getattr(record, "reason", None) or ""
        r_raw = getattr(record, "r_multiple", None)
        try:
            r_multiple = float(r_raw) if r_raw is not None else None
        except (TypeError, ValueError):
            r_multiple = None
        if r_multiple is None:
            return None
        direction = getattr(record, "direction", "") or ""
        if hasattr(direction, "value"):
            direction = direction.value
        return self.record_loss(
            symbol=str(getattr(record, "symbol", "") or ""),
            strategy=str(getattr(record, "strategy", "") or ""),
            session=session,
            direction=str(direction),
            reason=str(reason),
            pnl=pnl_f,
            r_multiple=r_multiple,
            exit_type=str(getattr(record, "exit_reason", "") or ""),
            at=at,
        )

    def blocks(self, fingerprint: str, now: datetime | None = None) -> bool:
        """True when matching lessons in the cooldown window reach ``max_repeats``."""
        if not self.config.enabled:
            return False
        fp = str(fingerprint or "").strip()
        if not fp:
            return False
        moment = now or datetime.now(tz=UTC)
        moment = (
            moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
        )
        window = timedelta(minutes=max(0, int(self.config.cooldown_minutes)))
        cutoff = moment - window
        count = 0
        for lesson in self.lessons:
            if lesson.fingerprint != fp:
                continue
            recorded = _parse_iso(lesson.recorded_at)
            if recorded is None:
                continue
            if recorded >= cutoff:
                count += 1
        return count >= int(self.config.max_repeats)

    def load(self) -> None:
        """Load lessons from disk; missing/corrupt files start empty."""
        if not self.path.exists():
            self.lessons = []
            return
        try:
            with self.path.open(encoding="utf-8-sig") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("MistakeMemory load failed {}: {}", self.path, exc)
            self.lessons = []
            return
        rows = raw.get("lessons") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            self.lessons = []
            return
        self.lessons = [Lesson.from_dict(row) for row in rows if isinstance(row, dict)]
        if isinstance(raw, dict) and raw.get("mode"):
            self.mode = str(raw["mode"])

    def save(self) -> None:
        """Persist lessons to ``lessons_{mode}.json``."""
        if not self.config.persist:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mode": self.mode,
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "lessons": [lesson.to_dict() for lesson in self.lessons],
        }
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
