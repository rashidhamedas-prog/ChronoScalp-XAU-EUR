from __future__ import annotations

from pathlib import Path

import yaml

from chronoscalp.saas.broker_wizard import (
    _upsert_env,
    apply_active_symbols,
    apply_broker_to_settings_yaml,
    apply_enabled_strategies,
)
from chronoscalp.saas.user_config import UserConfigStore


def test_upsert_env_preserves_other_keys(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("FOO=1\nBAR=2\n", encoding="utf-8")
    _upsert_env(env, {"BAR": "9", "OANDA_API_TOKEN": "tok"})
    text = env.read_text(encoding="utf-8")
    assert "FOO=1" in text
    assert "BAR=9" in text
    assert "OANDA_API_TOKEN=tok" in text


def test_apply_broker_writes_overrides(tmp_path: Path):
    overrides = tmp_path / "runtime_overrides.yaml"
    apply_broker_to_settings_yaml("oanda", "paper", "practice", overrides_path=overrides)
    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data["execution"]["broker"] == "paper"
    assert data["execution"]["data_source"] == "oanda"
    assert data["oanda"]["environment"] == "practice"


def test_apply_active_symbols_and_strategies(tmp_path: Path):
    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_active_symbols(
        ["ethusd", "USDJPY", "USDJPY"],
        overrides_path=overrides,
        allowed=["ETHUSD", "USDJPY", "XAUUSD"],
    )
    assert saved == ["ETHUSD", "USDJPY"]
    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data["symbols"] == ["ETHUSD", "USDJPY"]

    modes = apply_enabled_strategies(
        ["liquidity_volume", "smc_confluence", "ultra_scalp", "nope"],
        overrides_path=overrides,
    )
    assert modes == ["liquidity_volume", "smc_confluence", "ultra_scalp"]
    data2 = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data2["strategy"]["use_smc_confluence"] is True
    assert data2["strategy"]["use_liquidity_volume"] is True
    assert data2["strategy"]["use_ultra_scalp"] is True
    assert data2["symbols"] == ["ETHUSD", "USDJPY"]  # preserved

    from chronoscalp.saas.broker_wizard import apply_trading_hours_mode

    mode = apply_trading_hours_mode("24h", overrides_path=overrides)
    assert mode == "always_on_24h"
    data3 = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data3["sessions"]["trading_hours_mode"] == "always_on_24h"
    assert data3["sessions"]["trade_outside_sessions"] is True

    mode2 = apply_trading_hours_mode("london_ny", overrides_path=overrides)
    assert mode2 == "london_ny"
    data4 = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data4["sessions"]["trading_hours_mode"] == "london_ny"
    assert data4["sessions"]["trade_outside_sessions"] is False


def test_apply_active_symbols_preserves_broker_symbol_case(tmp_path: Path):
    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_active_symbols(
        ["xauusd_o", "eurusd_o", "XAUUSD_O"],
        overrides_path=overrides,
        allowed=["XAUUSD_o", "EURUSD_o", "USDJPY_o"],
    )
    assert saved == ["XAUUSD_o", "EURUSD_o"]
    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data["symbols"] == ["XAUUSD_o", "EURUSD_o"]


def test_user_config_roundtrip(tmp_path: Path):
    store = UserConfigStore(tmp_path / "user_config.json")
    store.config.broker.provider = "oanda"
    store.config.broker.onboarding_complete = True
    store.save()
    reloaded = UserConfigStore(tmp_path / "user_config.json")
    assert reloaded.config.broker.provider == "oanda"
    assert reloaded.config.broker.onboarding_complete is True
