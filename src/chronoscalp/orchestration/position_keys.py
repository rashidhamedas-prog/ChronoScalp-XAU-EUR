"""Composite open-position keys: (symbol, strategy) -> ticket.

Legacy state files keyed tickets by symbol only. Loaders accept both forms so
restarts do not drop managed positions.
"""

from __future__ import annotations

from chronoscalp.utils.strategy_tags import normalize_strategy_tag

KEY_SEPARATOR = "::"


def position_key(symbol: str, strategy: str | None) -> str:
    """Stable dict key for one strategy's open ticket on a symbol."""
    tag = normalize_strategy_tag(strategy)
    return f"{symbol}{KEY_SEPARATOR}{tag}"


def parse_position_key(key: str) -> tuple[str, str]:
    """Split a stored key into ``(symbol, strategy)``.

    Bare symbol keys (pre-TASK-002) map to strategy ``unknown``.
    """
    raw = str(key or "").strip()
    if KEY_SEPARATOR in raw:
        symbol, strategy = raw.split(KEY_SEPARATOR, 1)
        return symbol, normalize_strategy_tag(strategy)
    return raw, "unknown"


def is_composite_key(key: str) -> bool:
    """True when ``key`` already uses the symbol::strategy form."""
    return KEY_SEPARATOR in str(key or "")
