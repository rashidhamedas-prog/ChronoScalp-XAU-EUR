from __future__ import annotations

from pathlib import Path

import yaml

from chronoscalp.saas.broker_wizard import _upsert_env, apply_broker_to_settings_yaml
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


def test_user_config_roundtrip(tmp_path: Path):
    store = UserConfigStore(tmp_path / "user_config.json")
    store.config.broker.provider = "oanda"
    store.config.broker.onboarding_complete = True
    store.save()
    reloaded = UserConfigStore(tmp_path / "user_config.json")
    assert reloaded.config.broker.provider == "oanda"
    assert reloaded.config.broker.onboarding_complete is True
