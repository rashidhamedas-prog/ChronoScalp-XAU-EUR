"""Tests for ultra-scalp per-symbol allow/deny gates."""

from __future__ import annotations

from chronoscalp.strategy.multi_timeframe import ultra_scalp_allowed_for_symbol


def test_disabled_symbols_blocks_fx_majors_including_broker_suffix() -> None:
    cfg = {"disabled_symbols": ["EURUSD", "USDJPY", "XAUUSD"]}
    assert not ultra_scalp_allowed_for_symbol("EURUSD", cfg)
    assert not ultra_scalp_allowed_for_symbol("EURUSD_o", cfg)
    assert not ultra_scalp_allowed_for_symbol("USDJPY", cfg)
    assert ultra_scalp_allowed_for_symbol("BTCUSD", cfg)


def test_allowed_symbols_whitelist() -> None:
    cfg = {"allowed_symbols": ["BTCUSD"]}
    assert ultra_scalp_allowed_for_symbol("BTCUSD", cfg)
    assert not ultra_scalp_allowed_for_symbol("EURUSD_o", cfg)
    assert not ultra_scalp_allowed_for_symbol("XAUUSD", cfg)


def test_empty_allowlist_blocks_all() -> None:
    assert not ultra_scalp_allowed_for_symbol("EURUSD", {"allowed_symbols": []})


def test_legacy_no_lists_allows_all() -> None:
    assert ultra_scalp_allowed_for_symbol("EURUSD", {})
