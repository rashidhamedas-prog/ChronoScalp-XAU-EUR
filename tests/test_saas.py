from __future__ import annotations

from pathlib import Path

import pytest
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
        ["delta", "liquidity_volume", "smc_confluence", "ultra_scalp", "news_straddle", "nope"],
        overrides_path=overrides,
    )
    assert modes == [
        "delta",
        "liquidity_volume",
        "smc_confluence",
        "ultra_scalp",
        "news_straddle",
    ]
    data2 = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data2["strategy"]["use_smc_confluence"] is True
    assert data2["strategy"]["use_liquidity_volume"] is True
    assert data2["strategy"]["use_ultra_scalp"] is True
    assert data2["strategy"]["use_news_straddle"] is True
    assert data2["strategy"]["use_delta"] is True
    assert data2["strategy"]["use_xau_vwap_pullback"] is False
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


def test_apply_xau_vwap_shadow_only(tmp_path: Path):
    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_enabled_strategies(
        ["delta"],
        shadow=["xau_vwap_pullback"],
        overrides_path=overrides,
    )
    assert "delta" in saved
    assert "xau_vwap_pullback" in saved
    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data["strategy"]["xau_vwap_pullback"]["shadow_only"] is True
    assert data["strategy"]["xau_vwap_pullback"]["enabled"] is True
    from chronoscalp.strategy.multi_timeframe import is_shadow_only, resolve_enabled_strategies

    enabled = resolve_enabled_strategies(data["strategy"])
    assert enabled.xau_vwap_pullback is True
    assert is_shadow_only(data["strategy"], "xau_vwap_pullback") is True


def test_overlay_news_straddle_resolves_enabled_after_reload(tmp_path: Path):
    """Saving News in the overlay is enough for resolve_enabled_strategies.

    The trading *process* still needs Stop/Start; this only checks settings reload.
    """
    overrides = tmp_path / "runtime_overrides.yaml"
    apply_enabled_strategies(["news_straddle"], overrides_path=overrides)
    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    from chronoscalp.strategy.multi_timeframe import resolve_enabled_strategies

    assert resolve_enabled_strategies(data["strategy"]).news_straddle is True


def test_apply_daily_loss_limit_enabled(tmp_path: Path):
    from chronoscalp.saas.broker_wizard import apply_daily_loss_limit_enabled

    overrides = tmp_path / "runtime_overrides.yaml"
    assert apply_daily_loss_limit_enabled(False, overrides_path=overrides) is False
    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data["risk"]["daily_loss_limit_enabled"] is False
    assert apply_daily_loss_limit_enabled(True, overrides_path=overrides) is True
    data2 = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data2["risk"]["daily_loss_limit_enabled"] is True


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


def test_apply_active_symbols_without_allowed_uses_symbols_yaml_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: bare uppercasing used to persist LiteFinance XAUUSD_O (untradeable)."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "symbols.yaml").write_text(
        "XAUUSD_o: {}\nEURUSD_o: {}\nBTCUSD: {}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_active_symbols(
        ["XAUUSD_O", "eurusd_o", "BTCUSD"],
        overrides_path=overrides,
        allowed=None,
    )
    assert saved == ["XAUUSD_o", "EURUSD_o", "BTCUSD"]


def test_user_config_roundtrip(tmp_path: Path):
    store = UserConfigStore(tmp_path / "user_config.json")
    store.config.broker.provider = "oanda"
    store.config.broker.onboarding_complete = True
    store.save()
    reloaded = UserConfigStore(tmp_path / "user_config.json")
    assert reloaded.config.broker.provider == "oanda"
    assert reloaded.config.broker.onboarding_complete is True


def test_apply_trade_open_copy_chat_and_toggle(tmp_path: Path) -> None:
    from chronoscalp.saas.broker_wizard import (
        apply_trade_open_copy_chat_id,
        apply_trade_open_copy_enabled,
    )

    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_trade_open_copy_chat_id("@taranomrashid", overrides_path=overrides)
    assert saved == "@taranomrashid"
    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data["alerting"]["trade_open_copy_chat_id"] == "@taranomrashid"
    assert data["alerting"]["trade_open_copy_enabled"] is True

    assert apply_trade_open_copy_enabled(False, overrides_path=overrides) is False
    data2 = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    assert data2["alerting"]["trade_open_copy_enabled"] is False
    assert data2["alerting"]["trade_open_copy_chat_id"] == "@taranomrashid"
