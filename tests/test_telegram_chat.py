from __future__ import annotations

import pytest

from chronoscalp.utils.telegram_chat import (
    DEFAULT_TRADE_OPEN_COPY_CHAT,
    InvalidTelegramChatRef,
    normalize_telegram_chat_ref,
)


def test_default_copy_target() -> None:
    assert DEFAULT_TRADE_OPEN_COPY_CHAT == "@taranomrashid"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@taranomrashid", "@taranomrashid"),
        ("taranomrashid", "@taranomrashid"),
        ("https://t.me/taranomrashid", "@taranomrashid"),
        ("123456789", "123456789"),
        ("-1001234567890", "-1001234567890"),
    ],
)
def test_normalize_telegram_chat_ref(raw: str, expected: str) -> None:
    assert normalize_telegram_chat_ref(raw) == expected


@pytest.mark.parametrize("raw", ["", "@@", "ab", "not a user!", "t.me/"])
def test_normalize_telegram_chat_ref_rejects(raw: str) -> None:
    with pytest.raises(InvalidTelegramChatRef):
        normalize_telegram_chat_ref(raw)
