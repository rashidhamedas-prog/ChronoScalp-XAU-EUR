"""MT5 execution helpers — spread conversion, filling mode, position lookup.

Pure functions where possible so they can be unit-tested without a live
terminal. All MetaTrader5 imports stay inside functions (Windows-only).
"""

from __future__ import annotations

from chronoscalp.data.mt5_connector import _require_windows
from chronoscalp.logging_setup import logger

CHRONOSCALP_MAGIC = 20260711


def spread_points_to_pips(spread_points: float, point: float, pip_size: float) -> float:
    """Convert MT5 ``symbol_info.spread`` (points) to pips using broker point size."""
    if pip_size <= 0 or point <= 0:
        raise ValueError("pip_size and point must be positive")
    return spread_points * point / pip_size


def resolve_order_filling_mode(symbol: str) -> int:
    """Pick an ``ORDER_FILLING_*`` mode supported by the broker symbol."""
    _require_windows()
    import MetaTrader5 as mt5

    info = mt5.symbol_info(symbol)
    if info is None:
        logger.warning("resolve_order_filling_mode: no symbol_info for {}, defaulting IOC", symbol)
        return mt5.ORDER_FILLING_IOC

    filling = int(info.filling_mode)
    if filling & mt5.SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    if filling & mt5.SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    if filling & mt5.SYMBOL_FILLING_RETURN:
        return mt5.ORDER_FILLING_RETURN

    logger.warning(
        "resolve_order_filling_mode: no known filling flag for {} (mode={}), defaulting IOC",
        symbol,
        filling,
    )
    return mt5.ORDER_FILLING_IOC


def find_managed_position_ticket(symbol: str, magic: int = CHRONOSCALP_MAGIC) -> int | None:
    """Return the ticket of the most recent open position for ``symbol`` with ``magic``."""
    _require_windows()
    import MetaTrader5 as mt5

    raw_positions = mt5.positions_get(symbol=symbol)
    if not raw_positions:
        return None

    managed = [p for p in raw_positions if p.magic == magic]
    if not managed:
        return None

    return int(max(managed, key=lambda p: p.time).ticket)


def fetch_closed_position_pnl(ticket: int) -> float | None:
    """Best-effort realized P&L for a recently closed position (live mode)."""
    _require_windows()
    import MetaTrader5 as mt5

    deals = mt5.history_deals_get(position=ticket)
    if not deals:
        return None
    return float(sum(d.profit + d.swap + d.commission for d in deals))
