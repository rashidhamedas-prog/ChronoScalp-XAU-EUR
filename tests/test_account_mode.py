from __future__ import annotations

from chronoscalp.execution.account_mode import (
    AccountMarginMode,
    from_mt5_margin_mode,
    independent_same_symbol_allowed,
)


def test_mt5_margin_mode_mapping():
    assert from_mt5_margin_mode(2) == AccountMarginMode.HEDGING
    assert from_mt5_margin_mode(0) == AccountMarginMode.NETTING
    assert from_mt5_margin_mode(1) == AccountMarginMode.NETTING
    assert from_mt5_margin_mode(None) == AccountMarginMode.UNKNOWN


def test_independent_same_symbol_allowed():
    assert independent_same_symbol_allowed(AccountMarginMode.HEDGING) is True
    assert independent_same_symbol_allowed(AccountMarginMode.PAPER) is True
    assert independent_same_symbol_allowed(AccountMarginMode.NETTING) is False
    assert independent_same_symbol_allowed(AccountMarginMode.UNKNOWN) is False
