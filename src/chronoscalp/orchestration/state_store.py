"""Persistent trading state — survives restarts and supports reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chronoscalp.logging_setup import logger
from chronoscalp.orchestration.position_keys import (
    is_composite_key,
    parse_position_key,
    position_key,
)
from chronoscalp.utils.atomic_json import read_json_with_fallback, write_json_atomic
from chronoscalp.utils.strategy_tags import normalize_strategy_tag


def _normalize_ticket_map(raw: dict[str, Any] | None) -> dict[str, int]:
    """Accept legacy ``{symbol: ticket}`` and composite ``{symbol::strategy: ticket}``."""
    out: dict[str, int] = {}
    for key, value in (raw or {}).items():
        try:
            ticket = int(value)
        except (TypeError, ValueError):
            continue
        if is_composite_key(str(key)):
            symbol, strategy = parse_position_key(str(key))
            out[position_key(symbol, strategy)] = ticket
        else:
            out[position_key(str(key), "unknown")] = ticket
    return out


@dataclass
class TradingState:
    open_tickets: dict[str, int] = field(default_factory=dict)
    processed_signals: list[str] = field(default_factory=list)
    last_evaluated_bars: dict[str, str] = field(default_factory=dict)
    position_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_tickets": dict(self.open_tickets),
            "processed_signals": list(self.processed_signals),
            "last_evaluated_bars": dict(self.last_evaluated_bars),
            "position_meta": {str(k): dict(v) for k, v in self.position_meta.items()},
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradingState:
        raw_meta = data.get("position_meta") or {}
        return cls(
            open_tickets=_normalize_ticket_map(data.get("open_tickets") or {}),
            processed_signals=list(data.get("processed_signals") or []),
            last_evaluated_bars={
                str(k): str(v) for k, v in (data.get("last_evaluated_bars") or {}).items()
            },
            position_meta={str(k): dict(v) for k, v in raw_meta.items() if isinstance(v, dict)},
            updated_at=str(data.get("updated_at") or ""),
        )


class TradingStateStore:
    """JSON-backed store for ``open_tickets`` and dedup keys."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.state = TradingState()
        self._loaded_from_backup = False

    def load(self) -> TradingState:
        if not self.path.exists() and not self.path.with_suffix(self.path.suffix + ".bak").exists():
            logger.info("No prior trading state at {} — starting fresh", self.path)
            self.state = TradingState()
            return self.state

        def _require_mapping(payload: Any) -> None:
            if not isinstance(payload, dict):
                raise ValueError("state root must be a mapping")

        raw, source = read_json_with_fallback(
            self.path,
            default={"open_tickets": {}, "processed_signals": [], "last_evaluated_bars": {}},
            validate=_require_mapping,
        )
        self.state = TradingState.from_dict(raw if isinstance(raw, dict) else {})
        if source == "backup":
            logger.warning(
                "Loaded trading state from .bak — forcing broker reconciliation recommended"
            )
            self._loaded_from_backup = True
        else:
            self._loaded_from_backup = False
        logger.info(
            "Loaded trading state ({}): {} open ticket(s), {} dedup key(s)",
            source,
            len(self.state.open_tickets),
            len(self.state.processed_signals),
        )
        return self.state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = datetime.now(tz=UTC).isoformat()
        write_json_atomic(self.path, self.state.to_dict())

    def reconcile_open_tickets(
        self,
        broker_tickets: dict[str, int],
        *,
        ticket_strategies: dict[int, str] | None = None,
    ) -> None:
        """Sync in-memory tickets with broker reality after startup.

        ``broker_tickets`` maps composite ``symbol::strategy`` keys to tickets.
        Legacy ``{symbol: ticket}`` maps are upgraded using ``ticket_strategies``.
        """
        strategies = ticket_strategies or {}
        normalized: dict[str, int] = {}
        for key, ticket in broker_tickets.items():
            if is_composite_key(key):
                symbol, strategy = parse_position_key(key)
                normalized[position_key(symbol, strategy)] = int(ticket)
            else:
                tag = normalize_strategy_tag(strategies.get(int(ticket), "unknown"))
                normalized[position_key(str(key), tag)] = int(ticket)

        stale = [k for k in self.state.open_tickets if k not in normalized]
        for key in stale:
            logger.warning("Reconcile: dropping stale ticket {} (not on broker)", key)
            self.state.open_tickets.pop(key, None)

        for key, ticket in normalized.items():
            if key not in self.state.open_tickets:
                logger.info("Reconcile: adopting broker position {} ticket={}", key, ticket)
            self.state.open_tickets[key] = ticket

        if stale or normalized:
            self.save()
