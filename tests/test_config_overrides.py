"""Tests for Demo/Shadow runtime_overrides validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chronoscalp.config_overrides import (
    RuntimeOverridesValidationError,
    validate_runtime_overrides,
)


def test_demo_shadow_example_validates() -> None:
    path = Path("config/runtime_overrides.demo_shadow.example.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = validate_runtime_overrides(payload)
    assert out["execution"]["broker"] == "paper"
    assert out["risk"]["active_risk_per_trade_pct"] == 0.25
    assert 1.5 in out["risk"]["risk_presets_pct"]
    assert "liquidity_volume" in out["strategy"]["enabled_strategies"]
    assert len(out["symbols"]) >= 2


def test_rejects_risk_above_hard_ceiling() -> None:
    with pytest.raises(RuntimeOverridesValidationError, match="hard ceiling"):
        validate_runtime_overrides({"risk": {"max_risk_per_trade_pct": 1.5}})


def test_rejects_rr_below_floor() -> None:
    with pytest.raises(RuntimeOverridesValidationError, match="hard floor"):
        validate_runtime_overrides({"risk": {"min_reward_risk_ratio": 1.0}})


def test_rejects_telegram_disabling_control_flags() -> None:
    with pytest.raises(RuntimeOverridesValidationError, match="Telegram"):
        validate_runtime_overrides({"control": {"remote_can_start_live": False}})


def test_preserves_legacy_risk_preset_list() -> None:
    out = validate_runtime_overrides(
        {
            "risk": {
                "max_risk_per_trade_pct": 1.0,
                "active_risk_per_trade_pct": 0.25,
                "risk_presets_pct": [0.25, 0.5, 1.0, 1.5],
            }
        }
    )
    assert out["risk"]["risk_presets_pct"][-1] == 1.5
