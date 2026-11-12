"""Shared cash-cost model for paper, backtest, and sizing parity.

Round-turn commission comes from :func:`chronoscalp.risk.position_sizing.commission_per_lot`
(symbol-spec fields). Spread is charged as cash from ``spread_pips × pip_value × volume``.
Each side of a round turn pays half commission and half spread unless a caller
requests the full round-turn charge at close.
"""

from __future__ import annotations

from dataclasses import dataclass

from chronoscalp.risk.position_sizing import commission_per_lot
from chronoscalp.utils.types import SignalType


@dataclass(frozen=True)
class FillCosts:
    """Cash costs attributed to one fill (account currency)."""

    commission: float
    spread: float

    @property
    def total(self) -> float:
        return float(self.commission) + float(self.spread)


def spread_cash_cost(symbol_spec: dict, spread_pips: float, volume: float) -> float:
    """Full quoted spread cost for ``volume`` lots (both sides of the market)."""
    pip_value = float(symbol_spec.get("pip_value_per_lot", 0.0) or 0.0)
    return max(0.0, float(spread_pips)) * pip_value * max(0.0, float(volume))


def side_fill_costs(
    symbol_spec: dict,
    *,
    entry_price: float,
    volume: float,
    spread_pips: float,
) -> FillCosts:
    """Half round-turn commission + half spread for one entry or exit side."""
    rt_commission = commission_per_lot(symbol_spec, float(entry_price))
    full_spread = spread_cash_cost(symbol_spec, spread_pips, volume)
    return FillCosts(commission=rt_commission * 0.5 * float(volume), spread=full_spread * 0.5)


def round_turn_fill_costs(
    symbol_spec: dict,
    *,
    entry_price: float,
    volume: float,
    spread_pips: float,
) -> FillCosts:
    """Full round-turn commission + full spread for ``volume`` lots."""
    rt_commission = commission_per_lot(symbol_spec, float(entry_price))
    return FillCosts(
        commission=rt_commission * float(volume),
        spread=spread_cash_cost(symbol_spec, spread_pips, volume),
    )


def adverse_price_for_side(
    *,
    mid_price: float,
    direction: SignalType,
    is_entry: bool,
    symbol_spec: dict,
    spread_pips: float,
    slippage_pips: float = 0.0,
) -> float:
    """Apply half-spread + slippage adverse to ``mid_price`` for buy/sell fills."""
    pip_size = float(symbol_spec.get("pip_size", 0.0) or 0.0)
    half_spread = max(0.0, float(spread_pips)) * pip_size / 2.0
    slip = max(0.0, float(slippage_pips)) * pip_size
    adverse = half_spread + slip
    if direction == SignalType.BUY:
        return float(mid_price) + adverse if is_entry else float(mid_price) - adverse
    return float(mid_price) - adverse if is_entry else float(mid_price) + adverse


def resolve_effective_spread_pips(
    symbol: str,
    symbols_cfg: dict,
    backtest_cfg: dict | None = None,
) -> float:
    """Prefer symbol typical spread; fall back to ``backtest.default_spread_pips``."""
    spec = symbols_cfg.get(symbol) or {}
    if "typical_spread_pips" in spec:
        return float(spec["typical_spread_pips"])
    defaults = (backtest_cfg or {}).get("default_spread_pips") or {}
    if symbol in defaults:
        return float(defaults[symbol])
    # Canonical family fallback (XAUUSD_o → XAUUSD).
    base = symbol.split("_")[0]
    if base in defaults:
        return float(defaults[base])
    return 0.0
