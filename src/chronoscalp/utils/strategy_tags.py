"""Normalize strategy labels for journal, MT5 comments, and reporting."""

from __future__ import annotations

# Canonical tags used in journal / reporting (stable IDs).
STRATEGY_ULTRA_SCALP = "ultra_scalp"
STRATEGY_INSTITUTIONAL = "institutional"
STRATEGY_NEWS_STRADDLE = "news_straddle"
STRATEGY_SMC = "smc_confluence"
STRATEGY_LIQUIDITY = "liquidity_volume"
STRATEGY_DELTA = "delta"
STRATEGY_UNKNOWN = "unknown"

# Display order for strategy P&L tables.
STRATEGY_REPORT_ORDER: tuple[str, ...] = (
    STRATEGY_ULTRA_SCALP,
    STRATEGY_INSTITUTIONAL,
    STRATEGY_NEWS_STRADDLE,
    STRATEGY_SMC,
    STRATEGY_LIQUIDITY,
    STRATEGY_DELTA,
    STRATEGY_UNKNOWN,
)


def normalize_strategy_tag(raw: str | None) -> str:
    """Map free-form reason/comment fragments to a canonical strategy id."""
    text = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return STRATEGY_UNKNOWN

    # Strip common MT5 comment prefixes.
    if text.startswith("cs_"):
        text = text[3:]

    head = text.split(",")[0].strip("._ ")

    checks: tuple[tuple[str, tuple[str, ...]], ...] = (
        (STRATEGY_NEWS_STRADDLE, ("news_straddle", "newsstraddle")),
        (STRATEGY_ULTRA_SCALP, ("ultra_scalp", "ultrascalp", "ultra_scalp_v3")),
        (STRATEGY_INSTITUTIONAL, ("institutional_entry", "institutional")),
        (STRATEGY_SMC, ("smc_confluence", "smc")),
        (STRATEGY_LIQUIDITY, ("liquidity_volume", "liquidity_sweep", "liquidity")),
        (STRATEGY_DELTA, ("delta",)),
    )
    blob = f"{head}|{text}"
    for canonical, needles in checks:
        for needle in needles:
            if needle in blob:
                return canonical
    if head in {
        STRATEGY_ULTRA_SCALP,
        STRATEGY_INSTITUTIONAL,
        STRATEGY_NEWS_STRADDLE,
        STRATEGY_SMC,
        STRATEGY_LIQUIDITY,
        STRATEGY_DELTA,
    }:
        return head
    return STRATEGY_UNKNOWN


def strategy_from_reason(reason: str | None) -> str:
    """Derive strategy tag from a Signal.reason string."""
    return normalize_strategy_tag(reason)


def strategy_from_comment(comment: str | None) -> str:
    """Derive strategy tag from an MT5/broker order comment."""
    return normalize_strategy_tag(comment)


def resolve_strategy_tag(
    *,
    explicit: str | None = None,
    reason: str | None = None,
    comment: str | None = None,
) -> str:
    """Prefer explicit tag, then reason, then comment."""
    if explicit and str(explicit).strip():
        tag = normalize_strategy_tag(explicit)
        if tag != STRATEGY_UNKNOWN:
            return tag
    from_reason = strategy_from_reason(reason)
    if from_reason != STRATEGY_UNKNOWN:
        return from_reason
    from_comment = strategy_from_comment(comment)
    if from_comment != STRATEGY_UNKNOWN:
        return from_comment
    if explicit and str(explicit).strip():
        return normalize_strategy_tag(explicit)
    return STRATEGY_UNKNOWN


def mt5_comment_for_strategy(strategy: str | None) -> str:
    """Short broker-safe comment encoding the strategy (≤31 chars after sanitize)."""
    tag = normalize_strategy_tag(strategy)
    # Keep prefix short so tag survives MT5's 31-char comment limit.
    return f"CS_{tag}"[:31]
