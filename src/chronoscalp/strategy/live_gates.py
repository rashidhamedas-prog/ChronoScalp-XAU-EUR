"""Fail-closed live-enablement gates for research strategies.

``xau_vwap_pullback`` cannot be live-enabled until ``live_ready: true`` is set
after the validation checklist in ``docs/STRATEGY_XAU_VWAP_PULLBACK.md`` passes.
UI/API writers must coerce to shadow; the live loop must still refuse real
orders if someone edits YAML by hand.
"""

from __future__ import annotations

from typing import Any

XAU_VWAP_PULLBACK = "xau_vwap_pullback"


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
    return str(mode).lower() == "live" and not is_strategy_live_ready(
        strategy_cfg, strategy_id
    )
