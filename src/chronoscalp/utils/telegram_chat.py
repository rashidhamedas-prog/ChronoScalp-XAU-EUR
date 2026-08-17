"""Normalize Telegram chat targets for Bot API sendMessage.

Accepts a numeric chat id, ``@username``, a bare username, or a ``t.me`` URL.
Private users usually need a numeric id; ``@username`` only works for public
channels/groups (and only after the target has started the bot).
"""

from __future__ import annotations

import re

DEFAULT_TRADE_OPEN_COPY_CHAT = "@taranomrashid"

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_NUMERIC_ID_RE = re.compile(r"^-?\d{5,20}$")


class InvalidTelegramChatRef(ValueError):
    """Raised when a chat id / username cannot be used as a Bot API target."""


def normalize_telegram_chat_ref(raw: str) -> str:
    """Return a Bot API ``chat_id`` string (numeric or ``@username``).

    Raises:
        InvalidTelegramChatRef: empty or malformed input.
    """
    text = (raw or "").strip()
    if not text:
        raise InvalidTelegramChatRef("chat id is empty")

    lowered = text.lower()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :].split("?", 1)[0].strip("/")
            break

    if text.startswith("@"):
        text = text[1:]
    text = text.strip()
    if not text:
        raise InvalidTelegramChatRef("chat id is empty")

    if _NUMERIC_ID_RE.fullmatch(text):
        return text
    if _USERNAME_RE.fullmatch(text):
        return f"@{text}"
    raise InvalidTelegramChatRef(
        "use @username or a numeric chat_id (the recipient must Start this bot)"
    )
