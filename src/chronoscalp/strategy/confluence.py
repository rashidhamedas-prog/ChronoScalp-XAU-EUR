"""Shared SMC / liquidity confluence helpers."""

from __future__ import annotations

import pandas as pd

from chronoscalp.utils.types import TrendDirection


def smc_confirms(row: pd.Series, direction: TrendDirection) -> bool:
    if direction == TrendDirection.BULLISH:
        return bool(
            row.get("bullish_ob") or row.get("fvg_bullish") or row.get("liquidity_sweep_low")
        )
    if direction == TrendDirection.BEARISH:
        return bool(
            row.get("bearish_ob") or row.get("fvg_bearish") or row.get("liquidity_sweep_high")
        )
    return False


def liquidity_volume_confirms(row: pd.Series, direction: TrendDirection) -> bool:
    if direction == TrendDirection.BULLISH:
        return bool(row.get("liquidity_sweep_low_vol"))
    if direction == TrendDirection.BEARISH:
        return bool(row.get("liquidity_sweep_high_vol"))
    return False


def confluence_ok(
    row: pd.Series,
    direction: TrendDirection,
    *,
    use_smc_confluence: bool,
    use_liquidity_volume: bool,
) -> tuple[bool, list[str]]:
    """OR across enabled strategy modes — any confirming mode is enough."""
    if not use_smc_confluence and not use_liquidity_volume:
        return True, []

    tags: list[str] = []
    if use_smc_confluence and smc_confirms(row, direction):
        tags.append("smc_confirmed")
    if use_liquidity_volume and liquidity_volume_confirms(row, direction):
        tags.append("liquidity_volume")
    return bool(tags), tags
