"""Per-symbol strategy catalogs — selecting a symbol enables its engines.

Operators pick symbols only. Gold and EUR each run Delta plus a news
straddle (pending BUY_STOP + SELL_STOP). Overlay ``enabled_strategies`` is
ignored whenever catalogs are present so a stale picker cannot silently
change the live book.
"""

from __future__ import annotations

from typing import Any

KNOWN_STRATEGY_IDS: frozenset[str] = frozenset(
    {
        "smc_confluence",
        "liquidity_volume",
        "ultra_scalp",
        "news_straddle",
        "delta",
        "xau_vwap_pullback",
    }
)

# Built-in catalogs used when config omits ``symbol_catalogs``.
DEFAULT_SYMBOL_CATALOGS: dict[str, tuple[str, ...]] = {
    "XAUUSD": ("delta", "news_straddle"),
    "EURUSD": ("delta", "news_straddle"),
}


def canonical_symbol_root(symbol: str) -> str:
    """``EURUSD_o`` / ``XAUUSD`` → ``EURUSD`` / ``XAUUSD`` for catalog keys."""
    return str(symbol or "").strip().upper().split("_", 1)[0]


def merge_symbol_overrides(config: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Return ``config`` with ``symbol_overrides[<root>]`` copied on top.

    Shared by Delta, news, scalp, and the institutional entry so each market
    can keep its own RVOL, spread cap, and geometry without a second code path.
    """
    merged = dict(config)
    overrides = config.get("symbol_overrides") or {}
    if not isinstance(overrides, dict):
        return merged
    root = canonical_symbol_root(symbol)
    if not root:
        return merged
    for key, values in overrides.items():
        if canonical_symbol_root(str(key)) == root and isinstance(values, dict):
            merged.update(values)
    return merged


def _clean_strategy_names(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip().lower()
        if name in KNOWN_STRATEGY_IDS and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def catalogs_from_config(strategy_cfg: dict[str, Any] | None) -> dict[str, list[str]]:
    """Read ``strategy.symbol_catalogs``, falling back to the built-in books."""
    cfg = strategy_cfg or {}
    raw = cfg.get("symbol_catalogs")
    if not isinstance(raw, dict) or not raw:
        return {key: list(names) for key, names in DEFAULT_SYMBOL_CATALOGS.items()}
    out: dict[str, list[str]] = {}
    for key, names in raw.items():
        root = canonical_symbol_root(str(key))
        if root:
            out[root] = _clean_strategy_names(names)
    return out or {key: list(names) for key, names in DEFAULT_SYMBOL_CATALOGS.items()}


def derive_from_symbols_enabled(strategy_cfg: dict[str, Any] | None) -> bool:
    """True when live/paper should ignore the operator strategy picker.

    Explicit ``derive_strategies_from_symbols`` wins. Otherwise catalogs in
    the config turn derivation on; a bare ``enabled_strategies`` test dict
    stays on the legacy picker so unit tests do not silently change engines.
    """
    cfg = strategy_cfg or {}
    flag = cfg.get("derive_strategies_from_symbols")
    if flag is not None:
        return bool(flag)
    raw = cfg.get("symbol_catalogs")
    return isinstance(raw, dict) and bool(raw)


def strategies_for_symbol(strategy_cfg: dict[str, Any] | None, symbol: str) -> list[str]:
    """Engines that evaluate ``symbol``. Empty when the symbol has no book."""
    root = canonical_symbol_root(symbol)
    if not root:
        return []
    catalogs = catalogs_from_config(strategy_cfg)
    return list(catalogs.get(root) or [])


def strategies_for_symbols(
    strategy_cfg: dict[str, Any] | None, symbols: list[str] | tuple[str, ...]
) -> list[str]:
    """Union of catalogs for the selected symbols, catalog order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    catalogs = catalogs_from_config(strategy_cfg)
    for symbol in symbols:
        root = canonical_symbol_root(symbol)
        for name in catalogs.get(root) or []:
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def format_catalog_lines(
    strategy_cfg: dict[str, Any] | None,
    symbols: list[str] | tuple[str, ...],
    *,
    labels: dict[str, str] | None = None,
) -> list[str]:
    """One human-readable line per selected symbol for Telegram / status."""
    names = labels or {}
    lines: list[str] = []
    for symbol in symbols:
        engines = strategies_for_symbol(strategy_cfg, symbol)
        if not engines:
            lines.append(f"{symbol}: (کاتالوگ خالی — معامله‌ای ارزیابی نمی‌شود)")
            continue
        pretty = " · ".join(names.get(name, name) for name in engines)
        lines.append(f"{symbol}: {pretty}")
    return lines
