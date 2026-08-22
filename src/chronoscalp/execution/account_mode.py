"""Broker account margin mode — hedging vs netting.

Strategy and risk code must import this enum only, never a broker SDK.
MT5 detection lives in ``execution/mt5_broker.py``.
"""

from __future__ import annotations

from enum import StrEnum


class AccountMarginMode(StrEnum):
    """How the broker nets positions on one symbol."""

    HEDGING = "hedging"
    NETTING = "netting"
    UNKNOWN = "unknown"
    PAPER = "paper"


def independent_same_symbol_allowed(mode: AccountMarginMode) -> bool:
    """True when multiple independent tickets on one symbol are real, not fake."""
    return mode in (AccountMarginMode.HEDGING, AccountMarginMode.PAPER)


def from_mt5_margin_mode(raw: int | None) -> AccountMarginMode:
    """Map MetaTrader5 ``account_info().margin_mode`` integers.

    Documented values (without importing the SDK here):
    0 = retail netting, 1 = exchange, 2 = retail hedging.
    Exchange is treated as netting: same-symbol tickets collapse.
    """
    if raw is None:
        return AccountMarginMode.UNKNOWN
    if int(raw) == 2:
        return AccountMarginMode.HEDGING
    if int(raw) in (0, 1):
        return AccountMarginMode.NETTING
    return AccountMarginMode.UNKNOWN
