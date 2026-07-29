#!/usr/bin/env python3
"""One-shot: restore keyboards including trading-hours buttons."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import dotenv_values  # noqa: E402

from chronoscalp.filters.session_filter import normalize_trading_hours_mode  # noqa: E402
from chronoscalp.telegram.control_bot import TelegramControlBot  # noqa: E402
from chronoscalp.telegram.keyboards import (  # noqa: E402
    HELP_TEXT,
    MAIN_KEYBOARD,
    SETTINGS_KEYBOARD,
)


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    chat = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not chat:
        raise SystemExit("TELEGRAM_CHAT_ID missing")

    bot = TelegramControlBot()
    hours = normalize_trading_hours_mode((bot.settings.sessions or {}).get("trading_hours_mode"))
    bot.send(
        chat,
        HELP_TEXT
        + f"\n\nساعات فعلی: {hours}\n"
        + "دکمه‌های «سشن لندن/آمریکا» و «۲۴ ساعته» الان روی منو هستند.\n"
        + "(کیبورد دوباره تنظیم شد)",
        reply_markup=MAIN_KEYBOARD,
    )
    bot.send(
        chat,
        "برای ساعات معامله همین دکمه‌ها یا مسیر تنظیمات را بزنید.",
        reply_markup=SETTINGS_KEYBOARD,
    )
    print("KEYBOARD_RESTORED", chat, "hours=", hours)


if __name__ == "__main__":
    main()
