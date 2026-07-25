"""Tests for Telegram control-bot command dispatch (no network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chronoscalp.telegram.control_bot import TelegramControlBot


def _fake_settings(tmp_path: Path, *, live_confirmed: bool = False) -> SimpleNamespace:
    secrets = SimpleNamespace(
        telegram_bot_token="token-test",
        telegram_chat_id="42",
        chronoscalp_stop_trading="no",
        live_trading_confirmed=live_confirmed,
    )
    return SimpleNamespace(
        secrets=secrets,
        execution={"state_dir": str(tmp_path / "state"), "broker": "paper"},
        alerting={"timeout_seconds": 5},
        backtest={"initial_balance": 10_000},
        symbols=["XAUUSD"],
    )


@pytest.fixture
def bot(tmp_path: Path) -> TelegramControlBot:
    started: list[str] = []
    stopped: list[bool] = []

    def start_fn(mode: str) -> tuple[bool, str]:
        started.append(mode)
        return True, f"started {mode}"

    def stop_fn() -> tuple[bool, str]:
        stopped.append(True)
        return True, "stopped"

    ctrl = TelegramControlBot(
        settings=_fake_settings(tmp_path),  # type: ignore[arg-type]
        start_fn=start_fn,
        stop_fn=stop_fn,
        running_fn=lambda: False,
        pid_fn=lambda: None,
        logs_fn=lambda _n: ["line-a", "line-b"],
        license_check=lambda _s: None,
    )
    ctrl.send = MagicMock()  # type: ignore[method-assign]
    ctrl._started = started  # type: ignore[attr-defined]
    ctrl._stopped = stopped  # type: ignore[attr-defined]
    return ctrl


def test_unauthorized_chat_rejected(bot: TelegramControlBot) -> None:
    bot.handle(99, "/status")
    bot.send.assert_called_once()
    assert "Unauthorized" in bot.send.call_args.args[1]


def test_help_sends_keyboard(bot: TelegramControlBot) -> None:
    bot.handle(42, "/help")
    kwargs = bot.send.call_args.kwargs
    assert "reply_markup" in kwargs
    assert "keyboard" in kwargs["reply_markup"]


def test_start_paper_via_button(bot: TelegramControlBot) -> None:
    bot.handle(42, "استارت Paper")
    assert bot._started == ["paper"]  # type: ignore[attr-defined]
    assert "✅" in bot.send.call_args.args[1]


def test_start_live_blocked_without_confirm(bot: TelegramControlBot) -> None:
    bot.handle(42, "/start_live")
    assert bot._started == []  # type: ignore[attr-defined]
    assert "CHRONOSCALP_CONFIRM_LIVE" in bot.send.call_args.args[1]


def test_start_live_allowed_when_confirmed(tmp_path: Path) -> None:
    started: list[str] = []
    ctrl = TelegramControlBot(
        settings=_fake_settings(tmp_path, live_confirmed=True),  # type: ignore[arg-type]
        start_fn=lambda mode: started.append(mode) or (True, "ok"),
        stop_fn=lambda: (True, "ok"),
        running_fn=lambda: False,
        pid_fn=lambda: None,
        logs_fn=lambda _n: [],
        license_check=lambda _s: None,
    )
    ctrl.send = MagicMock()  # type: ignore[method-assign]
    ctrl.handle(42, "/start_live")
    assert started == ["live"]


def test_bot_stop_and_halt_resume(bot: TelegramControlBot, tmp_path: Path) -> None:
    bot.handle(42, "توقف ربات")
    assert bot._stopped == [True]  # type: ignore[attr-defined]

    bot.handle(42, "/halt")
    assert bot.kill.is_active()
    bot.handle(42, "/resume")
    assert not bot.kill.is_active()


def test_status_and_logs(bot: TelegramControlBot) -> None:
    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "متوقف" in text
    assert "XAUUSD" in text

    bot.handle(42, "/logs")
    assert "line-a" in bot.send.call_args.args[1]


def test_stop_alias_is_kill_switch_not_process_stop(bot: TelegramControlBot) -> None:
    """Legacy /stop must halt entries, not kill the process."""
    bot.handle(42, "/stop")
    assert bot.kill.is_active()
    assert bot._stopped == []  # type: ignore[attr-defined]


def test_bind_chat_persists_when_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict[str, str] = {}

    def fake_save(token: str, chat_id: str, env_path=None) -> None:  # noqa: ANN001
        saved["token"] = token
        saved["chat_id"] = chat_id

    monkeypatch.setattr(
        "chronoscalp.saas.broker_wizard.save_telegram_credentials",
        fake_save,
    )
    settings = _fake_settings(tmp_path)
    settings.secrets.telegram_chat_id = ""
    ctrl = TelegramControlBot(
        settings=settings,  # type: ignore[arg-type]
        start_fn=lambda _m: (True, "ok"),
        stop_fn=lambda: (True, "ok"),
        running_fn=lambda: False,
        pid_fn=lambda: None,
        logs_fn=lambda _n: [],
        license_check=lambda _s: None,
    )
    ctrl.allowed_chat = ""
    ctrl.send = MagicMock()  # type: ignore[method-assign]
    ctrl.handle(777, "/whoami")
    assert saved["chat_id"] == "777"
    assert ctrl.allowed_chat == "777"