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
from chronoscalp.orchestration.trade_journal import load_journal_snapshot
from chronoscalp.saas.broker_wizard import (
    KNOWN_STRATEGIES,
    apply_active_symbols,
    apply_broker_to_settings_yaml,
    apply_enabled_strategies,
    apply_risk_preset,
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

    def _cmd_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(chat_id, "منوی اصلی", reply_markup=MAIN_KEYBOARD)

    def _cmd_settings(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(
            chat_id, "تنظیمات — اتصال یا کنترل را انتخاب کنید.", reply_markup=SETTINGS_KEYBOARD
        )

    def _cmd_conn_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(chat_id, "تنظیمات اتصال", reply_markup=CONN_KEYBOARD)

    def _cmd_control_menu(self, chat_id: int, _text: str = "") -> None:
        self._pending.pop(chat_id, None)
        self.send(chat_id, "تنظیمات کنترل (نماد / استراتژی / ریسک)", reply_markup=CONTROL_KEYBOARD)

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
        live_ok = "yes" if self.settings.secrets.live_trading_confirmed else "no"
        user = UserConfigStore().config
        lines = [
            "وضعیت ChronoScalp",
            f"فرآیند: {'در حال اجرا' if running else 'متوقف'}" + (f" (PID {pid})" if pid else ""),
            f"حالت ژورنال: {mode}",
            f"پروفایل: provider={user.broker.provider} mode={user.broker.mode}",
            f"بروکر اجرا: {broker}",
            f"نمادها: {symbols}",
            f"kill_switch: {ks}",
            f"دلیل: {reason}",
            f"تأیید Live (.env): {live_ok}",
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

    def _cmd_start_paper(self, chat_id: int, _text: str = "") -> None:
        err = self._ensure_license()
        if err:
            self.send(chat_id, f"لایسنس: {err}")
            return
        ok, msg = self._start_fn("paper")
        self.send(chat_id, ("✅ " if ok else "❌ ") + msg)

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
        ok, msg = self._start_fn("live")
        self.send(chat_id, ("✅ " if ok else "❌ ") + msg)

    def _cmd_bot_stop(self, chat_id: int, _text: str = "") -> None:
        ok, msg = self._stop_fn()
        self.send(chat_id, ("✅ " if ok else "⚠️ ") + msg)

    def _cmd_halt(self, chat_id: int, _text: str = "") -> None:
        self.kill.activate("telegram /halt")
        self.send(chat_id, "🛑 Kill switch فعال شد — ورود جدید متوقف است.")

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
        from chronoscalp.strategy.multi_timeframe import resolve_enabled_strategies

        use_smc, use_liq, use_scalp = resolve_enabled_strategies(self.settings.strategy)
        strats = []
        if use_smc:
            strats.append("smc_confluence")
        if use_liq:
            strats.append("liquidity_volume")
        if use_scalp:
            strats.append("ultra_scalp")
        risk = resolve_active_risk_pct(self.settings.risk)
        symbols = ", ".join(self.settings.symbols) or "—"
        text = (
            self._connection_summary()
            + "\n\nکنترل / Control\n"
            + f"symbols={symbols}\n"
            + f"strategies={','.join(strats) or '(MACD/trend only)'}\n"
            + f"risk_effective={risk}%"
        )
        self.send(chat_id, text, reply_markup=CONTROL_KEYBOARD)

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

    # --- control: symbols / strategies / risk ---

    def _cmd_symbols_prompt(self, chat_id: int, _text: str = "") -> None:
        catalog = list(self.settings.available_symbols) or list(self.settings.symbols)
        current = ", ".join(self.settings.symbols) or "—"
        avail = ", ".join(catalog) or "—"
        self._pending[chat_id] = {"flow": "symbols", "step": "list", "data": {}}
        self.send(
            chat_id,
            f"نمادهای فعال: {current}\nموجود: {avail}\n\n"
            "لیست جدید را با ویرگول بفرستید:\nXAUUSD,EURUSD\nیا /cancel",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _cmd_symbols(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        raw = " ".join(args) if args else ""
        if not raw:
            self._cmd_symbols_prompt(chat_id)
            return
        self._apply_symbols(chat_id, raw)

    def _apply_symbols(self, chat_id: int, raw: str) -> None:
        parts = [p.strip() for p in raw.replace("،", ",").split(",") if p.strip()]
        catalog = list(self.settings.available_symbols) or list(self.settings.symbols)
        try:
            saved = apply_active_symbols(parts, allowed=catalog or None)
        except ValueError as exc:
            self.send(chat_id, f"❌ {exc}")
            return
        self._reload_settings()
        self._pending.pop(chat_id, None)
        self.send(
            chat_id,
            f"✅ نمادها: {', '.join(saved)}\nربات را ری‌استارت کنید.",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _cmd_strategies_prompt(self, chat_id: int, _text: str = "") -> None:
        known = ", ".join(KNOWN_STRATEGIES)
        self._pending[chat_id] = {"flow": "strategies", "step": "list", "data": {}}
        self.send(
            chat_id,
            f"استراتژی‌های شناخته‌شده:\n{known}\n\n"
            "لیست را با ویرگول بفرستید (خالی = فقط MACD/trend):\n"
            "smc_confluence,liquidity_volume\nیا /cancel",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _cmd_strategies(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args:
            self._cmd_strategies_prompt(chat_id)
            return
        raw = " ".join(args)
        self._apply_strategies(chat_id, raw)

    def _apply_strategies(self, chat_id: int, raw: str) -> None:
        parts = [p.strip() for p in raw.replace("،", ",").split(",") if p.strip()]
        saved = apply_enabled_strategies(parts)
        self._reload_settings()
        self._pending.pop(chat_id, None)
        label = ", ".join(saved) if saved else "(MACD/trend only)"
        self.send(
            chat_id,
            f"✅ استراتژی‌ها: {label}\nربات را ری‌استارت کنید.",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _set_risk(self, chat_id: int, pct: float) -> None:
        effective = apply_risk_preset(pct)
        self._reload_settings()
        note = ""
        if pct > 1.0:
            note = f"\n(انتخاب {pct}% بود؛ سقف امنیتی → {effective}%)"
        self.send(
            chat_id,
            f"✅ ریسک مؤثر = {effective}%{note}",
            reply_markup=CONTROL_KEYBOARD,
        )

    def _cmd_risk_05(self, chat_id: int, _text: str = "") -> None:
        self._set_risk(chat_id, 0.5)

    def _cmd_risk_10(self, chat_id: int, _text: str = "") -> None:
        self._set_risk(chat_id, 1.0)

    def _cmd_risk_15(self, chat_id: int, _text: str = "") -> None:
        self._set_risk(chat_id, 1.5)

    def _cmd_risk(self, chat_id: int, text: str = "") -> None:
        args = self._args(text)
        if not args:
            self.send(chat_id, "استفاده: /risk 0.5|1|1.5")
            return
        try:
            pct = float(args[0].replace("%", "").replace("٫", ".").replace(",", "."))
        except ValueError:
            self.send(chat_id, "❌ عدد نامعتبر")
            return
        if pct not in (0.5, 1.0, 1.5):
            self.send(chat_id, "فقط presetهای 0.5 / 1 / 1.5 مجاز است.")
            return
        self._set_risk(chat_id, pct)

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

        if flow == "symbols" and step == "list":
            self._apply_symbols(chat_id, raw)
            return True

        if flow == "strategies" and step == "list":
            self._apply_strategies(chat_id, raw)
            return True

        return False

    def handle(self, chat_id: int, text: str) -> None:
        """Dispatch one inbound message."""
        logger.info("Telegram cmd from chat_id={} text={!r}", chat_id, (text or "")[:80])
        if not self._authorized(chat_id):
            self.send(chat_id, "⛔ Unauthorized chat.")
            return

        self._bind_chat_if_needed(chat_id)

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
            "symbols_prompt": self._cmd_symbols_prompt,
            "symbols": self._cmd_symbols,
            "strategies_prompt": self._cmd_strategies_prompt,
            "strategies": self._cmd_strategies,
            "risk_05": self._cmd_risk_05,
            "risk_10": self._cmd_risk_10,
            "risk_15": self._cmd_risk_15,
            "risk": self._cmd_risk,
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
