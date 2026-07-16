"""Typed configuration loader.

Strategy/risk parameters come from config/*.yaml (git-tracked). Secrets come
only from environment variables / .env (git-ignored). This split is
deliberate — see CLAUDE.md "Conventions".
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"


class Secrets(BaseSettings):
    """Loaded from environment / .env. Never log these values directly."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mt5_login: int = Field(default=0)
    mt5_password: str = Field(default="")
    mt5_server: str = Field(default="")
    mt5_terminal_path: str = Field(default="")

    chronoscalp_confirm_live: str = Field(default="no")
    chronoscalp_stop_trading: str = Field(default="no")
    news_api_key: str = Field(default="")
    sentry_dsn: str = Field(default="")
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    discord_webhook_url: str = Field(default="")
    oanda_api_token: str = Field(default="")
    oanda_account_id: str = Field(default="")
    license_admin_secret: str = Field(default="")
    chronoscalp_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    @property
    def live_trading_confirmed(self) -> bool:
        return self.chronoscalp_confirm_live.strip().lower() == "yes"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into a copy of ``base``."""
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    """Merged, typed access to config/settings.yaml + config/symbols.yaml."""

    def __init__(self) -> None:
        self.raw: dict[str, Any] = _load_yaml("settings.yaml")
        # Optional runtime overrides written by the user panel (broker mode, etc.)
        overrides_path = CONFIG_DIR / "runtime_overrides.yaml"
        if overrides_path.exists():
            with overrides_path.open(encoding="utf-8") as f:
                overlay = yaml.safe_load(f) or {}
            if isinstance(overlay, dict):
                self.raw = _deep_merge(self.raw, overlay)
        self.symbols_raw: dict[str, Any] = _load_yaml("symbols.yaml")
        self.secrets = Secrets()

    # --- convenience accessors -------------------------------------------------
    @property
    def symbols(self) -> list[str]:
        return list(self.raw.get("symbols", []))

    @property
    def risk(self) -> dict[str, Any]:
        return dict(self.raw.get("risk", {}))

    @property
    def sessions(self) -> dict[str, Any]:
        return dict(self.raw.get("sessions", {}))

    @property
    def indicators(self) -> dict[str, Any]:
        return dict(self.raw.get("indicators", {}))

    @property
    def strategy(self) -> dict[str, Any]:
        return dict(self.raw.get("strategy", {}))

    @property
    def news_filter(self) -> dict[str, Any]:
        return dict(self.raw.get("news_filter", {}))

    @property
    def spread_filter(self) -> dict[str, Any]:
        return dict(self.raw.get("spread_filter", {}))

    @property
    def execution(self) -> dict[str, Any]:
        return dict(self.raw.get("execution", {}))

    @property
    def backtest(self) -> dict[str, Any]:
        return dict(self.raw.get("backtest", {}))

    @property
    def alerting(self) -> dict[str, Any]:
        return dict(self.raw.get("alerting", {}))

    @property
    def resilience(self) -> dict[str, Any]:
        return dict(self.raw.get("resilience", {}))

    @property
    def ml(self) -> dict[str, Any]:
        return dict(self.raw.get("ml", {}))

    def symbol_spec(self, symbol: str) -> dict[str, Any]:
        spec = self.symbols_raw.get(symbol)
        if spec is None:
            raise KeyError(f"No contract spec for symbol '{symbol}' in config/symbols.yaml")
        return dict(spec)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Call get_settings.cache_clear() in tests
    if you need to reload after mutating config files on disk."""
    return Settings()
