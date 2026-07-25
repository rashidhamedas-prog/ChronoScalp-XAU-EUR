#!/usr/bin/env python3
"""One-shot: restore UTF-8 Persian keyboard for the bound Telegram chat."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import dotenv_values  # noqa: E402

from chronoscalp.telegram.control_bot import TelegramControlBot  # noqa: E402
from chronoscalp.telegram.keyboards import HELP_TEXT, MAIN_KEYBOARD  # noqa: E402


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    chat = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not chat:
        raise SystemExit("TELEGRAM_CHAT_ID missing")

    bot = TelegramControlBot()
    bot.send(
        chat,
        HELP_TEXT + "\n\n(کیبورد فارسی دوباره تنظیم شد)",
        reply_markup=MAIN_KEYBOARD,
    )
    print("KEYBOARD_RESTORED", chat)


if __name__ == "__main__":
    main()
