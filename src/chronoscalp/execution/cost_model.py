"""Shared cash-cost model for paper, backtest, and sizing parity.

Round-turn commission comes from :func:`chronoscalp.risk.position_sizing.commission_per_lot`
(symbol-spec fields). Spread is charged as cash from ``spread_pips × pip_value × volume``.
Each side of a round turn pays half commission and half spread unless a caller
requests the full round-turn charge at close.

Phase 1 extensions: session spread multipliers, overnight swap/day, and
news-window slippage multipliers. One model for backtest, paper, and RL sim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from chronoscalp.risk.position_sizing import commission_per_lot
from chronoscalp.utils.types import SignalType

# Session multipliers calibrated as defaults — override via backtest_cfg.
_DEFAULT_SESSION_SPREAD_MULT: dict[str, float] = {
    "asia": 1.35,
    "london": 1.0,
    "new_york": 1.05,
    "overlap": 0.95,
    "off_hours": 1.5,
}


@dataclass(frozen=True)
class FillCosts:
    """Cash costs attributed to one fill (account currency)."""

    commission: float
    spread: float
    swap: float = 0.0
    slippage: float = 0.0

    @property
    def total(self) -> float:
        return float(self.commission) + float(self.spread) + float(self.swap) + float(self.slippage)


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


def session_name_utc(at: datetime) -> str:
    """Coarse session label for spread multipliers (London / NY local hours)."""
    if at.tzinfo is None:
        raise ValueError("session_name_utc requires a timezone-aware datetime")
    lon = at.astimezone(ZoneInfo("Europe/London"))
    ny = at.astimezone(ZoneInfo("America/New_York"))
    lon_h = lon.hour + lon.minute / 60.0
    ny_h = ny.hour + ny.minute / 60.0
    in_london = 8.0 <= lon_h < 16.5
    in_ny = 8.5 <= ny_h < 16.5
    if in_london and in_ny:
        return "overlap"
    if in_london:
        return "london"
    if in_ny:
        return "new_york"
    if 0.0 <= lon_h < 8.0:
        return "asia"
    return "off_hours"


def session_spread_multiplier(
    at: datetime | None,
    backtest_cfg: dict | None = None,
) -> float:
    """Return the session spread multiplier (1.0 = baseline)."""
    if at is None:
        return 1.0
    cfg = backtest_cfg or {}
    table = dict(_DEFAULT_SESSION_SPREAD_MULT)
    overrides = cfg.get("session_spread_multipliers") or {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            try:
                table[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    return float(table.get(session_name_utc(at), 1.0))


def resolve_session_spread_pips(
    symbol: str,
    symbols_cfg: dict,
    backtest_cfg: dict | None = None,
    *,
    at: datetime | None = None,
) -> float:
    """Typical spread × session multiplier for ``at``."""
    base = resolve_effective_spread_pips(symbol, symbols_cfg, backtest_cfg)
    return base * session_spread_multiplier(at, backtest_cfg)


def news_slippage_multiplier(
    *,
    in_news_window: bool,
    backtest_cfg: dict | None = None,
) -> float:
    """Extra slippage multiplier inside high-impact news windows."""
    if not in_news_window:
        return 1.0
    cfg = backtest_cfg or {}
    try:
        return max(1.0, float(cfg.get("news_slippage_multiplier", 2.0)))
    except (TypeError, ValueError):
        return 2.0


def overnight_swap_cash(
    symbol_spec: dict,
    *,
    direction: SignalType,
    volume: float,
    nights: int,
) -> float:
    """Cash swap for ``nights`` held (positive = charge against equity).

    Reads ``swap_long_per_lot`` / ``swap_short_per_lot`` (account currency per
    lot per night). Missing keys → 0.
    """
    if nights <= 0 or volume <= 0:
        return 0.0
    if direction == SignalType.BUY:
        rate = float(symbol_spec.get("swap_long_per_lot", 0.0) or 0.0)
    else:
        rate = float(symbol_spec.get("swap_short_per_lot", 0.0) or 0.0)
    # Positive rate = broker credits trader → negative cash cost.
    return float(-rate) * float(volume) * int(nights)


def side_fill_costs_extended(
    symbol_spec: dict,
    *,
    entry_price: float,
    volume: float,
    spread_pips: float,
    slippage_pips: float = 0.0,
    swap_cash: float = 0.0,
) -> FillCosts:
    """Side costs plus explicit slippage cash and overnight swap charge."""
    base = side_fill_costs(
        symbol_spec,
        entry_price=entry_price,
        volume=volume,
        spread_pips=spread_pips,
    )
    slip_cash = spread_cash_cost(symbol_spec, slippage_pips, volume) * 0.5
    return FillCosts(
        commission=base.commission,
        spread=base.spread,
        swap=float(swap_cash),
        slippage=float(slip_cash),
    )
