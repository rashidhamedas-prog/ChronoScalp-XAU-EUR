"""Tests for Demo/Shadow runtime_overrides validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chronoscalp.config_overrides import (
    UNENFORCED_OVERRIDE_KEYS,
    RuntimeOverridesValidationError,
    unenforced_override_keys,
    validate_runtime_overrides,
)

EXAMPLE_OVERLAY = Path("config/runtime_overrides.demo_shadow.example.yaml")


def test_demo_shadow_example_validates() -> None:
    payload = yaml.safe_load(EXAMPLE_OVERLAY.read_text(encoding="utf-8"))
    out = validate_runtime_overrides(payload)
    assert out["execution"]["broker"] == "paper"
    assert out["risk"]["active_risk_per_trade_pct"] == 0.25
    assert 1.5 in out["risk"]["risk_presets_pct"]
    assert "liquidity_volume" in out["strategy"]["enabled_strategies"]
    assert len(out["symbols"]) >= 2


def test_demo_shadow_example_keeps_delta_enabled() -> None:
    """A shadow overlay that drops delta silently disables the gold strategy."""
    payload = yaml.safe_load(EXAMPLE_OVERLAY.read_text(encoding="utf-8"))
    out = validate_runtime_overrides(payload)
    assert "delta" in out["strategy"]["enabled_strategies"]
    assert out["strategy"]["delta"]["allowed_symbols"] == ["XAUUSD"]


def test_unenforced_keys_reported_when_present() -> None:
    found = unenforced_override_keys(
        {
            "risk": {"max_trades_portfolio_day": 3, "max_daily_loss_pct": 1.0},
            "execution": {"single_instance": True, "broker": "paper"},
        }
    )
    assert found == ["execution.single_instance", "risk.max_trades_portfolio_day"]


def test_unenforced_keys_empty_for_enforced_only_overlay() -> None:
    assert unenforced_override_keys({"risk": {"max_daily_loss_pct": 1.0}}) == []
    assert unenforced_override_keys(None) == []


def test_every_unenforced_key_is_dotted_and_sorted() -> None:
    assert list(UNENFORCED_OVERRIDE_KEYS) == sorted(UNENFORCED_OVERRIDE_KEYS)
    assert all(key.count(".") == 1 for key in UNENFORCED_OVERRIDE_KEYS)


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


def test_xau_vwap_is_a_valid_runtime_strategy() -> None:
    out = validate_runtime_overrides(
        {
            "strategy": {
                "enabled_strategies": ["xau_vwap_pullback"],
                "use_xau_vwap_pullback": True,
            }
        }
    )
    assert out["strategy"]["enabled_strategies"] == ["xau_vwap_pullback"]
    assert out["strategy"]["use_xau_vwap_pullback"] is True


def test_heat_may_reach_daily_loss_but_not_exceed_it() -> None:
    out = validate_runtime_overrides(
        {"risk": {"max_daily_loss_pct": 3.0, "max_portfolio_heat_pct": 3.0}}
    )
    assert out["risk"]["max_portfolio_heat_pct"] == 3.0
    with pytest.raises(RuntimeOverridesValidationError, match="max_portfolio_heat_pct"):
        validate_runtime_overrides(
            {"risk": {"max_daily_loss_pct": 3.0, "max_portfolio_heat_pct": 4.0}}
        )


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


def test_alerting_trade_open_copy_normalized() -> None:
    out = validate_runtime_overrides(
        {
            "alerting": {
                "trade_open_copy_enabled": True,
                "trade_open_copy_chat_id": "taranomrashid",
            }
        }
    )
    assert out["alerting"]["trade_open_copy_enabled"] is True
    assert out["alerting"]["trade_open_copy_chat_id"] == "@taranomrashid"


def test_alerting_rejects_invalid_copy_chat() -> None:
    with pytest.raises(RuntimeOverridesValidationError, match="trade_open_copy_chat_id"):
        validate_runtime_overrides({"alerting": {"trade_open_copy_chat_id": "nope!"}})
