"""Best-effort alerting via Telegram and Discord webhooks.

Alerts are fire-and-forget: failures are logged but never propagate to the
trading loop. Secrets (tokens, webhook URLs) live only in .env.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from chronoscalp.logging_setup import logger


class AlertLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


_LEVEL_EMOJI = {
    AlertLevel.INFO: "ℹ️",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.ERROR: "❌",
    AlertLevel.CRITICAL: "🛑",
}


@dataclass(frozen=True)
class AlertConfig:
    enabled: bool = False
    telegram_enabled: bool = False
    discord_enabled: bool = False
    timeout_seconds: float = 5.0
    prefix: str = "ChronoScalp"


class AlertNotifier:
    """Sends formatted alerts to configured channels."""

    def __init__(
        self,
        cfg: AlertConfig,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        discord_webhook_url: str = "",
    ) -> None:
        self._cfg = cfg
        self._telegram_token = telegram_bot_token.strip()
        self._telegram_chat_id = telegram_chat_id.strip()
        self._discord_url = discord_webhook_url.strip()

    @classmethod
    def from_settings(cls, alerting_cfg: dict[str, Any], secrets: Any) -> AlertNotifier:
        cfg = AlertConfig(
            enabled=bool(alerting_cfg.get("enabled", False)),
            telegram_enabled=bool(alerting_cfg.get("telegram_enabled", True)),
            discord_enabled=bool(alerting_cfg.get("discord_enabled", True)),
            timeout_seconds=float(alerting_cfg.get("timeout_seconds", 5)),
            prefix=str(alerting_cfg.get("prefix", "ChronoScalp")),
        )
        return cls(
            cfg=cfg,
            telegram_bot_token=getattr(secrets, "telegram_bot_token", ""),
            telegram_chat_id=getattr(secrets, "telegram_chat_id", ""),
            discord_webhook_url=getattr(secrets, "discord_webhook_url", ""),
        )

    @property
    def is_configured(self) -> bool:
        if not self._cfg.enabled:
            return False
        has_telegram = (
            self._cfg.telegram_enabled
            and bool(self._telegram_token)
            and bool(self._telegram_chat_id)
        )
        has_discord = self._cfg.discord_enabled and bool(self._discord_url)
        return has_telegram or has_discord

    def notify(self, title: str, message: str, level: AlertLevel = AlertLevel.INFO) -> None:
        if not self._cfg.enabled:
            return

        emoji = _LEVEL_EMOJI.get(level, "")
        body = f"{emoji} *{self._cfg.prefix}* — {title}\n{message}"

        if self._cfg.telegram_enabled and self._telegram_token and self._telegram_chat_id:
            self._send_telegram(body)

        if self._cfg.discord_enabled and self._discord_url:
            self._send_discord(f"**{self._cfg.prefix}** — {title}\n{message}")

    def _send_telegram(self, text: str) -> None:
        import requests

        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        payload = {
            "chat_id": self._telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            response = requests.post(url, json=payload, timeout=self._cfg.timeout_seconds)
            if response.status_code >= 400:
                logger.warning("Telegram alert failed: HTTP {}", response.status_code)
        except requests.RequestException as exc:
            logger.warning("Telegram alert failed: {}", exc)

    def _send_discord(self, content: str) -> None:
        import requests

        try:
            response = requests.post(
                self._discord_url,
                json={"content": content[:2000]},
                timeout=self._cfg.timeout_seconds,
            )
            if response.status_code >= 400:
                logger.warning("Discord alert failed: HTTP {}", response.status_code)
        except requests.RequestException as exc:
            logger.warning("Discord alert failed: {}", exc)
