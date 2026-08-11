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


def test_delta_is_a_valid_runtime_strategy() -> None:
    out = validate_runtime_overrides(
        {"strategy": {"enabled_strategies": ["delta"], "use_delta": True}}
    )
    assert out["strategy"]["enabled_strategies"] == ["delta"]
    assert out["strategy"]["use_delta"] is True


def test_mistake_memory_nested_validation() -> None:
    out = validate_runtime_overrides(
        {
            "risk": {
                "mistake_memory": {
                    "enabled": True,
                    "cooldown_minutes": 60,
                    "max_repeats": 2,
                    "min_loss_r": 0.5,
                    "match_session": True,
                    "match_exit_type": False,
                    "persist": True,
                }
            }
        }
    )
    mm = out["risk"]["mistake_memory"]
    assert mm["enabled"] is True
    assert mm["cooldown_minutes"] == 60
    assert mm["max_repeats"] == 2
    assert mm["min_loss_r"] == 0.5
    assert mm["match_exit_type"] is False


def test_mistake_memory_rejects_cooldown_below_one() -> None:
    with pytest.raises(RuntimeOverridesValidationError, match="cooldown_minutes"):
        validate_runtime_overrides({"risk": {"mistake_memory": {"cooldown_minutes": 0}}})
