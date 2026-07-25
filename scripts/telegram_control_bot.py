#!/usr/bin/env python3
"""ChronoScalp Telegram control bot — process start/stop, status, P&L, kill-switch.

Requires TELEGRAM_BOT_TOKEN (+ optional TELEGRAM_CHAT_ID allow-list) in .env.

Create the bot with @BotFather, then:
  1. Put token in .env
  2. Message the bot /start
  3. Set TELEGRAM_CHAT_ID to your chat id (from /whoami)
  4. python scripts/telegram_control_bot.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chronoscalp.telegram.control_bot import TelegramControlBot  # noqa: E402


def main() -> None:
    TelegramControlBot().run_forever()


if __name__ == "__main__":
    main()
