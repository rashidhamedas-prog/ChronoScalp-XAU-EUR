"""Telegram control plane for ChronoScalp (start/stop, status, P&L, kill switch).

Mirrors the user-panel process controls via long-polling. Requires
``TELEGRAM_BOT_TOKEN`` in ``.env``. When ``TELEGRAM_CHAT_ID`` is set, only that
chat may issue commands (recommended for production).

Live start still requires ``CHRONOSCALP_CONFIRM_LIVE=yes`` — this bot never
bypasses that gate.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from chronoscalp.config import Settings, get_settings
from chronoscalp.logging_setup import logger
from chronoscalp.orchestration.kill_switch import KillSwitch
from chronoscalp.orchestration.trade_journal import load_journal_snapshot
from chronoscalp.saas.process_control import (
    PID_FILE,
    bot_is_running,
    bot_pid,
    start_bot,
    stop_bot,
    tail_logs,
)
from chronoscalp.saas.user_config import UserConfigStore

API = "https://api.telegram.org/bot{token}/{method}"

# Reply-keyboard labels (Persian) — also accepted as free-text commands.
BTN_STATUS = "وضعیت"
BTN_PNL = "سود/زیان"
BTN_OPEN = "پوزیشن‌ها"
BTN_START_PAPER = "استارت Paper"
BTN_START_LIVE = "استارت Live"
BTN_STOP_BOT = "توقف ربات"
BTN_HALT = "توقف ورود"
BTN_RESUME = "ادامه ورود"
BTN_LOGS = "لاگ"
BTN_HELP = "راهنما"

MAIN_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": BTN_STATUS}, {"text": BTN_PNL}, {"text": BTN_OPEN}],
        [{"text": BTN_START_PAPER}, {"text": BTN_START_LIVE}, {"text": BTN_STOP_BOT}],
        [{"text": BTN_HALT}, {"text": BTN_RESUME}],
        [{"text": BTN_LOGS}, {"text": BTN_HELP}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

HELP_TEXT = (
    "ChronoScalp — کنترل از تلگرام\n\n"
    "دکمه‌ها یا دستورها:\n"
    "/status — وضعیت فرآیند + kill switch\n"
    "/start_paper — شروع ربات (paper)\n"
    "/start_live — شروع ربات (live؛ نیاز به تأیید .env)\n"
    "/bot_stop — توقف فرآیند ربات\n"
    "/pnl — آمار سود/زیان\n"
    "/open — پوزیشن‌های باز\n"
    "/halt — توقف ورود جدید (kill switch)\n"
    "/resume — برداشتن kill switch\n"
    "/logs — آخرین خطوط لاگ\n"
    "/whoami — شناسه چت شما\n"
    "/help — همین راهنما\n\n"
    "نکته: Live بدون CHRONOSCALP_CONFIRM_LIVE=yes استارت نمی‌شود."
)

# Map button labels / command aliases → canonical command key.
_ALIASES: dict[str, str] = {
    "/start": "help",
    "/help": "help",
    BTN_HELP: "help",
    "راهنما": "help",
    "/whoami": "whoami",
    "/status": "status",
    BTN_STATUS: "status",
    "وضعیت": "status",
    "/pnl": "pnl",
    BTN_PNL: "pnl",
    "سود/زیان": "pnl",
    "/open": "open",
    BTN_OPEN: "open",
    "پوزیشن‌ها": "open",
    "/start_paper": "start_paper",
    BTN_START_PAPER: "start_paper",
    "استارت paper": "start_paper",
    "/start_live": "start_live",
    BTN_START_LIVE: "start_live",
    "استارت live": "start_live",
    "/bot_stop": "bot_stop",
    "/stop_bot": "bot_stop",
    BTN_STOP_BOT: "bot_stop",
    "توقف ربات": "bot_stop",
    "/halt": "halt",
    "/stop": "halt",  # backward-compatible kill-switch alias
    BTN_HALT: "halt",
    "توقف ورود": "halt",
    "/resume": "resume",
    BTN_RESUME: "resume",
    "ادامه ورود": "resume",
    "/logs": "logs",
    BTN_LOGS: "logs",
    "لاگ": "logs",
}


class TelegramControlBot:
    """Long-polling Telegram bot that controls ChronoScalp on the host."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        start_fn: Callable[[str], tuple[bool, str]] | None = None,
        stop_fn: Callable[[], tuple[bool, str]] | None = None,
        running_fn: Callable[[], bool] | None = None,
        pid_fn: Callable[[], int | None] | None = None,
        logs_fn: Callable[[int], list[str]] | None = None,
        license_check: Callable[[Settings], Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.token = self.settings.secrets.telegram_bot_token.strip()
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing in .env")
        self.allowed_chat = self.settings.secrets.telegram_chat_id.strip()
        self.state_dir = Path(self.settings.execution.get("state_dir", "data/state"))
        self.pid_file = PID_FILE
        self.timeout = float(self.settings.alerting.get("timeout_seconds", 5))
        self.reference_equity = float(self.settings.backtest.get("initial_balance", 10_000))
        self.kill = KillSwitch(
            state_dir=self.state_dir,
            env_stop=self.settings.secrets.chronoscalp_stop_trading,
        )
        self.offset = 0
        self._start_fn = start_fn or (lambda mode: start_bot(mode=mode, pid_file=self.pid_file))
        self._stop_fn = stop_fn or (lambda: stop_bot(pid_file=self.pid_file))
        self._running_fn = running_fn or (lambda: bot_is_running(self.pid_file))
        self._pid_fn = pid_fn or (lambda: bot_pid(self.pid_file))
        self._logs_fn = logs_fn or (lambda n: tail_logs(n))
        self._license_check = license_check

    def _detect_mode(self) -> str:
        if (self.state_dir / "trade_journal_live.json").exists():
            return "live"
        if (self.state_dir / "trade_journal_paper.json").exists():
            return "paper"
        try:
            user_mode = UserConfigStore().config.broker.mode
            if user_mode in ("paper", "live"):
                return user_mode
        except OSError:
            pass
        return "paper"

    def _api(self, method: str, **params: Any) -> dict[str, Any]:
        """POST to Telegram Bot API with explicit UTF-8 JSON (Persian-safe)."""
        url = API.format(token=self.token, method=method)
        body = json.dumps(params, ensure_ascii=False).encode("utf-8")
        response = requests.post(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=max(35.0, self.timeout),
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data

    def send(
        self,
        chat_id: str | int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """Send a plain-text message (no Markdown — avoids underscore breakage)."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4000],
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            self._api("sendMessage", **payload)
        except Exception:  # noqa: BLE001
            logger.exception("Telegram sendMessage failed chat_id={}", chat_id)
            raise

    def _authorized(self, chat_id: str | int) -> bool:
        if not self.allowed_chat:
            return True
        return str(chat_id) == str(self.allowed_chat)

    def _bind_chat_if_needed(self, chat_id: int) -> None:
        """Persist first controller chat id when TELEGRAM_CHAT_ID is empty."""
        if self.allowed_chat:
            return
        chat_s = str(chat_id)
        try:
            from chronoscalp.saas.broker_wizard import save_telegram_credentials

            save_telegram_credentials(self.token, chat_s)
            self.allowed_chat = chat_s
            logger.info("Bound TELEGRAM_CHAT_ID to {}", chat_s)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist TELEGRAM_CHAT_ID")

    def _resolve_command(self, text: str) -> str | None:
        raw = (text or "").strip()
        if not raw:
            return None
        # Strip @BotUsername from /cmd@BotUsername
        first = raw.split()[0]
        if first.startswith("/") and "@" in first:
            first = first.split("@", 1)[0]
        key = first.lower() if first.startswith("/") else first
        # Normalize Persian button labels (exact + lowercased latin cmds)
        if key in _ALIASES:
            return _ALIASES[key]
        lowered = key.lower()
        if lowered in _ALIASES:
            return _ALIASES[lowered]
        return _ALIASES.get(raw) or _ALIASES.get(raw.lower())

    def _cmd_help(self, chat_id: int) -> None:
        self.send(chat_id, HELP_TEXT, reply_markup=MAIN_KEYBOARD)

    def _cmd_whoami(self, chat_id: int) -> None:
        self.send(
            chat_id,
            f"chat_id = {chat_id}\nاین مقدار را در .env به‌صورت TELEGRAM_CHAT_ID بگذارید.",
        )

    def _cmd_status(self, chat_id: int) -> None:
        running = self._running_fn()
        pid = self._pid_fn() if running else None
        mode = self._detect_mode()
        ks = "ACTIVE" if self.kill.is_active() else "off"
        reason = self.kill.reason() if self.kill.is_active() else "—"
        broker = self.settings.execution.get("broker", "?")
        symbols = ", ".join(self.settings.symbols) if self.settings.symbols else "—"
        live_ok = "yes" if self.settings.secrets.live_trading_confirmed else "no"
        lines = [
            "وضعیت ChronoScalp",
            f"فرآیند: {'در حال اجرا' if running else 'متوقف'}"
            + (f" (PID {pid})" if pid else ""),
            f"حالت ژورنال: {mode}",
            f"بروکر: {broker}",
            f"نمادها: {symbols}",
            f"kill_switch: {ks}",
            f"دلیل: {reason}",
            f"تأیید Live (.env): {live_ok}",
        ]
        self.send(chat_id, "\n".join(lines))

    def _cmd_pnl(self, chat_id: int) -> None:
        mode = self._detect_mode()
        snap = load_journal_snapshot(
            self.state_dir, mode, reference_equity=self.reference_equity
        )
        s = snap.stats
        self.send(
            chat_id,
            (
                f"P&L ({mode})\n"
                f"net={s.net_pnl:+.2f}  today={s.today_pnl:+.2f}\n"
                f"closed={s.closed_trades}  open={s.open_trades}\n"
                f"win_rate={s.win_rate_pct:.1f}%  avg={s.avg_pnl:+.2f}\n"
                f"PF={s.profit_factor}  expectancy={s.expectancy:+.2f}"
            ),
        )

    def _cmd_open(self, chat_id: int) -> None:
        mode = self._detect_mode()
        snap = load_journal_snapshot(self.state_dir, mode)
        if not snap.open_trades:
            self.send(chat_id, "پوزیشن بازی نیست.")
            return
        lines = [
            f"{t.symbol} {t.direction} vol={t.volume} @{t.entry_price}"
            for t in snap.open_trades
        ]
        self.send(chat_id, "پوزیشن‌های باز:\n" + "\n".join(lines))

    def _ensure_license(self) -> str | None:
        """Return an error message when license check fails, else None."""
        checker = self._license_check
        if checker is None:
            try:
                from chronoscalp.licensing import require_valid_license

                checker = require_valid_license
            except Exception:  # noqa: BLE001
                return None
        try:
            checker(self.settings)
        except RuntimeError as exc:
            return str(exc)
        return None

    def _cmd_start_paper(self, chat_id: int) -> None:
        err = self._ensure_license()
        if err:
            self.send(chat_id, f"لایسنس: {err}")
            return
        ok, msg = self._start_fn("paper")
        self.send(chat_id, ("✅ " if ok else "❌ ") + msg)

    def _cmd_start_live(self, chat_id: int) -> None:
        if not self.settings.secrets.live_trading_confirmed:
            self.send(
                chat_id,
                "❌ حالت Live نیاز به CHRONOSCALP_CONFIRM_LIVE=yes در .env دارد.\n"
                "از پنل کنترل تأیید کنید یا .env را دستی تنظیم کنید — این گیت عمدی است.",
            )
            return
        err = self._ensure_license()
        if err:
            self.send(chat_id, f"لایسنس: {err}")
            return
        ok, msg = self._start_fn("live")
        self.send(chat_id, ("✅ " if ok else "❌ ") + msg)

    def _cmd_bot_stop(self, chat_id: int) -> None:
        ok, msg = self._stop_fn()
        self.send(chat_id, ("✅ " if ok else "⚠️ ") + msg)

    def _cmd_halt(self, chat_id: int) -> None:
        self.kill.activate("telegram /halt")
        self.send(chat_id, "🛑 Kill switch فعال شد — ورود جدید متوقف است.")

    def _cmd_resume(self, chat_id: int) -> None:
        self.kill.deactivate()
        self.send(chat_id, "✅ Kill switch برداشته شد.")

    def _cmd_logs(self, chat_id: int) -> None:
        lines = self._logs_fn(25)
        if not lines:
            self.send(chat_id, "لاگی پیدا نشد.")
            return
        body = "\n".join(lines)
        if len(body) > 3800:
            body = body[-3800:]
        self.send(chat_id, f"آخرین لاگ:\n{body}")

    def handle(self, chat_id: int, text: str) -> None:
        """Dispatch one inbound message."""
        logger.info("Telegram cmd from chat_id={} text={!r}", chat_id, (text or "")[:80])
        if not self._authorized(chat_id):
            self.send(chat_id, "⛔ Unauthorized chat.")
            return

        self._bind_chat_if_needed(chat_id)

        cmd = self._resolve_command(text)
        if cmd is None:
            self.send(chat_id, "دستور ناشناخته. /help را بزنید.", reply_markup=MAIN_KEYBOARD)
            return

        handlers: dict[str, Callable[[int], None]] = {
            "help": self._cmd_help,
            "whoami": self._cmd_whoami,
            "status": self._cmd_status,
            "pnl": self._cmd_pnl,
            "open": self._cmd_open,
            "start_paper": self._cmd_start_paper,
            "start_live": self._cmd_start_live,
            "bot_stop": self._cmd_bot_stop,
            "halt": self._cmd_halt,
            "resume": self._cmd_resume,
            "logs": self._cmd_logs,
        }
        handlers[cmd](chat_id)

    def run_forever(self) -> None:
        """Block forever, long-polling Telegram updates."""
        try:
            self._api("deleteWebhook", drop_pending_updates=False)
            logger.info("Telegram webhook cleared (long-poll mode)")
        except Exception:  # noqa: BLE001
            logger.warning("deleteWebhook failed — continuing with getUpdates")

        logger.info(
            "Telegram control bot started (allow_chat={})",
            self.allowed_chat or "*",
        )
        while True:
            try:
                data = self._api(
                    "getUpdates",
                    offset=self.offset,
                    timeout=25,
                    allowed_updates=["message"],
                )
                for upd in data.get("result") or []:
                    self.offset = int(upd["update_id"]) + 1
                    msg = upd.get("message") or {}
                    text = msg.get("text") or ""
                    chat = msg.get("chat") or {}
                    chat_id = chat.get("id")
                    if chat_id is None or not text:
                        continue
                    try:
                        self.handle(int(chat_id), text)
                    except Exception:  # noqa: BLE001
                        logger.exception("Failed handling telegram message")
            except requests.RequestException as exc:
                logger.warning("Telegram poll error: {}", exc)
                time.sleep(5)
            except Exception:  # noqa: BLE001
                logger.exception("Telegram bot loop error")
                time.sleep(5)
