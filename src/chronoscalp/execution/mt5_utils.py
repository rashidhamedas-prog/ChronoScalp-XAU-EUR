"""MT5 execution helpers — spread conversion, filling mode, position lookup.

Pure functions where possible so they can be unit-tested without a live
terminal. All MetaTrader5 imports stay inside functions (Windows-only).
"""

from __future__ import annotations

from chronoscalp.data.mt5_connector import _require_windows
from chronoscalp.logging_setup import logger

CHRONOSCALP_MAGIC = 20260711

# MT5 order comments are broker-limited (commonly ≤31 chars, ASCII-safe).
_MT5_COMMENT_MAX = 31


class StaleStopsError(ValueError):
    """Live fill price moved through signal SL/TP — refuse order_send (Invalid stops)."""


def sanitize_mt5_comment(text: str, *, max_len: int = _MT5_COMMENT_MAX) -> str:
    """Return a broker-safe MT5 order comment (ASCII, no spaces, ≤ ``max_len``)."""
    raw = (text or "").strip()
    cleaned = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_" for ch in raw)
    cleaned = cleaned.strip("._-") or "ChronoScalp"
    return cleaned[:max_len]


def validate_stops_vs_fill_price(
    *,
    is_buy: bool,
    fill_price: float,
    stop_loss: float,
    take_profit: float,
) -> None:
    """Require SL/TP on the correct side of the live fill price.

    Strategy builds stops from bar close; ``order_send`` uses ask/bid. If price
    gaps through the stop before send, MT5 returns ``Invalid stops``. Reject
    here instead of tightening risk or flipping geometry.
    """
    if fill_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        raise StaleStopsError(
            f"non-positive stop levels fill={fill_price} sl={stop_loss} tp={take_profit}"
        )
    if is_buy:
        if not (stop_loss < fill_price < take_profit):
            raise StaleStopsError(
                f"BUY requires sl < price < tp; got sl={stop_loss} price={fill_price} tp={take_profit}"
            )
    else:
        if not (take_profit < fill_price < stop_loss):
            raise StaleStopsError(
                f"SELL requires tp < price < sl; got tp={take_profit} price={fill_price} sl={stop_loss}"
            )


def spread_points_to_pips(spread_points: float, point: float, pip_size: float) -> float:
    """Convert MT5 ``symbol_info.spread`` (points) to pips using broker point size."""
    if pip_size <= 0 or point <= 0:
        raise ValueError("pip_size and point must be positive")
    return spread_points * point / pip_size


# MQL5 symbol_info.filling_mode bit flags (not always exported by MetaTrader5 pip).
_SYMBOL_FILLING_FOK = 1
_SYMBOL_FILLING_IOC = 2
_SYMBOL_FILLING_RETURN = 4


def resolve_order_filling_mode(symbol: str) -> int:
    """Pick an ``ORDER_FILLING_*`` mode supported by the broker symbol.

    ``symbol_info.filling_mode`` is a bitmask of ``SYMBOL_FILLING_*`` (1/2/4).
    Some MetaTrader5 builds omit those names and only expose ``ORDER_FILLING_*``
    (0/1/2) used in ``order_send`` — never bitwise-AND those against filling_mode.
    """
    _require_windows()
    import MetaTrader5 as mt5

    order_ioc = int(getattr(mt5, "ORDER_FILLING_IOC", 1))
    order_fok = int(getattr(mt5, "ORDER_FILLING_FOK", 0))
    order_return = int(getattr(mt5, "ORDER_FILLING_RETURN", 2))
    sym_ioc = int(getattr(mt5, "SYMBOL_FILLING_IOC", _SYMBOL_FILLING_IOC))
    sym_fok = int(getattr(mt5, "SYMBOL_FILLING_FOK", _SYMBOL_FILLING_FOK))
    sym_return = int(getattr(mt5, "SYMBOL_FILLING_RETURN", _SYMBOL_FILLING_RETURN))

    info = mt5.symbol_info(symbol)
    if info is None:
        logger.warning("resolve_order_filling_mode: no symbol_info for {}, defaulting IOC", symbol)
        return order_ioc

    filling = int(info.filling_mode)
    if filling & sym_ioc:
        return order_ioc
    if filling & sym_fok:
        return order_fok
    if filling & sym_return:
        return order_return

    logger.warning(
        "resolve_order_filling_mode: no known filling flag for {} (mode={}), defaulting IOC",
        symbol,
        filling,
    )
    return order_ioc


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
