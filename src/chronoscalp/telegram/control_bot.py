"""Telegram control plane for ChronoScalp.

Covers process start/stop, P&L, kill switch, broker connection, and
panel-equivalent control settings (symbols / strategies / risk / live gate).

Live start still requires ``CHRONOSCALP_CONFIRM_LIVE=yes`` — this bot never
bypasses that gate; ``/live_confirm yes`` is an explicit operator action
(same as the Streamlit panel).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from chronoscalp.config import Settings, get_settings
from chronoscalp.logging_setup import logger
from chronoscalp.orchestration.kill_switch import KillSwitch
from chronoscalp.orchestration.trade_journal import load_journal_snapshot, write_daily_reset_marker
from chronoscalp.saas.broker_wizard import (
    apply_active_symbols,
    apply_broker_to_settings_yaml,
    apply_daily_loss_limit_enabled,
    apply_enabled_strategies,
    apply_mistake_memory_enabled,
    apply_risk_preset,
    apply_trade_open_copy_chat_id,
    apply_trade_open_copy_enabled,
    apply_trading_hours_mode,
    disable_live_confirm,
    enable_live_confirm,
    save_mt5_credentials,
    save_oanda_credentials,
    test_mt5_connection,
    test_oanda_connection,
)
from chronoscalp.saas.process_control import (
    PID_FILE,
    bot_is_running,
    bot_pid,
    start_bot,
    stop_bot,
    tail_logs,
)
from chronoscalp.saas.user_config import UserConfigStore
from chronoscalp.telegram.keyboards import (
    ALIASES,
    CONN_KEYBOARD,
    CONTROL_KEYBOARD,
    HELP_TEXT,
    MAIN_KEYBOARD,
    OANDA_ENV_KEYBOARD,
    SETTINGS_KEYBOARD,
    STRATEGY_LABEL_TO_KEY,
    STRATEGY_LABELS,
    hours_keyboard,
    parse_toggle_label,
    risk_keyboard,
    strategies_keyboard,
    symbols_keyboard,
    trade_notify_keyboard,
)

API = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"


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
        self._settings_injected = settings is not None
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
        self._pending: dict[int, dict[str, Any]] = {}
        self._start_fn = start_fn or (lambda mode: start_bot(mode=mode, pid_file=self.pid_file))
        self._stop_fn = stop_fn or (lambda: stop_bot(pid_file=self.pid_file))
        self._running_fn = running_fn or (lambda: bot_is_running(self.pid_file))
        self._pid_fn = pid_fn or (lambda: bot_pid(self.pid_file))
        self._logs_fn = logs_fn or (lambda n: tail_logs(n))
        self._license_check = license_check

    def _reload_settings(self) -> None:
        if self._settings_injected:
            return
        get_settings.cache_clear()
        self.settings = get_settings()
        self.allowed_chat = self.settings.secrets.telegram_chat_id.strip() or self.allowed_chat
        self.kill = KillSwitch(
            state_dir=Path(self.settings.execution.get("state_dir", "data/state")),
            env_stop=self.settings.secrets.chronoscalp_stop_trading,
        )

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
        first = raw.split()[0]
        if first.startswith("/") and "@" in first:
            first = first.split("@", 1)[0]
        key = first.lower() if first.startswith("/") else first
        if key in ALIASES:
            return ALIASES[key]
        lowered = key.lower()
        if lowered in ALIASES:
            return ALIASES[lowered]
        return ALIASES.get(raw) or ALIASES.get(raw.lower())

    def _args(self, text: str) -> list[str]:
        parts = (text or "").strip().split()
        if not parts:
            return []
        # Drop command token
        return parts[1:]

    # --- core ops ---

    def _cmd_help(self, chat_id: int, _text: str = "") -> None:
        self.send(chat_id, HELP_TEXT, reply_markup=MAIN_KEYBOARD)

    def _trading_hours_label(self) -> str:
        sessions = getattr(self.settings, "sessions", None) or {}
        if callable(sessions):
            try:
                sessions = sessions()
            except TypeError:
                sessions = {}
        if not isinstance(sessions, dict):
            sessions = {}
        from chronoscalp.filters.session_filter import normalize_trading_hours_mode

        hours = normalize_trading_hours_mode(sessions.get("trading_hours_mode"))
        return {
            "london_ny": "سشن لندن/آمریکا",
            "always_on_24h": "۲۴ ساعته",
        }.get(hours, hours)

    def _cmd_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            f"منوی اصلی\nساعات معامله: {self._trading_hours_label()}",
            reply_markup=MAIN_KEYBOARD,
        )

    def _cmd_settings(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self._reload_settings()
        self.send(
            chat_id,
            "⚙️ تنظیمات — همه گزینه‌ها از منو (بدون تایپ).\n"
            f"ساعات فعلی: {self._trading_hours_label()}\n"
            "نماد · استراتژی · ساعات · ریسک · اعلان معامله · اتصال · تأیید Live",
            reply_markup=SETTINGS_KEYBOARD,
        )

    def _cmd_conn_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(chat_id, "تنظیمات اتصال", reply_markup=CONN_KEYBOARD)

    def _cmd_control_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            "تنظیمات کنترل — از دکمه‌ها انتخاب کنید (بدون تایپ):\n"
            f"ساعات فعلی: {self._trading_hours_label()}",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _cmd_hours_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            f"ساعات معامله را انتخاب کنید:\nفعلی: {self._trading_hours_label()}",
            reply_markup=hours_keyboard(),
        )

    def _daily_loss_enabled(self) -> bool:
        return bool(self.settings.risk.get("daily_loss_limit_enabled", True))

    def _mistake_memory_enabled(self) -> bool:
        mm = self.settings.risk.get("mistake_memory") or {}
        if not isinstance(mm, dict):
            return True
        return bool(mm.get("enabled", True))

    def _mistake_memory_cooldown_minutes(self) -> int:
        mm = self.settings.risk.get("mistake_memory") or {}
        if not isinstance(mm, dict):
            return 240
        try:
            return int(mm.get("cooldown_minutes", 240))
        except (TypeError, ValueError):
            return 240

    def _risk_keyboard(self) -> dict:
        return risk_keyboard(
            daily_loss_enabled=self._daily_loss_enabled(),
            mistake_memory_enabled=self._mistake_memory_enabled(),
        )

    def _cmd_risk_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self._reload_settings()
        enabled = self._daily_loss_enabled()
        status = "روشن ✅" if enabled else "خاموش ⬜"
        mm_enabled = self._mistake_memory_enabled()
        mm_status = "روشن ✅" if mm_enabled else "خاموش ⬜"
        cooldown = self._mistake_memory_cooldown_minutes()
        self.send(
            chat_id,
            "ریسک هر معامله را انتخاب کنید:\n"
            "۰٫۵٪ / ۱٪ / ۱٫۵٪ — سقف امن پروژه ۱٪ است (۱٫۵٪ → ۱٪).\n\n"
            f"قفل ضرر روزانه: {status}\n"
            f"سقف ضرر روز: {float(self.settings.risk.get('max_daily_loss_pct', 3.0))}%\n"
            f"یادگیری از اشتباه: {mm_status}\n"
            f"کول‌داون: {cooldown} دقیقه",
            reply_markup=self._risk_keyboard(),
        )

    def _cmd_whoami(self, chat_id: int, _text: str = "") -> None:
        self.send(
            chat_id,
            f"chat_id = {chat_id}\nاین مقدار را در .env به‌صورت TELEGRAM_CHAT_ID بگذارید.",
        )

    def _cmd_status(self, chat_id: int, _text: str = "") -> None:
        running = self._running_fn()
        pid = self._pid_fn() if running else None
        mode = self._detect_mode()
        ks = "ACTIVE" if self.kill.is_active() else "off"
        reason = self.kill.reason() if self.kill.is_active() else "—"
        broker = self.settings.execution.get("broker", "?")
        symbols = ", ".join(self.settings.symbols) if self.settings.symbols else "—"
        strategies = ", ".join(self._current_strategies()) or "(MACD/trend only)"
        live_ok = "yes" if self.settings.secrets.live_trading_confirmed else "no"
        mm = "on" if self._mistake_memory_enabled() else "off"
        user = UserConfigStore().config
        lines = [
            "وضعیت ChronoScalp",
            f"فرآیند: {'در حال اجرا' if running else 'متوقف'}" + (f" (PID {pid})" if pid else ""),
            f"حالت ژورنال: {mode}",
            f"پروفایل: provider={user.broker.provider} mode={user.broker.mode}",
            f"بروکر اجرا: {broker}",
            f"نمادها: {symbols}",
            f"استراتژی‌ها: {strategies}",
            f"kill_switch: {ks}",
            f"دلیل: {reason}",
            f"تأیید Live (.env): {live_ok}",
            f"mistake_memory={mm}",
        ]
        self.send(chat_id, "\n".join(lines), reply_markup=MAIN_KEYBOARD)

    def _cmd_pnl(self, chat_id: int, _text: str = "") -> None:
        mode = self._detect_mode()
        snap = load_journal_snapshot(self.state_dir, mode, reference_equity=self.reference_equity)
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

    def _cmd_open(self, chat_id: int, _text: str = "") -> None:
        rows, account = self._load_live_open_positions()
        if rows is not None:
            if not rows:
                self.send(chat_id, self._empty_broker_positions_message(account))
                return
            lines = [
                (
                    f"#{r.get('ticket')} {r.get('symbol')} {r.get('direction')} "
                    f"vol={r.get('volume')} @{r.get('entry_price')} "
                    f"pnl={float(r.get('profit') or 0):+.2f}"
                )
                for r in rows
            ]
            header = "پوزیشن‌های باز (زنده از بروکر):"
            hint = self._format_account_hint(account)
            if hint:
                header = f"{header}\n{hint}"
            self.send(chat_id, header + "\n" + "\n".join(lines))
            return

        mode = self._detect_mode()
        snap = load_journal_snapshot(self.state_dir, mode)
        if not snap.open_trades:
            self.send(
                chat_id,
                "پوزیشن بازی در ژورنال نیست.\n"
                "(خواندن زنده از بروکر ممکن نشد — لاگ/اتصال MT5 را چک کنید)",
            )
            return
        lines = [
            f"#{t.ticket} {t.symbol} {t.direction} vol={t.volume} @{t.entry_price}"
            for t in snap.open_trades
        ]
        self.send(chat_id, "پوزیشن‌های باز (ژورنال):\n" + "\n".join(lines))

    def _empty_broker_positions_message(self, account: dict | None = None) -> str:
        """Persian empty-state with account identity so operators can cross-check MT5."""
        lines = ["پوزیشن بازی روی بروکر نیست."]
        hint = self._format_account_hint(account)
        if hint:
            lines.append(hint)
        lines.append(
            "اگر در ترمینال پوزیشن می‌بینید، همان login/server دمو را با ربات مقایسه کنید "
            "(Trade → Positions، نه History)."
        )
        return "\n".join(lines)

    @staticmethod
    def _format_account_hint(account: dict | None) -> str:
        if not account:
            return ""
        login = account.get("login") or ""
        server = account.get("server") or ""
        parts: list[str] = []
        if login:
            parts.append(f"login={login}")
        if server:
            parts.append(f"server={server}")
        for key in ("equity", "margin"):
            raw = account.get(key)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            parts.append(f"{key}={value:.2f}")
        return "حساب: " + " | ".join(parts) if parts else ""

    def _load_live_open_positions(self) -> tuple[list[dict] | None, dict]:
        """Live MT5/OANDA first, then fresh snapshot; ``(None, {})`` = fall back to journal."""
        self._reload_settings()
        broker = str(self.settings.execution.get("broker") or "").lower()
        secrets = self.settings.secrets
        account: dict = {}

        if broker == "mt5":
            from chronoscalp.saas.broker_wizard import fetch_mt5_open_positions

            ok, msg, live_rows, account = fetch_mt5_open_positions(
                int(secrets.mt5_login or 0),
                str(secrets.mt5_password or ""),
                str(secrets.mt5_server or ""),
                str(secrets.mt5_terminal_path or ""),
            )
            if ok:
                return live_rows, account
            logger.warning("Telegram live positions (MT5) failed: {}", msg)
        elif broker == "oanda":
            from chronoscalp.saas.broker_wizard import fetch_oanda_open_positions

            user = UserConfigStore().config
            ok, msg, live_rows = fetch_oanda_open_positions(
                str(secrets.oanda_api_token or ""),
                str(secrets.oanda_account_id or ""),
                str(user.broker.oanda_environment or "practice"),
            )
            if ok:
                return live_rows, {
                    "login": secrets.oanda_account_id or "",
                    "server": str(user.broker.oanda_environment or "practice"),
                }
            logger.warning("Telegram live positions (OANDA) failed: {}", msg)

        mode = self._detect_mode()
        snapshot_path = self.state_dir / f"broker_positions_{mode}.json"
        rows, snap_account = self._read_positions_snapshot(snapshot_path, max_age_seconds=120.0)
        if rows is not None:
            return rows, snap_account or account
        return None, account

    @staticmethod
    def _read_positions_snapshot(
        path: Path, *, max_age_seconds: float
    ) -> tuple[list[dict] | None, dict]:
        if not path.exists():
            return None, {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            updated = str(payload.get("updated_at") or "")
            if updated:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                age = (datetime.now(tz=UTC) - ts).total_seconds()
                if age > max_age_seconds:
                    return None, {}
            rows = payload.get("positions")
            account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
            if isinstance(rows, list):
                return rows, account
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None, {}
        return None, {}

    def _ensure_license(self) -> str | None:
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

    def _stop_if_running(self) -> str | None:
        """Stop the trading process when it is still up. Returns a status line."""
        if not self._running_fn():
            return None
        ok, msg = self._stop_fn()
        time.sleep(1.0)
        return ("✅ " if ok else "⚠️ ") + msg

    def _cmd_start_paper(self, chat_id: int, _text: str = "") -> None:
        err = self._ensure_license()
        if err:
            self.send(chat_id, f"لایسنس: {err}")
            return
        prior = self._stop_if_running()
        self.kill.deactivate()
        ok, msg = self._start_fn("paper")
        text = ("✅ " if ok else "❌ ") + msg
        if prior:
            text = f"{prior}\n{text}"
        self.send(chat_id, text)

    def _cmd_start_live(self, chat_id: int, _text: str = "") -> None:
        self._reload_settings()
        if not self.settings.secrets.live_trading_confirmed:
            self.send(
                chat_id,
                "❌ حالت Live نیاز به CHRONOSCALP_CONFIRM_LIVE=yes دارد.\n"
                "دکمه «تأیید Live روشن» یا /live_confirm yes را بزنید.",
            )
            return
        err = self._ensure_license()
        if err:
            self.send(chat_id, f"لایسنس: {err}")
            return
        prior = self._stop_if_running()
        self.kill.deactivate()
        ok, msg = self._start_fn("live")
        text = ("✅ " if ok else "❌ ") + msg
        if prior:
            text = f"{prior}\n{text}"
        self.send(chat_id, text)

    def _cmd_bot_stop(self, chat_id: int, _text: str = "") -> None:
        ok, msg = self._stop_fn()
        self.send(chat_id, ("✅ " if ok else "⚠️ ") + msg)

    def _cmd_halt(self, chat_id: int, _text: str = "") -> None:
        self.kill.activate("telegram /halt")
        self.send(
            chat_id,
            "🛑 ورود جدید متوقف شد — فرآیند ربات هنوز روشن است.\n"
            "برای خاموش کردن کامل، «توقف ربات» را بزنید.",
        )

    def _cmd_resume(self, chat_id: int, _text: str = "") -> None:
        self.kill.deactivate()
        self.send(chat_id, "✅ Kill switch برداشته شد.")

    def _cmd_logs(self, chat_id: int, _text: str = "") -> None:
        lines = self._logs_fn(25)
        if not lines:
            self.send(chat_id, "لاگی پیدا نشد.")
            return
        body = "\n".join(lines)
        if len(body) > 3800:
            body = body[-3800:]
        self.send(chat_id, f"آخرین لاگ:\n{body}")

    def _cmd_cancel(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(chat_id, "لغو شد.", reply_markup=SETTINGS_KEYBOARD)

    # --- connection ---

    def _connection_summary(self) -> str:
        user = UserConfigStore().config
        s = self.settings.secrets
        live = "yes" if s.live_trading_confirmed else "no"
        mt5_login = s.mt5_login or "—"
        mt5_server = s.mt5_server or "—"
        oanda_acc = (s.oanda_account_id or "—")[:8] + ("…" if s.oanda_account_id else "")
        has_oanda = "set" if s.oanda_api_token else "empty"
        return "\n".join(
            [
                "اتصال / Connection",
                f"provider={user.broker.provider}",
                f"mode={user.broker.mode}",
                f"oanda_env={user.broker.oanda_environment}",
                f"execution.broker={self.settings.execution.get('broker')}",
                f"live_confirm={live}",
                f"MT5 login={mt5_login} server={mt5_server}",
                f"OANDA token={has_oanda} account={oanda_acc}",
                f"onboarding={user.broker.onboarding_complete}",
            ]
        )

    def _cmd_conn(self, chat_id: int, _text: str = "") -> None:
        self._reload_settings()
        self.send(chat_id, self._connection_summary(), reply_markup=CONN_KEYBOARD)

    def _cmd_config(self, chat_id: int, _text: str = "") -> None:
        self._reload_settings()
        from chronoscalp.risk.position_sizing import resolve_active_risk_pct

        strats = self._current_strategies()
        risk = resolve_active_risk_pct(self.settings.risk)
        symbols = ", ".join(self.settings.symbols) or "—"
        hours = self._trading_hours_label()
        daily_loss = "on" if self._daily_loss_enabled() else "off"
        mm = "on" if self._mistake_memory_enabled() else "off"
        copy_on, copy_chat = self._trade_open_copy_state()
        copy_status = "on" if copy_on else "off"
        text = (
            self._connection_summary()
            + "\n\nکنترل / Control\n"
            + f"symbols={symbols}\n"
            + f"strategies={','.join(strats) or '(MACD/trend only)'}\n"
            + f"trading_hours={hours}\n"
            + f"risk_effective={risk}%\n"
            + f"daily_loss_limit={daily_loss}"
            + f" ({float(self.settings.risk.get('max_daily_loss_pct', 3.0))}%)\n"
            + f"mistake_memory={mm}\n"
            + f"trade_open_copy={copy_status} → {copy_chat}"
        )
        self.send(chat_id, text, reply_markup=SETTINGS_KEYBOARD)

    def _save_user_broker(
        self,
        *,
        provider: str | None = None,
        mode: str | None = None,
        oanda_environment: str | None = None,
        onboarding_complete: bool | None = None,
    ) -> None:
        store = UserConfigStore()
        cfg = store.config
        if provider is not None:
            cfg.broker.provider = provider
        if mode is not None:
            cfg.broker.mode = mode
        if oanda_environment is not None:
            cfg.broker.oanda_environment = oanda_environment
        if onboarding_complete is not None:
            cfg.broker.onboarding_complete = onboarding_complete
        store.save()

    def _apply_provider_mode(self, provider: str, mode: str, oanda_env: str = "practice") -> None:
        apply_broker_to_settings_yaml(provider, mode, oanda_env)
        self._save_user_broker(
            provider=provider,
            mode=mode,
            oanda_environment=oanda_env,
            onboarding_complete=True,
        )
        self._reload_settings()

    def _cmd_mode_paper(self, chat_id: int, _text: str = "") -> None:
        user = UserConfigStore().config
        self._apply_provider_mode(
            user.broker.provider or "mt5", "paper", user.broker.oanda_environment
        )
        self.send(
            chat_id,
            "✅ mode=paper ذخیره شد. برای اعمال، ربات را ری‌استارت کنید.",
            reply_markup=CONN_KEYBOARD,
        )

    def _cmd_mode_live(self, chat_id: int, _text: str = "") -> None:
        user = UserConfigStore().config
        self._apply_provider_mode(
            user.broker.provider or "mt5", "live", user.broker.oanda_environment
        )
        self.send(
            chat_id,
            "✅ mode=live ذخیره شد.\n"
            "استارت Live هنوز به تأیید Live نیاز دارد (/live_confirm yes).",
            reply_markup=CONN_KEYBOARD,
        )

    def _cmd_mode(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args or args[0].lower() not in ("paper", "live"):
            self.send(chat_id, "استفاده: /mode paper|live")
            return
        if args[0].lower() == "paper":
            self._cmd_mode_paper(chat_id)
        else:
            self._cmd_mode_live(chat_id)

    def _cmd_provider(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args or args[0].lower() not in ("mt5", "oanda"):
            self.send(chat_id, "استفاده: /provider mt5|oanda")
            return
        provider = args[0].lower()
        user = UserConfigStore().config
        self._apply_provider_mode(
            provider, user.broker.mode or "paper", user.broker.oanda_environment
        )
        self.send(chat_id, f"✅ provider={provider} ذخیره شد.", reply_markup=CONN_KEYBOARD)

    def _cmd_live_on(self, chat_id: int, _text: str = "") -> None:
        enable_live_confirm()
        self._reload_settings()
        self.send(chat_id, "✅ CHRONOSCALP_CONFIRM_LIVE=yes", reply_markup=CONN_KEYBOARD)

    def _cmd_live_off(self, chat_id: int, _text: str = "") -> None:
        disable_live_confirm()
        self._reload_settings()
        self.send(chat_id, "✅ CHRONOSCALP_CONFIRM_LIVE=no", reply_markup=CONN_KEYBOARD)

    def _cmd_live_confirm(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args or args[0].lower() not in ("yes", "no", "on", "off", "1", "0"):
            self.send(chat_id, "استفاده: /live_confirm yes|no")
            return
        if args[0].lower() in ("yes", "on", "1"):
            self._cmd_live_on(chat_id)
        else:
            self._cmd_live_off(chat_id)

    def _cmd_test_conn(self, chat_id: int, _text: str = "") -> None:
        self._reload_settings()
        user = UserConfigStore().config
        provider = user.broker.provider or "mt5"
        self.send(chat_id, f"در حال تست اتصال {provider}…")
        if provider == "oanda":
            res = test_oanda_connection(
                self.settings.secrets.oanda_api_token,
                self.settings.secrets.oanda_account_id,
                user.broker.oanda_environment or "practice",
            )
        else:
            try:
                res = test_mt5_connection(
                    int(self.settings.secrets.mt5_login or 0),
                    self.settings.secrets.mt5_password,
                    self.settings.secrets.mt5_server,
                    self.settings.secrets.mt5_terminal_path,
                )
            except Exception as exc:  # noqa: BLE001
                self.send(chat_id, f"❌ {exc}", reply_markup=CONN_KEYBOARD)
                return
        self.send(chat_id, ("✅ " if res.ok else "❌ ") + res.message, reply_markup=CONN_KEYBOARD)

    def _cmd_wizard_mt5(self, chat_id: int, _text: str = "") -> None:
        self._pending[chat_id] = {"flow": "mt5", "step": "login", "data": {}}
        self.send(chat_id, "MT5 Login (عدد) را بفرستید — یا /cancel", reply_markup=CONN_KEYBOARD)

    def _cmd_wizard_oanda(self, chat_id: int, _text: str = "") -> None:
        self._pending[chat_id] = {"flow": "oanda", "step": "token", "data": {}}
        self.send(chat_id, "OANDA API Token را بفرستید — یا /cancel", reply_markup=CONN_KEYBOARD)

    def _cmd_set_mt5(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if len(args) < 3:
            self.send(
                chat_id,
                "استفاده:\n/set_mt5 LOGIN PASSWORD SERVER [PATH]\n"
                "یا دکمه «بروکر MT5» برای ویزارد.",
            )
            return
        login, password, server = args[0], args[1], args[2]
        path = " ".join(args[3:]) if len(args) > 3 else DEFAULT_MT5_PATH
        self._finish_mt5(chat_id, login, password, server, path)

    def _cmd_set_oanda(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if len(args) < 2:
            self.send(
                chat_id,
                "استفاده:\n/set_oanda TOKEN ACCOUNT_ID [practice|live]\n"
                "یا دکمه «بروکر OANDA» برای ویزارد.",
            )
            return
        token, account = args[0], args[1]
        env = args[2].lower() if len(args) > 2 else "practice"
        if env not in ("practice", "live"):
            env = "practice"
        self._finish_oanda(chat_id, token, account, env)

    def _finish_mt5(self, chat_id: int, login: str, password: str, server: str, path: str) -> None:
        try:
            int(login)
        except ValueError:
            self.send(chat_id, "❌ Login باید عدد باشد.")
            return
        save_mt5_credentials(login, password, server, path)
        user = UserConfigStore().config
        mode = user.broker.mode if user.broker.mode in ("paper", "live") else "paper"
        self._apply_provider_mode("mt5", mode)
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            f"✅ MT5 ذخیره شد (login={login}, server={server}).\n" "برای تست: /test_conn",
            reply_markup=CONN_KEYBOARD,
        )

    def _finish_oanda(self, chat_id: int, token: str, account: str, env: str) -> None:
        save_oanda_credentials(token, account)
        user = UserConfigStore().config
        mode = user.broker.mode if user.broker.mode in ("paper", "live") else "paper"
        self._apply_provider_mode("oanda", mode, env)
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            f"✅ OANDA ذخیره شد (env={env}).\nبرای تست: /test_conn",
            reply_markup=CONN_KEYBOARD,
        )

    def _cmd_oanda_env_practice(self, chat_id: int, _text: str = "") -> None:
        pending = self._pending.get(chat_id)
        if not pending or pending.get("flow") != "oanda" or pending.get("step") != "env":
            self.send(chat_id, "ابتدا ویزارد OANDA را شروع کنید.")
            return
        data = pending["data"]
        self._finish_oanda(chat_id, data["token"], data["account"], "practice")

    def _cmd_oanda_env_live(self, chat_id: int, _text: str = "") -> None:
        pending = self._pending.get(chat_id)
        if not pending or pending.get("flow") != "oanda" or pending.get("step") != "env":
            self.send(chat_id, "ابتدا ویزارد OANDA را شروع کنید.")
            return
        data = pending["data"]
        self._finish_oanda(chat_id, data["token"], data["account"], "live")

    # --- control: symbols / strategies / risk (menu-only pickers) ---

    def _symbol_catalog(self) -> list[str]:
        return list(self.settings.available_symbols) or list(self.settings.symbols)

    def _current_strategies(self) -> list[str]:
        from chronoscalp.strategy.multi_timeframe import resolve_enabled_strategies

        use_smc, use_liq, use_scalp, use_news, use_delta = resolve_enabled_strategies(
            self.settings.strategy
        )
        out: list[str] = []
        if use_delta:
            out.append("delta")
        if use_smc:
            out.append("smc_confluence")
        if use_liq:
            out.append("liquidity_volume")
        if use_scalp:
            out.append("ultra_scalp")
        if use_news:
            out.append("news_straddle")
        return out

    def _symbols_menu_state(self, chat_id: int) -> list[str]:
        pending = self._pending.get(chat_id)
        if pending and pending.get("flow") == "symbols_menu":
            return list(pending.get("selected") or [])
        return list(self.settings.symbols)

    def _strategies_menu_state(self, chat_id: int) -> list[str]:
        pending = self._pending.get(chat_id)
        if pending and pending.get("flow") == "strategies_menu":
            return list(pending.get("selected") or [])
        return self._current_strategies()

    def _send_symbols_menu(self, chat_id: int, *, note: str = "") -> None:
        catalog = self._symbol_catalog()
        selected = self._symbols_menu_state(chat_id)
        self._pending[chat_id] = {
            "flow": "symbols_menu",
            "step": "pick",
            "selected": selected,
        }
        active = ", ".join(selected) or "(هیچکدام)"
        msg = (
            "نمادها — روی هر نماد بزنید تا روشن/خاموش شود، بعد «ذخیره نمادها».\n"
            f"انتخاب فعلی: {active}"
        )
        if note:
            msg = f"{note}\n\n{msg}"
        self.send(chat_id, msg, reply_markup=symbols_keyboard(catalog, selected))

    def _send_strategies_menu(self, chat_id: int, *, note: str = "") -> None:
        selected = self._strategies_menu_state(chat_id)
        self._pending[chat_id] = {
            "flow": "strategies_menu",
            "step": "pick",
            "selected": selected,
        }
        labels = [STRATEGY_LABELS.get(k, k) for k in selected]
        active = ", ".join(labels) if labels else "(فقط MACD/trend)"
        msg = (
            "استراتژی‌ها — روی هر مورد بزنید تا روشن/خاموش شود، بعد «ذخیره استراتژی‌ها».\n"
            f"دلتا (طلا) · SMC · نقدینگی+حجم · اسکلپ S15 · استرادل خبری\n"
            f"انتخاب فعلی: {active}"
        )
        if note:
            msg = f"{note}\n\n{msg}"
        self.send(chat_id, msg, reply_markup=strategies_keyboard(selected))

    def _cmd_symbols_menu(self, chat_id: int, _text: str = "") -> None:
        self._reload_settings()
        self._send_symbols_menu(chat_id)

    def _cmd_strategies_menu(self, chat_id: int, _text: str = "") -> None:
        self._reload_settings()
        self._send_strategies_menu(chat_id)

    def _cmd_symbols_all(self, chat_id: int, _text: str = "") -> None:
        catalog = self._symbol_catalog()
        self._pending[chat_id] = {
            "flow": "symbols_menu",
            "step": "pick",
            "selected": list(catalog),
        }
        self._send_symbols_menu(chat_id, note="همه نمادها انتخاب شدند.")

    def _cmd_symbols_none(self, chat_id: int, _text: str = "") -> None:
        # Keep at least empty draft — save will reject empty; user must pick one.
        self._pending[chat_id] = {"flow": "symbols_menu", "step": "pick", "selected": []}
        self._send_symbols_menu(chat_id, note="انتخاب پاک شد — حداقل یک نماد لازم است.")

    def _cmd_symbols_save(self, chat_id: int, _text: str = "") -> None:
        selected = self._symbols_menu_state(chat_id)
        catalog = self._symbol_catalog()
        try:
            saved = apply_active_symbols(selected, allowed=catalog or None)
        except ValueError as exc:
            self._send_symbols_menu(chat_id, note=f"❌ {exc}")
            return
        self._reload_settings()
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            f"✅ نمادها ذخیره شد: {', '.join(saved)}\nربات را Stop سپس Start کنید.",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _cmd_strategies_all(self, chat_id: int, _text: str = "") -> None:
        self._pending[chat_id] = {
            "flow": "strategies_menu",
            "step": "pick",
            "selected": list(STRATEGY_LABELS.keys()),
        }
        self._send_strategies_menu(chat_id, note="همه استراتژی‌ها انتخاب شدند.")

    def _cmd_strategies_none(self, chat_id: int, _text: str = "") -> None:
        self._pending[chat_id] = {
            "flow": "strategies_menu",
            "step": "pick",
            "selected": [],
        }
        self._send_strategies_menu(chat_id, note="فقط MACD/trend (بدون confluence).")

    def _cmd_strategies_save(self, chat_id: int, _text: str = "") -> None:
        selected = self._strategies_menu_state(chat_id)
        saved = apply_enabled_strategies(selected)
        self._reload_settings()
        self._pending.pop(chat_id, None)
        label = (
            ", ".join(STRATEGY_LABELS.get(s, s) for s in saved) if saved else "(MACD/trend only)"
        )
        self.send(
            chat_id,
            f"✅ استراتژی‌ها ذخیره شد: {label}\nربات را Stop سپس Start کنید.",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _toggle_symbol_pick(self, chat_id: int, symbol: str) -> None:
        catalog = self._symbol_catalog()
        catalog_u = {s.upper(): s for s in catalog}
        key = catalog_u.get(symbol.upper())
        if key is None:
            self._send_symbols_menu(chat_id, note=f"نماد ناشناخته: {symbol}")
            return
        selected = list(self._symbols_menu_state(chat_id))
        selected_u = {s.upper() for s in selected}
        if key.upper() in selected_u:
            selected = [s for s in selected if s.upper() != key.upper()]
        else:
            selected.append(key)
        self._pending[chat_id] = {
            "flow": "symbols_menu",
            "step": "pick",
            "selected": selected,
        }
        self._send_symbols_menu(chat_id)

    def _toggle_strategy_pick(self, chat_id: int, label_or_key: str) -> None:
        key = STRATEGY_LABEL_TO_KEY.get(label_or_key) or (
            label_or_key if label_or_key in STRATEGY_LABELS else None
        )
        if key is None:
            self._send_strategies_menu(chat_id, note=f"استراتژی ناشناخته: {label_or_key}")
            return
        selected = list(self._strategies_menu_state(chat_id))
        if key in selected:
            selected = [s for s in selected if s != key]
        else:
            selected.append(key)
        self._pending[chat_id] = {
            "flow": "strategies_menu",
            "step": "pick",
            "selected": selected,
        }
        self._send_strategies_menu(chat_id)

    def _handle_menu_toggle(self, chat_id: int, text: str) -> bool:
        """Handle ✅/⬜ taps inside symbols/strategies pickers (no typing)."""
        payload = parse_toggle_label(text)
        if payload is None:
            return False
        pending = self._pending.get(chat_id) or {}
        flow = pending.get("flow")
        if flow == "symbols_menu":
            self._toggle_symbol_pick(chat_id, payload)
            return True
        if flow == "strategies_menu":
            self._toggle_strategy_pick(chat_id, payload)
            return True
        # Not in a picker — open the matching menu if payload looks known.
        catalog_u = {s.upper() for s in self._symbol_catalog()}
        if payload.upper() in catalog_u:
            self._cmd_symbols_menu(chat_id)
            self._toggle_symbol_pick(chat_id, payload)
            return True
        if payload in STRATEGY_LABEL_TO_KEY or payload in STRATEGY_LABELS:
            self._cmd_strategies_menu(chat_id)
            self._toggle_strategy_pick(chat_id, payload)
            return True
        return False

    def _cmd_symbols(self, chat_id: int, text: str = "") -> None:
        """Slash `/symbols` opens menu; optional CSV args still accepted for automation."""
        args = self._args(text)
        raw = " ".join(args) if args else ""
        if not raw:
            self._cmd_symbols_menu(chat_id)
            return
        self._apply_symbols_csv(chat_id, raw)

    def _apply_symbols_csv(self, chat_id: int, raw: str) -> None:
        parts = [p.strip() for p in raw.replace("،", ",").split(",") if p.strip()]
        catalog = self._symbol_catalog()
        try:
            saved = apply_active_symbols(parts, allowed=catalog or None)
        except ValueError as exc:
            self.send(chat_id, f"❌ {exc}", reply_markup=CONTROL_KEYBOARD)
            return
        self._reload_settings()
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            f"✅ نمادها: {', '.join(saved)}\nربات را Stop سپس Start کنید.",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _cmd_strategies(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args:
            self._cmd_strategies_menu(chat_id)
            return
        raw = " ".join(args)
        self._apply_strategies_csv(chat_id, raw)

    def _apply_strategies_csv(self, chat_id: int, raw: str) -> None:
        parts = [p.strip() for p in raw.replace("،", ",").split(",") if p.strip()]
        saved = apply_enabled_strategies(parts)
        self._reload_settings()
        self._pending.pop(chat_id, None)
        label = ", ".join(saved) if saved else "(MACD/trend only)"
        self.send(
            chat_id,
            f"✅ استراتژی‌ها: {label}\nربات را Stop سپس Start کنید.",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _set_hours(self, chat_id: int, mode: str) -> None:
        saved = apply_trading_hours_mode(mode)
        self._reload_settings()
        labels = {
            "london_ny": "فقط سشن لندن و آمریکا",
            "always_on_24h": "۲۴ ساعته (همیشه)",
        }
        self.send(
            chat_id,
            f"✅ ساعات معامله: {labels.get(saved, saved)}\nربات را Stop سپس Start کنید.",
            reply_markup=hours_keyboard(),
        )

    def _cmd_hours_london_ny(self, chat_id: int, _text: str = "") -> None:
        self._set_hours(chat_id, "london_ny")

    def _cmd_hours_24h(self, chat_id: int, _text: str = "") -> None:
        self._set_hours(chat_id, "always_on_24h")

    def _cmd_hours(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args:
            self._cmd_hours_menu(chat_id)
            return
        self._set_hours(chat_id, args[0])

    def _set_risk(self, chat_id: int, pct: float) -> None:
        effective = apply_risk_preset(pct)
        self._reload_settings()
        note = ""
        if pct > 1.0:
            note = f"\n(انتخاب {pct}% بود؛ سقف امنیتی → {effective}%)"
        self.send(
            chat_id,
            f"✅ ریسک مؤثر = {effective}%{note}\nربات را Stop سپس Start کنید.",
            reply_markup=self._risk_keyboard(),
        )

    def _cmd_risk_05(self, chat_id: int, _text: str = "") -> None:
        self._set_risk(chat_id, 0.5)

    def _cmd_risk_10(self, chat_id: int, _text: str = "") -> None:
        self._set_risk(chat_id, 1.0)

    def _cmd_risk_15(self, chat_id: int, _text: str = "") -> None:
        self._set_risk(chat_id, 1.5)

    def _cmd_risk(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        presets = self._risk_presets()
        if not args:
            shown = " | ".join(
                str(p).rstrip("0").rstrip(".") if isinstance(p, float) else str(p) for p in presets
            )
            self.send(chat_id, f"استفاده: /risk {{{shown}}}")
            return
        try:
            pct = float(args[0].replace("%", "").replace("٫", ".").replace(",", "."))
        except ValueError:
            self.send(chat_id, "❌ عدد نامعتبر")
            return
        if not any(abs(pct - p) < 1e-9 for p in presets):
            shown = " / ".join(str(p) for p in presets)
            self.send(chat_id, f"فقط presetهای {shown} مجاز است.")
            return
        self._set_risk(chat_id, pct)

    def _risk_presets(self) -> list[float]:
        """Configured risk presets; always keep legacy 0.5/1.0/1.5 available."""
        raw = self.settings.risk.get("risk_presets_pct") or [0.5, 1.0, 1.5]
        values = [float(p) for p in raw]
        for legacy in (0.5, 1.0, 1.5):
            if not any(abs(legacy - p) < 1e-9 for p in values):
                values.append(legacy)
        return values

    def _set_daily_loss_enabled(self, chat_id: int, enabled: bool) -> None:
        apply_daily_loss_limit_enabled(enabled)
        self._reload_settings()
        label = "روشن ✅" if enabled else "خاموش ⬜"
        self.send(
            chat_id,
            f"✅ قفل ضرر روزانه: {label}\n" "ربات را Stop سپس Start کنید تا اعمال شود.",
            reply_markup=self._risk_keyboard(),
        )

    def _cmd_daily_loss_on(self, chat_id: int, _text: str = "") -> None:
        self._set_daily_loss_enabled(chat_id, True)

    def _cmd_daily_loss_off(self, chat_id: int, _text: str = "") -> None:
        self._set_daily_loss_enabled(chat_id, False)

    def _set_mistake_memory_enabled(self, chat_id: int, enabled: bool) -> None:
        apply_mistake_memory_enabled(enabled)
        self._reload_settings()
        label = "روشن ✅" if enabled else "خاموش ⬜"
        self.send(
            chat_id,
            f"✅ یادگیری از اشتباه: {label}\n" "ربات را Stop سپس Start کنید تا اعمال شود.",
            reply_markup=self._risk_keyboard(),
        )

    def _cmd_mistake_memory_on(self, chat_id: int, _text: str = "") -> None:
        self._set_mistake_memory_enabled(chat_id, True)

    def _cmd_mistake_memory_off(self, chat_id: int, _text: str = "") -> None:
        self._set_mistake_memory_enabled(chat_id, False)

    def _trade_open_copy_state(self) -> tuple[bool, str]:
        from chronoscalp.utils.telegram_chat import DEFAULT_TRADE_OPEN_COPY_CHAT

        alerting = self.settings.alerting or {}
        enabled = bool(alerting.get("trade_open_copy_enabled", True))
        chat = str(alerting.get("trade_open_copy_chat_id") or "").strip()
        return enabled, chat or DEFAULT_TRADE_OPEN_COPY_CHAT

    def _trade_notify_keyboard(self) -> dict[str, Any]:
        enabled, _chat = self._trade_open_copy_state()
        return trade_notify_keyboard(enabled=enabled)

    def _cmd_trade_notify_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self._reload_settings()
        enabled, target = self._trade_open_copy_state()
        status = "روشن ✅" if enabled else "خاموش ⬜"
        self.send(
            chat_id,
            "اعلان باز شدن معامله\n"
            f"وضعیت: {status}\n"
            f"گیرنده: {target}\n\n"
            "به‌محض پر شدن معامله یک پیام به این آی‌دی می‌رود.\n"
            "گیرنده باید همین ربات را Start کرده باشد.\n"
            "برای کاربر خصوصی معمولاً chat_id عددی لازم است (نه @یوزرنیم).\n"
            "تغییر آی‌دی را از دکمه بزنید یا /notify_id را بفرستید.",
            reply_markup=self._trade_notify_keyboard(),
        )

    def _set_trade_open_copy_enabled(self, chat_id: int, enabled: bool) -> None:
        apply_trade_open_copy_enabled(enabled)
        self._reload_settings()
        label = "روشن ✅" if enabled else "خاموش ⬜"
        _, target = self._trade_open_copy_state()
        self.send(
            chat_id,
            f"✅ اعلان معامله: {label}\nگیرنده: {target}\n"
            "ربات معامله را Stop سپس Start کنید تا اعمال شود.",
            reply_markup=self._trade_notify_keyboard(),
        )

    def _cmd_trade_notify_on(self, chat_id: int, _text: str = "") -> None:
        self._set_trade_open_copy_enabled(chat_id, True)

    def _cmd_trade_notify_off(self, chat_id: int, _text: str = "") -> None:
        self._set_trade_open_copy_enabled(chat_id, False)

    def _cmd_trade_notify_set_id(self, chat_id: int, text: str = "") -> None:
        raw = (text or "").strip()
        if raw.startswith("/"):
            args = self._args(text)
            if args:
                self._save_trade_open_copy_chat(chat_id, " ".join(args))
                return
        self._pending[chat_id] = {"flow": "trade_notify_id", "step": "chat", "data": {}}
        self.send(
            chat_id,
            "آی‌دی گیرنده اعلان را بفرستید:\n"
            "• یوزرنیم مثل @taranomrashid\n"
            "• یا عدد chat_id مثل 123456789\n\n"
            "گیرنده باید ربات را Start کرده باشد.\n"
            "لغو = انصراف",
            reply_markup=self._trade_notify_keyboard(),
        )

    def _save_trade_open_copy_chat(self, chat_id: int, raw: str) -> None:
        from chronoscalp.utils.telegram_chat import InvalidTelegramChatRef

        try:
            saved = apply_trade_open_copy_chat_id(raw)
        except InvalidTelegramChatRef as exc:
            self.send(
                chat_id,
                f"❌ {exc}",
                reply_markup=self._trade_notify_keyboard(),
            )
            return
        self._pending.pop(chat_id, None)
        self._reload_settings()
        ping_note = self._try_trade_notify_ping(saved)
        self.send(
            chat_id,
            f"✅ گیرنده اعلان ذخیره شد: {saved}\n"
            f"{ping_note}\n"
            "ربات معامله را Stop سپس Start کنید تا اعلان زنده با آی‌دی جدید برود.",
            reply_markup=self._trade_notify_keyboard(),
        )

    def _try_trade_notify_ping(self, target: str) -> str:
        try:
            self.send(
                target,
                "تست اعلان معامله ChronoScalp — اگر این را می‌بینید آی‌دی درست است.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Trade-open copy test failed target={}: {}", target, exc)
            return (
                "⚠️ تست ارسال نشد. گیرنده باید ربات را Start کرده باشد؛ "
                "برای کاربر خصوصی chat_id عددی بفرستید (دستور /whoami در همان چت)."
            )
        return "✅ پیام تست ارسال شد."

    def _cmd_trade_notify_test(self, chat_id: int, _text: str = "") -> None:
        self._reload_settings()
        enabled, target = self._trade_open_copy_state()
        if not enabled:
            self.send(
                chat_id,
                "اعلان معامله خاموش است. اول «اعلان معامله روشن» را بزنید.",
                reply_markup=self._trade_notify_keyboard(),
            )
            return
        ping_note = self._try_trade_notify_ping(target)
        self.send(
            chat_id,
            f"تست به {target}\n{ping_note}",
            reply_markup=self._trade_notify_keyboard(),
        )

    def _cmd_mistake_memory(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args:
            self._cmd_risk_menu(chat_id)
            return
        key = args[0].strip().lower()
        if key in ("on", "1", "yes", "enable", "روشن"):
            self._cmd_mistake_memory_on(chat_id)
            return
        if key in ("off", "0", "no", "disable", "خاموش"):
            self._cmd_mistake_memory_off(chat_id)
            return
        self.send(
            chat_id,
            "استفاده: /mistake_memory on|off",
            reply_markup=self._risk_keyboard(),
        )

    def _detect_run_mode(self) -> str:
        """Best-effort: user profile broker mode, else live if confirm, else paper."""
        user = UserConfigStore().config
        mode = (user.broker.mode or "").strip().lower()
        if mode in ("live", "paper"):
            return mode
        if self.settings.secrets.live_trading_confirmed:
            return "live"
        return "paper"

    def _restart_bot_for_mode(self, mode: str) -> str:
        """Stop managed bot if running, then start in ``mode``. Returns status text."""
        notes: list[str] = []
        if self._running_fn():
            ok, msg = self._stop_fn()
            notes.append(("✅ " if ok else "⚠️ ") + msg)
            time.sleep(1.5)
        ok, msg = self._start_fn(mode)
        notes.append(("✅ " if ok else "❌ ") + msg)
        return "\n".join(notes)

    def _cmd_daily_loss_unlock(self, chat_id: int, _text: str = "") -> None:
        """Clear today's daily-loss count via reset marker and restart the bot."""
        mode = self._detect_run_mode()
        reset_at = write_daily_reset_marker(self.state_dir, mode)
        # Also clear paper marker when unlocking live (and vice versa) so demos
        # don't keep a stale seed if the operator switches modes.
        other = "paper" if mode == "live" else "live"
        write_daily_reset_marker(self.state_dir, other)
        restart_msg = self._restart_bot_for_mode(mode)
        self.send(
            chat_id,
            "✅ قفل ضرر امروز باز شد.\n"
            f"marker={reset_at.isoformat()} mode={mode}\n"
            f"{restart_msg}",
            reply_markup=self._risk_keyboard(),
        )

    def _cmd_daily_loss(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args:
            self._cmd_risk_menu(chat_id)
            return
        key = args[0].strip().lower()
        if key in ("on", "1", "yes", "enable", "روشن"):
            self._cmd_daily_loss_on(chat_id)
            return
        if key in ("off", "0", "no", "disable", "خاموش"):
            self._cmd_daily_loss_off(chat_id)
            return
        if key in ("unlock", "reset", "باز", "unlock_today"):
            self._cmd_daily_loss_unlock(chat_id)
            return
        self.send(
            chat_id,
            "استفاده: /daily_loss on|off|unlock",
            reply_markup=self._risk_keyboard(),
        )

    # --- pending wizard input ---

    def _handle_pending(self, chat_id: int, text: str) -> bool:
        pending = self._pending.get(chat_id)
        if not pending:
            return False
        raw = (text or "").strip()
        if not raw:
            return True
        if raw.startswith("/"):
            return False  # allow command to cancel/override via normal dispatch
        flow = pending.get("flow")
        step = pending.get("step")
        data = pending.setdefault("data", {})

        if flow == "mt5":
            if step == "login":
                data["login"] = raw
                pending["step"] = "password"
                self.send(chat_id, "رمز MT5 را بفرستید:")
                return True
            if step == "password":
                data["password"] = raw
                pending["step"] = "server"
                self.send(chat_id, "نام Server بروکر را بفرستید:")
                return True
            if step == "server":
                data["server"] = raw
                pending["step"] = "path"
                self.send(
                    chat_id,
                    f"مسیر terminal64.exe را بفرستید\n(یا `-` برای پیش‌فرض:\n{DEFAULT_MT5_PATH})",
                )
                return True
            if step == "path":
                path = DEFAULT_MT5_PATH if raw in ("-", "default", "پیش‌فرض") else raw
                self._finish_mt5(chat_id, data["login"], data["password"], data["server"], path)
                return True

        if flow == "oanda":
            if step == "token":
                data["token"] = raw
                pending["step"] = "account"
                self.send(chat_id, "OANDA Account ID را بفرستید:")
                return True
            if step == "account":
                data["account"] = raw
                pending["step"] = "env"
                self.send(
                    chat_id,
                    "محیط OANDA را انتخاب کنید:",
                    reply_markup=OANDA_ENV_KEYBOARD,
                )
                return True

        # symbols_menu / strategies_menu use button toggles, not free text.
        if flow in ("symbols_menu", "strategies_menu"):
            return False

        if flow == "trade_notify_id" and step == "chat":
            if self._resolve_command(raw) is not None:
                return False
            self._save_trade_open_copy_chat(chat_id, raw)
            return True

        return False

    def handle(self, chat_id: int, text: str) -> None:
        """Dispatch one inbound message."""
        logger.info("Telegram cmd from chat_id={} text={!r}", chat_id, (text or "")[:80])
        if not self._authorized(chat_id):
            self.send(
                chat_id,
                "⛔ این چت مجاز به کنترل ربات نیست.\n"
                f"chat_id عددی شما: {chat_id}\n"
                "اگر باید اعلان معامله بگیرید، این عدد را به اپراتور بدهید "
                "و همین ربات را Start کرده باشید.",
            )
            return

        self._bind_chat_if_needed(chat_id)

        if self._handle_menu_toggle(chat_id, text):
            return

        if self._handle_pending(chat_id, text):
            return

        cmd = self._resolve_command(text)
        if cmd is None:
            self.send(
                chat_id, "دستور ناشناخته. /help یا /settings را بزنید.", reply_markup=MAIN_KEYBOARD
            )
            return

        handlers: dict[str, Callable[[int, str], None]] = {
            "help": self._cmd_help,
            "menu": self._cmd_menu,
            "settings": self._cmd_settings,
            "conn_menu": self._cmd_conn_menu,
            "control_menu": self._cmd_control_menu,
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
            "cancel": self._cmd_cancel,
            "conn": self._cmd_conn,
            "config": self._cmd_config,
            "mode_paper": self._cmd_mode_paper,
            "mode_live": self._cmd_mode_live,
            "mode": self._cmd_mode,
            "provider": self._cmd_provider,
            "live_on": self._cmd_live_on,
            "live_off": self._cmd_live_off,
            "live_confirm": self._cmd_live_confirm,
            "test_conn": self._cmd_test_conn,
            "wizard_mt5": self._cmd_wizard_mt5,
            "wizard_oanda": self._cmd_wizard_oanda,
            "set_mt5": self._cmd_set_mt5,
            "set_oanda": self._cmd_set_oanda,
            "oanda_env_practice": self._cmd_oanda_env_practice,
            "oanda_env_live": self._cmd_oanda_env_live,
            "symbols_menu": self._cmd_symbols_menu,
            "symbols": self._cmd_symbols,
            "symbols_all": self._cmd_symbols_all,
            "symbols_none": self._cmd_symbols_none,
            "symbols_save": self._cmd_symbols_save,
            "strategies_menu": self._cmd_strategies_menu,
            "strategies": self._cmd_strategies,
            "strategies_all": self._cmd_strategies_all,
            "strategies_none": self._cmd_strategies_none,
            "strategies_save": self._cmd_strategies_save,
            "hours_menu": self._cmd_hours_menu,
            "risk_menu": self._cmd_risk_menu,
            "hours_london_ny": self._cmd_hours_london_ny,
            "hours_24h": self._cmd_hours_24h,
            "hours": self._cmd_hours,
            "risk_05": self._cmd_risk_05,
            "risk_10": self._cmd_risk_10,
            "risk_15": self._cmd_risk_15,
            "risk": self._cmd_risk,
            "daily_loss_on": self._cmd_daily_loss_on,
            "daily_loss_off": self._cmd_daily_loss_off,
            "daily_loss_unlock": self._cmd_daily_loss_unlock,
            "daily_loss": self._cmd_daily_loss,
            "mistake_memory_on": self._cmd_mistake_memory_on,
            "mistake_memory_off": self._cmd_mistake_memory_off,
            "mistake_memory": self._cmd_mistake_memory,
            "trade_notify_menu": self._cmd_trade_notify_menu,
            "trade_notify_on": self._cmd_trade_notify_on,
            "trade_notify_off": self._cmd_trade_notify_off,
            "trade_notify_set_id": self._cmd_trade_notify_set_id,
            "trade_notify_test": self._cmd_trade_notify_test,
        }
        handlers[cmd](chat_id, text)

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
