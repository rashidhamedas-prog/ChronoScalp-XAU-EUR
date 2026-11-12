"""Best-effort alerting via Telegram and Discord webhooks.

Alerts are queued onto a bounded background worker so the trading loop never
blocks on network I/O. On overflow the oldest pending alert is dropped and a
counter is incremented (surfaced via the next successful send).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from chronoscalp.logging_setup import agent_debug_log, logger
from chronoscalp.utils.telegram_chat import DEFAULT_TRADE_OPEN_COPY_CHAT


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
    trade_open_copy_enabled: bool = True
    trade_open_copy_chat_id: str = DEFAULT_TRADE_OPEN_COPY_CHAT
    queue_size: int = 64


@dataclass(frozen=True)
class _QueuedAlert:
    kind: str  # telegram | discord
    body: str
    chat_id: str = ""


class AlertNotifier:
    """Sends formatted alerts to configured channels via a background queue."""

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
        self._copy_chat_id = (cfg.trade_open_copy_chat_id or "").strip()
        self._queue: queue.Queue[_QueuedAlert | None] = queue.Queue(
            maxsize=max(1, int(cfg.queue_size))
        )
        self._dropped = 0
        self._lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._worker_loop, name="chronoscalp-alerts", daemon=True
        )
        self._worker.start()

    @classmethod
    def from_settings(cls, alerting_cfg: dict[str, Any], secrets: Any) -> AlertNotifier:
        copy_chat = str(
            alerting_cfg.get("trade_open_copy_chat_id") or DEFAULT_TRADE_OPEN_COPY_CHAT
        ).strip()
        cfg = AlertConfig(
            enabled=bool(alerting_cfg.get("enabled", False)),
            telegram_enabled=bool(alerting_cfg.get("telegram_enabled", True)),
            discord_enabled=bool(alerting_cfg.get("discord_enabled", True)),
            timeout_seconds=float(alerting_cfg.get("timeout_seconds", 5)),
            prefix=str(alerting_cfg.get("prefix", "ChronoScalp")),
            trade_open_copy_enabled=bool(alerting_cfg.get("trade_open_copy_enabled", True)),
            trade_open_copy_chat_id=copy_chat or DEFAULT_TRADE_OPEN_COPY_CHAT,
            queue_size=int(alerting_cfg.get("queue_size", 64)),
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

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    def notify(
        self,
        title: str,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        *,
        copy_trade_open: bool = False,
    ) -> None:
        emoji = _LEVEL_EMOJI.get(level, "")
        body = f"{emoji} *{self._cfg.prefix}* — {title}\n{message}"
        discord_body = f"**{self._cfg.prefix}** — {title}\n{message}"

        if self._cfg.enabled:
            if self._cfg.telegram_enabled and self._telegram_token and self._telegram_chat_id:
                self._enqueue(
                    _QueuedAlert(kind="telegram", body=body, chat_id=self._telegram_chat_id)
                )
            if self._cfg.discord_enabled and self._discord_url:
                self._enqueue(_QueuedAlert(kind="discord", body=discord_body))

        if copy_trade_open:
            self._copy_trade_open(body)

    def notify_trade_opened(self, title: str, message: str) -> None:
        """Operator alert (if enabled) plus the configurable trade-open copy."""
        self.notify(title, message, AlertLevel.INFO, copy_trade_open=True)

    def _copy_trade_open(self, body: str) -> None:
        if not self._cfg.trade_open_copy_enabled:
            return
        if not self._telegram_token or not self._copy_chat_id:
            logger.warning("Trade-open Telegram copy skipped: token or chat id missing")
            return
        if (
            self._cfg.enabled
            and self._cfg.telegram_enabled
            and self._copy_chat_id == self._telegram_chat_id
        ):
            return
        self._enqueue(_QueuedAlert(kind="telegram", body=body, chat_id=self._copy_chat_id))

    def flush(self, timeout: float = 2.0) -> None:
        """Block until the alert queue is empty (tests / shutdown)."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            if self._queue.empty():
                # Give the worker a beat to finish the in-flight send.
                time.sleep(0.01)
                if self._queue.empty():
                    return
            time.sleep(0.01)

    def _enqueue(self, item: _QueuedAlert) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        # Drop-oldest: reclaim one slot, then enqueue the new alert.
        try:
            self._queue.get_nowait()
            with self._lock:
                self._dropped += 1
                dropped = self._dropped
        except queue.Empty:
            dropped = self._dropped
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._dropped += 1
                dropped = self._dropped
            logger.warning("Alert queue full — dropped alert (total_dropped={})", dropped)
            return
        logger.warning(
            "Alert queue overflow — dropped oldest (total_dropped={})",
            dropped,
        )

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                if item.kind == "telegram":
                    self._send_telegram(item.body, chat_id=item.chat_id)
                elif item.kind == "discord":
                    self._send_discord(item.body)
            except Exception:  # noqa: BLE001
                logger.exception("Alert worker failed for kind={}", item.kind)

    def _send_telegram(self, text: str, *, chat_id: str) -> None:
        import requests

        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            response = requests.post(url, json=payload, timeout=self._cfg.timeout_seconds)
            desc = ""
            try:
                desc = str((response.json() or {}).get("description") or "")[:120]
            except Exception:  # noqa: BLE001
                desc = (response.text or "")[:80]
            agent_debug_log(
                location="alerts.py:_send_telegram",
                message="Telegram sendMessage result",
                data={
                    "status": response.status_code,
                    "chat_kind": "username" if str(chat_id).startswith("@") else "numeric",
                    "parse_mode": "Markdown",
                    "description": desc,
                },
                hypothesis_id="E",
            )
            if response.status_code >= 400:
                logger.warning(
                    "Telegram alert failed: HTTP {} chat_id={} body={}",
                    response.status_code,
                    chat_id,
                    (response.text or "")[:300],
                )
        except requests.RequestException as exc:
            logger.warning(
                "Telegram alert failed chat_id={}: {}",
                chat_id,
                type(exc).__name__,
            )

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
