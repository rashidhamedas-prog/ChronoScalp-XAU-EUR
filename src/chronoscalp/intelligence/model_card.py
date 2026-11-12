"""Model cards for regime / ML / RL artifacts (committed with trained models)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class ModelCard:
    name: str
    kind: str  # regime | ml_gate | rl_manager
    created_at: str
    features: list[str]
    training_window: str
    metrics: dict[str, float] = field(default_factory=dict)
    costs_net: bool = True
    notes: list[str] = field(default_factory=list)
    enabled_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_model_card(card: ModelCard, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(card.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def new_card(
    *,
    name: str,
    kind: str,
    features: list[str],
    training_window: str,
    metrics: dict[str, float] | None = None,
    notes: list[str] | None = None,
) -> ModelCard:
    return ModelCard(
        name=name,
        kind=kind,
        created_at=datetime.now(tz=UTC).isoformat(),
        features=list(features),
        training_window=training_window,
        metrics=dict(metrics or {}),
        notes=list(notes or []),
        costs_net=True,
        enabled_default=False,
    )
