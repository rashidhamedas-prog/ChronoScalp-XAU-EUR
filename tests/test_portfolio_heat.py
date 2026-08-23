from __future__ import annotations

import pytest

from chronoscalp.risk.portfolio_heat import (
    allocate_risk_pct,
    open_heat_from_dollar_risks,
    resolve_max_portfolio_heat_pct,
)
from chronoscalp.risk.position_sizing import HARD_MAX_RISK_PCT


def test_heat_ceiling_never_exceeds_daily_loss():
    assert (
        resolve_max_portfolio_heat_pct({"max_portfolio_heat_pct": 5.0, "max_daily_loss_pct": 3.0})
        == 3.0
    )
    assert (
        resolve_max_portfolio_heat_pct({"max_portfolio_heat_pct": 2.0, "max_daily_loss_pct": 3.0})
        == 2.0
    )


def test_allocate_shrinks_to_remaining_heat_without_raising_1pct():
    alloc = allocate_risk_pct(requested_risk_pct=1.0, open_heat_pct=2.4, max_heat_pct=3.0)
    assert alloc.allowed is True
    assert alloc.risk_pct == pytest.approx(0.6)
    assert alloc.risk_pct <= HARD_MAX_RISK_PCT


def test_allocate_blocks_when_heat_exhausted():
    alloc = allocate_risk_pct(requested_risk_pct=1.0, open_heat_pct=3.0, max_heat_pct=3.0)
    assert alloc.allowed is False
    assert alloc.reason == "portfolio_heat"


def test_open_heat_from_dollar_risks():
    assert open_heat_from_dollar_risks([100.0, 200.0], 10_000.0) == 3.0
    assert open_heat_from_dollar_risks([], 10_000.0) == 0.0
