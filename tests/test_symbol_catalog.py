"""Per-symbol strategy catalogs — selecting a symbol owns its engines."""

from __future__ import annotations

from chronoscalp.strategy.multi_timeframe import resolve_enabled_strategies
from chronoscalp.strategy.symbol_catalog import (
    DEFAULT_SYMBOL_CATALOGS,
    catalogs_from_config,
    merge_symbol_overrides,
    strategies_for_symbol,
    strategies_for_symbols,
)


def test_default_gold_book_is_delta_operator_style_and_news() -> None:
    names = strategies_for_symbol({}, "XAUUSD")
    assert names == ["delta", "operator_style", "news_straddle"]
    assert names == list(DEFAULT_SYMBOL_CATALOGS["XAUUSD"])


def test_default_eur_book_is_operator_style_and_news() -> None:
    names = strategies_for_symbol({}, "EURUSD")
    assert names == ["operator_style", "news_straddle"]
    assert "delta" not in names
    assert "xau_vwap_pullback" not in names
    assert "smc_confluence" not in names
    assert "ultra_scalp" not in names


def test_broker_suffix_uses_same_book() -> None:
    assert strategies_for_symbol({}, "XAUUSD_o") == strategies_for_symbol({}, "XAUUSD")


def test_unknown_symbol_has_empty_book() -> None:
    assert strategies_for_symbol({}, "BTCUSD") == []


def test_union_preserves_catalog_order() -> None:
    names = strategies_for_symbols({}, ["EURUSD", "XAUUSD"])
    assert names == ["operator_style", "news_straddle", "delta"]
    assert names.count("operator_style") == 1
    assert names.count("delta") == 1


def test_resolve_with_symbol_uses_catalog_when_flag_on() -> None:
    cfg = {
        "derive_strategies_from_symbols": True,
        "symbol_catalogs": {"XAUUSD": ["delta", "news_straddle"]},
        "enabled_strategies": ["smc_confluence"],
    }
    gold = resolve_enabled_strategies(cfg, symbol="XAUUSD")
    assert gold.delta and gold.news_straddle
    assert not gold.smc
    legacy = resolve_enabled_strategies(cfg)
    assert legacy.smc and not legacy.delta


def test_resolve_without_catalogs_keeps_enabled_list() -> None:
    enabled = resolve_enabled_strategies({"enabled_strategies": ["delta"]})
    assert enabled.delta and not enabled.smc


def test_merge_symbol_overrides_applies_root() -> None:
    merged = merge_symbol_overrides(
        {"rvol_min": 1.5, "symbol_overrides": {"XAUUSD": {"rvol_min": 1.15}}},
        "XAUUSD_o",
    )
    assert merged["rvol_min"] == 1.15


def test_catalogs_from_config_ignores_unknown_engines() -> None:
    cats = catalogs_from_config({"symbol_catalogs": {"XAUUSD": ["delta", "made_up"]}})
    assert cats["XAUUSD"] == ["delta"]
