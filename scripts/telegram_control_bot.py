#!/usr/bin/env python3
"""ChronoScalp Telegram control bot — status, P&L, kill-switch.

Requires TELEGRAM_BOT_TOKEN (+ optional TELEGRAM_CHAT_ID allow-list) in .env.

Create the bot with @BotFather, then:
  1. Put token in .env
  2. Message the bot /start
  3. Set TELEGRAM_CHAT_ID to your chat id (from /whoami)
  4. python scripts/telegram_control_bot.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.orchestration.kill_switch import KillSwitch  # noqa: E402
from chronoscalp.orchestration.trade_journal import load_journal_snapshot  # noqa: E402

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramControlBot:
    """Long-polling command bot for ops on a VPS."""

    def __init__(self) -> None:
        settings = get_settings()
        self.token = settings.secrets.telegram_bot_token.strip()
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing in .env")
        self.allowed_chat = settings.secrets.telegram_chat_id.strip()
        self.state_dir = Path(settings.execution.get("state_dir", "data/state"))
        self.mode = "paper"
        if (self.state_dir / "trade_journal_live.json").exists():
            self.mode = "live"
        self.kill = KillSwitch(
            state_dir=self.state_dir,
            env_stop=settings.secrets.chronoscalp_stop_trading,
        )
        self.offset = 0
        self.timeout = float(settings.alerting.get("timeout_seconds", 5))
        self.reference_equity = float(settings.backtest.get("initial_balance", 10_000))

    def _api(self, method: str, **params) -> dict:
        url = API.format(token=self.token, method=method)
        response = requests.post(url, json=params, timeout=max(35.0, self.timeout))
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data

    def send(self, chat_id: str | int, text: str) -> None:
        self._api("sendMessage", chat_id=chat_id, text=text[:4000], parse_mode="Markdown")

    def _authorized(self, chat_id: str | int) -> bool:
        if not self.allowed_chat:
            return True
        return str(chat_id) == str(self.allowed_chat)

    def handle(self, chat_id: int, text: str) -> None:
        if not self._authorized(chat_id):
            self.send(chat_id, "⛔ Unauthorized chat.")
            return

        cmd = (text or "").strip().split()[0].lower() if text else ""
        if cmd in ("/start", "/help"):
            self.send(
                chat_id,
                (
                    "*ChronoScalp Control*\n"
                    "/status — bot state + kill switch\n"
                    "/pnl — live trading stats\n"
                    "/open — open positions\n"
                    "/whoami — your chat id\n"
                    "/stop — halt new entries (kill switch)\n"
                    "/resume — clear kill switch\n"
                    "/help — this message"
                ),
            )
            return
        if cmd == "/whoami":
            self.send(chat_id, f"chat\\_id=`{chat_id}`\nPut this in `.env` as TELEGRAM_CHAT_ID")
            return
        if cmd == "/status":
            ks = "ACTIVE 🛑" if self.kill.is_active() else "off"
            reason = self.kill.reason() if self.kill.is_active() else "—"
            state_path = self.state_dir / f"trading_state_{self.mode}.json"
            self.send(
                chat_id,
                (
                    f"*Status*\nmode=`{self.mode}`\n"
                    f"kill\\_switch={ks}\nreason={reason}\n"
                    f"state\\_file={'yes' if state_path.exists() else 'no'}"
                ),
            )
            return
        if cmd == "/pnl":
            snap = load_journal_snapshot(
                self.state_dir, self.mode, reference_equity=self.reference_equity
            )
            s = snap.stats
            self.send(
                chat_id,
                (
                    f"*P&L ({self.mode})*\n"
                    f"net=`{s.net_pnl:+.2f}` today=`{s.today_pnl:+.2f}`\n"
                    f"closed={s.closed_trades} open={s.open_trades}\n"
                    f"win\\_rate={s.win_rate_pct:.1f}% avg=`{s.avg_pnl:+.2f}`\n"
                    f"PF={s.profit_factor} expectancy=`{s.expectancy:+.2f}`"
                ),
            )
            return
        if cmd == "/open":
            snap = load_journal_snapshot(self.state_dir, self.mode)
            if not snap.open_trades:
                self.send(chat_id, "No open positions.")
                return
            lines = [
                f"`{t.symbol}` {t.direction} vol={t.volume} @{t.entry_price}"
                for t in snap.open_trades
            ]
            self.send(chat_id, "*Open*\n" + "\n".join(lines))
            return
        if cmd == "/stop":
            self.kill.activate("telegram /stop")
            self.send(chat_id, "🛑 Kill switch *activated* — new entries halted.")
            return
        if cmd == "/resume":
            self.kill.deactivate()
            self.send(chat_id, "✅ Kill switch *cleared*.")
            return
        self.send(chat_id, "Unknown command. Try /help")

    def run_forever(self) -> None:
        logger.info("Telegram control bot started (allow_chat={})", self.allowed_chat or "*")
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


def main() -> None:
    TelegramControlBot().run_forever()


if __name__ == "__main__":
    main()
