from __future__ import annotations

from pathlib import Path

from chronoscalp.saas.broker_wizard import apply_enabled_strategies
from chronoscalp.strategy.live_gates import (
    blocks_real_live_orders,
    force_shadow_if_not_live_ready,
    is_strategy_live_ready,
)
from chronoscalp.strategy.multi_timeframe import is_shadow_only


def test_xau_is_not_live_ready_by_default():
    cfg = {"xau_vwap_pullback": {"enabled": True, "shadow_only": False, "live_ready": False}}
    assert is_strategy_live_ready(cfg, "xau_vwap_pullback") is False
    assert is_strategy_live_ready(cfg, "delta") is True
    assert force_shadow_if_not_live_ready(
        "xau_vwap_pullback", strategy_cfg=cfg, requested_shadow=False
    )
    assert blocks_real_live_orders(cfg, "xau_vwap_pullback", mode="live", shadow_only=False)


def test_apply_enabled_strategies_cannot_live_enable_xau(tmp_path: Path):
    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_enabled_strategies(
        ["delta", "xau_vwap_pullback"],
        overrides_path=overrides,
    )
    assert "xau_vwap_pullback" in saved
    import yaml

    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    xau = data["strategy"]["xau_vwap_pullback"]
    assert xau["shadow_only"] is True
    assert xau.get("live_ready") is False
    assert is_shadow_only(data["strategy"], "xau_vwap_pullback") is True
