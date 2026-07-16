"""Per-user preferences and broker connection profile (git-ignored)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_USER_CONFIG_PATH = Path("data/user/user_config.json")


@dataclass
class BrokerProfile:
    """User-facing broker connection settings (secrets stored separately in .env)."""

    provider: str = "oanda"  # oanda | mt5 | paper
    mode: str = "paper"  # paper | live
    oanda_environment: str = "practice"
    onboarding_complete: bool = False
    ib_referral_acknowledged: bool = False
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrokerProfile:
        return cls(
            provider=str(data.get("provider") or "oanda"),
            mode=str(data.get("mode") or "paper"),
            oanda_environment=str(data.get("oanda_environment") or "practice"),
            onboarding_complete=bool(data.get("onboarding_complete", False)),
            ib_referral_acknowledged=bool(data.get("ib_referral_acknowledged", False)),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass
class UserConfig:
    """Local user portal state."""

    broker: BrokerProfile = field(default_factory=BrokerProfile)
    display_name: str = ""
    language: str = "fa"
    telegram_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker": self.broker.to_dict(),
            "display_name": self.display_name,
            "language": self.language,
            "telegram_enabled": self.telegram_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserConfig:
        return cls(
            broker=BrokerProfile.from_dict(data.get("broker") or {}),
            display_name=str(data.get("display_name") or ""),
            language=str(data.get("language") or "fa"),
            telegram_enabled=bool(data.get("telegram_enabled", False)),
        )


class UserConfigStore:
    """Load/save ``data/user/user_config.json``."""

    def __init__(self, path: str | Path = DEFAULT_USER_CONFIG_PATH) -> None:
        self.path = Path(path)
        self.config = UserConfig()
        self.load()

    def load(self) -> UserConfig:
        if not self.path.exists():
            self.config = UserConfig()
            return self.config
        with self.path.open(encoding="utf-8") as f:
            self.config = UserConfig.from_dict(json.load(f))
        return self.config

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.config.broker.updated_at = datetime.now(tz=UTC).isoformat()
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.config.to_dict(), f, indent=2, ensure_ascii=False)
