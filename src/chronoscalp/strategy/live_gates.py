"""Fail-closed live-enablement gates for research strategies.

``xau_vwap_pullback`` cannot be live-enabled until ``live_ready: true`` is set
after the validation checklist in ``docs/STRATEGY_XAU_VWAP_PULLBACK.md`` passes.
UI/API writers must coerce to shadow; the live loop must still refuse real
orders if someone edits YAML by hand.

Per-symbol validation state is reported, not enforced. A strategy can hold
positive evidence on one instrument and none on another — Delta on 2026-08-29
measured PF 1.754 on XAUUSD and four consecutive full stop-outs on EURUSD — so
the operator needs that split surfaced everywhere they can enable a symbol.
Choosing to trade an unvalidated symbol stays the operator's call; doing it
unknowingly must not be possible.
"""

from __future__ import annotations

from typing import Any

XAU_VWAP_PULLBACK = "xau_vwap_pullback"

VALIDATED = "validated"
FAILED = "failed"
UNVALIDATED = "unvalidated"


def _block(strategy_cfg: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    raw = strategy_cfg.get(strategy_id)
    return raw if isinstance(raw, dict) else {}


def is_strategy_live_ready(strategy_cfg: dict[str, Any], strategy_id: str) -> bool:
    """Return True when this strategy may place real live orders.

    Strategies without a dedicated research gate are treated as ready.
    """
    name = str(strategy_id or "").strip().lower()
    if name != XAU_VWAP_PULLBACK:
        return True
    return bool(_block(strategy_cfg, name).get("live_ready", False))


def force_shadow_if_not_live_ready(
    strategy_id: str,
    *,
    strategy_cfg: dict[str, Any],
    requested_shadow: bool,
) -> bool:
    """True when the strategy must stay shadow-only (requested or gated)."""
    if requested_shadow:
        return True
    return not is_strategy_live_ready(strategy_cfg, strategy_id)


def symbol_validation_state(strategy_cfg: dict[str, Any], strategy_id: str, symbol: str) -> str:
    """Return the recorded validation verdict for ``(strategy, symbol)``.

    One of :data:`VALIDATED`, :data:`FAILED`, or :data:`UNVALIDATED`. Anything
    not explicitly recorded in the strategy's ``symbol_validation`` block is
    ``UNVALIDATED`` — absence of evidence is never read as evidence.
    """
    block = _block(strategy_cfg, str(strategy_id or "").strip().lower())
    raw = block.get("symbol_validation")
    if not isinstance(raw, dict):
        return UNVALIDATED
    verdict = str(raw.get(symbol, "") or "").strip().lower()
    return verdict if verdict in {VALIDATED, FAILED} else UNVALIDATED


def unvalidated_live_symbols(
    strategy_cfg: dict[str, Any], strategy_id: str, symbols: list[str]
) -> list[str]:
    """Symbols in ``symbols`` this strategy has no positive evidence for.

    Used to warn on the live-loop startup gate profile and in Telegram status.
    Order follows ``symbols`` so the message reads like the operator's own list.
    """
    return [
        symbol
        for symbol in symbols
        if symbol_validation_state(strategy_cfg, strategy_id, symbol) != VALIDATED
    ]


def blocks_real_live_orders(
    strategy_cfg: dict[str, Any],
    strategy_id: str,
    *,
    mode: str,
    shadow_only: bool,
) -> bool:
    """Live process must not send real orders for gated or shadow strategies."""
    if shadow_only:
        return True
    return str(mode).lower() == "live" and not is_strategy_live_ready(strategy_cfg, strategy_id)
