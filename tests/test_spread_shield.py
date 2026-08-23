from __future__ import annotations

from chronoscalp.filters.spread_shield import RollingMedianSpread, spread_allowed


def test_spread_allowed_cap_and_median():
    ok, why = spread_allowed(20.0, broker_cap_pips=35.0, rolling_median_pips=18.0)
    assert ok is True
    assert why == ""
    ok, why = spread_allowed(36.0, broker_cap_pips=35.0, rolling_median_pips=18.0)
    assert ok is False
    assert why == "spread_cap"
    ok, why = spread_allowed(25.0, broker_cap_pips=35.0, rolling_median_pips=18.0)
    assert ok is False
    assert why == "spread_vs_median"


def test_spread_allowed_fails_closed_without_median():
    ok, why = spread_allowed(10.0, broker_cap_pips=35.0, rolling_median_pips=None)
    assert ok is False
    assert why == "spread_median_unavailable"


def test_rolling_median_needs_three_samples():
    roll = RollingMedianSpread(window=10)
    roll.observe("XAUUSD", 20.0)
    roll.observe("XAUUSD", 22.0)
    assert roll.median("XAUUSD") is None
    roll.observe("XAUUSD", 24.0)
    assert roll.median("XAUUSD") == 22.0
