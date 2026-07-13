"""Persistent trading state — survives restarts and supports reconciliation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from chronoscalp.logging_setup import logger


@dataclass
class TradingState:
    open_tickets: dict[str, int] = field(default_factory=dict)
    processed_signals: list[str] = field(default_factory=list)
    last_evaluated_bars: dict[str, str] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_tickets": dict(self.open_tickets),
            "processed_signals": list(self.processed_signals),
            "last_evaluated_bars": dict(self.last_evaluated_bars),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradingState:
        return cls(
            open_tickets={str(k): int(v) for k, v in (data.get("open_tickets") or {}).items()},
            processed_signals=list(data.get("processed_signals") or []),
            last_evaluated_bars={str(k): str(v) for k, v in (data.get("last_evaluated_bars") or {}).items()},
            updated_at=str(data.get("updated_at") or ""),
        )


class TradingStateStore:
    """JSON-backed store for ``open_tickets`` and dedup keys."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.state = TradingState()

    def load(self) -> TradingState:
        if not self.path.exists():
            logger.info("No prior trading state at {} — starting fresh", self.path)
            self.state = TradingState()
            return self.state

        with self.path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        self.state = TradingState.from_dict(raw)
        logger.info(
            "Loaded trading state: {} open ticket(s), {} dedup key(s)",
            len(self.state.open_tickets),
            len(self.state.processed_signals),
        )
        return self.state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = datetime.utcnow().isoformat()
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2)

    def reconcile_open_tickets(self, broker_tickets_by_symbol: dict[str, int]) -> None:
        """Sync in-memory tickets with broker reality after startup."""
        stale = [sym for sym in self.state.open_tickets if sym not in broker_tickets_by_symbol]
        for sym in stale:
            logger.warning("Reconcile: dropping stale ticket for {} (not on broker)", sym)
            self.state.open_tickets.pop(sym, None)

        for sym, ticket in broker_tickets_by_symbol.items():
            if sym not in self.state.open_tickets:
                logger.info("Reconcile: adopting broker position {} ticket={}", sym, ticket)
            self.state.open_tickets[sym] = ticket

        if stale or broker_tickets_by_symbol:
            self.save()
