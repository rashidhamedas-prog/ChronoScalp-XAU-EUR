"""Tests for Telegram control-bot command dispatch (no network)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chronoscalp.telegram.control_bot import TelegramControlBot, telegram_error_summary
from chronoscalp.telegram.keyboards import (
    BTN_TRADE_NOTIFY,
    BTN_TRADE_NOTIFY_OFF,
    BTN_TRADE_NOTIFY_SET_ID,
    MAIN_KEYBOARD,
    SETTINGS_KEYBOARD,
)


def _fake_settings(tmp_path: Path, *, live_confirmed: bool = False) -> SimpleNamespace:
    secrets = SimpleNamespace(
        telegram_bot_token="token-test",
        telegram_chat_id="42",
        chronoscalp_stop_trading="no",
        live_trading_confirmed=live_confirmed,
        mt5_login=0,
        mt5_password="",
        mt5_server="",
        mt5_terminal_path="",
        oanda_api_token="",
        oanda_account_id="",
    )
    return SimpleNamespace(
        secrets=secrets,
        execution={"state_dir": str(tmp_path / "state"), "broker": "paper"},
        alerting={"timeout_seconds": 5},
        backtest={"initial_balance": 10_000},
        symbols=["XAUUSD"],
        available_symbols=["XAUUSD", "EURUSD", "USDJPY"],
        risk={"active_risk_per_trade_pct": 1.0, "max_risk_per_trade_pct": 1.0},
        strategy={
            "derive_strategies_from_symbols": True,
            "symbol_catalogs": {
                "XAUUSD": ["delta", "operator_style", "news_straddle"],
                "EURUSD": ["operator_style", "news_straddle"],
            },
            "enabled_strategies": ["smc_confluence"],
            "use_smc_confluence": True,
            "use_liquidity_volume": False,
            "use_ultra_scalp": False,
            "use_news_straddle": False,
        },
        sessions={"trading_hours_mode": "london_ny"},
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
    text = bot.send.call_args.args[1]
    assert "مجاز به کنترل" in text
    assert "99" in text


def test_help_sends_keyboard(bot: TelegramControlBot) -> None:
    bot.handle(42, "/help")
    kwargs = bot.send.call_args.kwargs
    assert "reply_markup" in kwargs
    assert kwargs["reply_markup"] == MAIN_KEYBOARD


def test_settings_menu(bot: TelegramControlBot) -> None:
    bot.handle(42, "تنظیمات")
    assert bot.send.call_args.kwargs["reply_markup"] == SETTINGS_KEYBOARD


def test_start_paper_via_button(bot: TelegramControlBot) -> None:
    bot.handle(42, "استارت Paper")
    assert bot._started == ["paper"]  # type: ignore[attr-defined]
    assert bot._stopped == []  # type: ignore[attr-defined]
    assert "✅" in bot.send.call_args.args[1]


def test_start_paper_restarts_when_already_running(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chronoscalp.telegram.control_bot.time.sleep", lambda _s: None)
    bot._running_fn = lambda: True  # type: ignore[method-assign]
    bot.handle(42, "استارت Paper")
    assert bot._stopped == [True]  # type: ignore[attr-defined]
    assert bot._started == ["paper"]  # type: ignore[attr-defined]
    text = bot.send.call_args.args[1]
    assert "stopped" in text
    assert "started paper" in text


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


def test_stop_alias_stops_process_not_kill_switch(bot: TelegramControlBot) -> None:
    bot.handle(42, "/stop")
    assert bot._stopped == [True]  # type: ignore[attr-defined]
    assert not bot.kill.is_active()


def test_halt_button_is_kill_switch_not_process_stop(bot: TelegramControlBot) -> None:
    bot.handle(42, "توقف ورود")
    assert bot.kill.is_active()
    assert bot._stopped == []  # type: ignore[attr-defined]
    assert "فرآیند ربات هنوز روشن است" in bot.send.call_args.args[1]


def test_stop_persian_alias(bot: TelegramControlBot) -> None:
    bot.handle(42, "استاپ")
    assert bot._stopped == [True]  # type: ignore[attr-defined]


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


def test_mt5_wizard_flow(bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.save_mt5_credentials",
        lambda login, password, server, path="": calls.update(
            login=login, password=password, server=server, path=path
        ),
    )
    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.apply_broker_to_settings_yaml",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.UserConfigStore",
        lambda: SimpleNamespace(
            config=SimpleNamespace(
                broker=SimpleNamespace(
                    provider="mt5",
                    mode="paper",
                    oanda_environment="practice",
                    onboarding_complete=False,
                )
            ),
            save=lambda: None,
        ),
    )
    monkeypatch.setattr(bot, "_reload_settings", lambda: None)
    monkeypatch.setattr(bot, "_save_user_broker", lambda **k: None)

    bot.handle(42, "بروکر MT5")
    bot.handle(42, "123456")
    bot.handle(42, "secret")
    bot.handle(42, "ICMarkets-Demo")
    bot.handle(42, "-")
    assert calls["login"] == "123456"
    assert calls["server"] == "ICMarkets-Demo"
    assert "✅" in bot.send.call_args.args[1]


def test_risk_preset_button(bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.apply_risk_preset",
        lambda pct: 1.0 if pct > 1 else pct,
    )
    monkeypatch.setattr(bot, "_reload_settings", lambda: None)
    bot.handle(42, "ریسک ۱٫۵٪")
    assert (
        "1.0%" in bot.send.call_args.args[1]
        or "۱" in bot.send.call_args.args[1]
        or "ریسک" in bot.send.call_args.args[1]
    )


def test_symbols_menu_toggle_and_save(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[list[str]] = []

    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.apply_active_symbols",
        lambda parts, allowed=None: saved.append(list(parts)) or list(parts),
    )
    monkeypatch.setattr(bot, "_reload_settings", lambda: None)

    bot.handle(42, "نمادها")
    assert bot._pending[42]["flow"] == "symbols_menu"
    kb = bot.send.call_args.kwargs["reply_markup"]
    assert any("✅ XAUUSD" in (b.get("text") or "") for row in kb["keyboard"] for b in row)

    bot.handle(42, "⬜ EURUSD")
    assert "EURUSD" in bot._pending[42]["selected"]

    bot.handle(42, "ذخیره نمادها")
    assert saved and "XAUUSD" in saved[-1] and "EURUSD" in saved[-1]
    assert "✅" in bot.send.call_args.args[1]


def test_strategies_button_is_read_only_catalog(bot: TelegramControlBot) -> None:
    bot.handle(42, "استراتژی‌ها")
    text = bot.send.call_args.args[1]
    assert "دلتا" in text
    assert "XAUUSD" in text
    assert "استرادل خبر" in text
    assert "ذخیره استراتژی" not in text
    kb = bot.send.call_args.kwargs.get("reply_markup") or {}
    labels = {b["text"] for row in kb.get("keyboard", []) for b in row}
    assert not any("ذخیره استراتژی" in label for label in labels)


def test_status_lists_per_symbol_catalog(bot: TelegramControlBot) -> None:
    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "استراتژی" in text
    assert "XAUUSD" in text
    assert "دلتا" in text
    assert "استرادل خبر" in text
    assert "پولبک VWAP" not in text


def test_status_shows_the_loaded_stop_geometry(bot: TelegramControlBot) -> None:
    """The operator must be able to confirm a restart picked up the loss fixes.

    The live bleed ran on a stale config and nothing on screen said so.
    """
    bot.settings.risk.update({"trailing_start_r_multiple": 1.0, "trailing_stop_atr_multiple": 1.5})
    bot.settings.risk["spread_ma_guard"] = {"enabled": True, "multiplier": 2.5}
    bot.settings.higher_trend_names = lambda **_kw: ["M15", "M5"]
    bot.settings.strategy["delta"] = {"stop_atr_source": "htf", "stop_atr_htf_index": 1}

    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "از 1R به بعد" in text
    assert "median×2.5" in text
    assert "ATR M5" in text


def test_status_names_the_real_frame_when_the_index_overshoots(
    bot: TelegramControlBot,
) -> None:
    """delta.reference_stop_atr clamps the index, so status must clamp too."""
    bot.settings.higher_trend_names = lambda **_kw: ["M15", "M5"]
    bot.settings.strategy["delta"] = {"stop_atr_source": "htf", "stop_atr_htf_index": 9}
    bot.handle(42, "/status")
    assert "ATR M5" in bot.send.call_args.args[1]


def test_status_flags_a_trigger_atr_stop_as_unfixed(bot: TelegramControlBot) -> None:
    bot.settings.strategy["delta"] = {"stop_atr_source": "trigger"}
    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "کندل تریگر" in text
    assert "⚠️" in text


def test_status_warns_when_an_unvalidated_symbol_is_live_selected(
    bot: TelegramControlBot,
) -> None:
    bot.settings.symbols = ["XAUUSD", "EURUSD"]
    bot.settings.strategy["delta"] = {
        "allowed_symbols": ["XAUUSD", "EURUSD"],
        "symbol_validation": {"XAUUSD": "validated", "EURUSD": "failed"},
    }
    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "XAUUSD ✅" in text
    assert "EURUSD ❌" in text
    assert "بدون شواهد سودآوری" in text


def test_status_has_no_warning_when_only_validated_symbols_are_active(
    bot: TelegramControlBot,
) -> None:
    bot.settings.symbols = ["XAUUSD"]
    bot.settings.strategy["delta"] = {
        "allowed_symbols": ["XAUUSD"],
        "symbol_validation": {"XAUUSD": "validated", "EURUSD": "failed"},
    }
    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "XAUUSD ✅" in text
    assert "بدون شواهد سودآوری" not in text


def test_status_survives_a_config_without_delta(bot: TelegramControlBot) -> None:
    """A profile that never enabled Delta must not break /status."""
    bot.settings.strategy.pop("delta", None)
    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "وضعیت ChronoScalp" in text


def test_settings_hub_has_all_sections(bot: TelegramControlBot) -> None:
    bot.handle(42, "تنظیمات")
    kb = bot.send.call_args.kwargs["reply_markup"]
    labels = {b["text"] for row in kb["keyboard"] for b in row}
    assert "نمادها" in labels
    assert "استراتژی نمادها" in labels
    assert "ساعات معامله" in labels
    assert "ریسک معامله" in labels
    assert "اتصال" in labels
    assert "اعلان معامله" in labels
    assert "تأیید Live روشن" in labels


def test_risk_menu_shows_mistake_memory(bot: TelegramControlBot) -> None:
    bot.settings.risk["mistake_memory"] = {
        "enabled": True,
        "cooldown_minutes": 240,
    }
    bot.handle(42, "ریسک معامله")
    text = bot.send.call_args.args[1]
    assert "یادگیری از اشتباه" in text
    assert "240" in text
    kb = bot.send.call_args.kwargs["reply_markup"]
    labels = {b["text"] for row in kb["keyboard"] for b in row}
    assert "یادگیری از اشتباه خاموش" in labels
    assert "یادگیری از اشتباه روشن" not in labels


def test_mistake_memory_toggle_persists(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []

    def _fake_apply(enabled: bool, **_kwargs: object) -> bool:
        called.append(enabled)
        return enabled

    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.apply_mistake_memory_enabled",
        _fake_apply,
    )
    monkeypatch.setattr(bot, "_reload_settings", lambda: None)

    bot.handle(42, "یادگیری از اشتباه خاموش")
    assert called == [False]
    text = bot.send.call_args.args[1]
    assert "یادگیری از اشتباه" in text
    assert "خاموش" in text
    assert "Stop" in text and "Start" in text

    bot.handle(42, "یادگیری از اشتباه روشن")
    assert called == [False, True]
    text_on = bot.send.call_args.args[1]
    assert "روشن" in text_on


def test_trade_notify_menu_shows_default_username(bot: TelegramControlBot) -> None:
    bot.handle(42, BTN_TRADE_NOTIFY)
    text = bot.send.call_args.args[1]
    assert "@taranomrashid" in text
    kb = bot.send.call_args.kwargs["reply_markup"]
    labels = {b["text"] for row in kb["keyboard"] for b in row}
    assert "تغییر آی‌دی اعلان" in labels
    assert "ارسال تست اعلان" in labels
    assert "اعلان معامله خاموش" in labels


def test_trade_notify_toggle_persists(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []

    def _fake_apply(enabled: bool, **_kwargs: object) -> bool:
        called.append(enabled)
        return enabled

    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.apply_trade_open_copy_enabled",
        _fake_apply,
    )
    monkeypatch.setattr(bot, "_reload_settings", lambda: None)

    bot.handle(42, BTN_TRADE_NOTIFY_OFF)
    assert called == [False]
    text = bot.send.call_args.args[1]
    assert "اعلان معامله" in text
    assert "خاموش" in text


def test_trade_notify_set_id_via_command(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[str] = []

    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.apply_trade_open_copy_chat_id",
        lambda raw: saved.append(raw) or "@newtarget",
    )
    monkeypatch.setattr(bot, "_reload_settings", lambda: None)
    monkeypatch.setattr(bot, "_try_trade_notify_ping", lambda _target: "✅ ping")

    bot.handle(42, "/notify_id @newtarget")
    assert saved == ["@newtarget"]
    text = bot.send.call_args.args[1]
    assert "@newtarget" in text
    assert "ذخیره" in text


def test_trade_notify_set_id_wizard(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[str] = []

    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.apply_trade_open_copy_chat_id",
        lambda raw: saved.append(raw) or "@taranomrashid",
    )
    monkeypatch.setattr(bot, "_reload_settings", lambda: None)
    monkeypatch.setattr(bot, "_try_trade_notify_ping", lambda _target: "✅ ping")

    bot.handle(42, BTN_TRADE_NOTIFY_SET_ID)
    assert bot._pending[42]["flow"] == "trade_notify_id"
    bot.handle(42, "@taranomrashid")
    assert saved == ["@taranomrashid"]
    assert 42 not in bot._pending
    assert "@taranomrashid" in bot.send.call_args.args[1]


def test_open_positions_from_fresh_broker_snapshot(bot: TelegramControlBot, tmp_path: Path) -> None:
    import json
    from datetime import UTC, datetime

    state = Path(bot.settings.execution["state_dir"])
    state.mkdir(parents=True, exist_ok=True)
    (state / "trade_journal_live.json").write_text(
        json.dumps({"mode": "live", "open_trades": [], "closed_trades": []}),
        encoding="utf-8",
    )
    payload = {
        "mode": "live",
        "updated_at": datetime.now(tz=UTC).isoformat(),
        "positions": [
            {
                "ticket": 111,
                "symbol": "ETHUSD",
                "direction": "buy",
                "volume": 1.5,
                "entry_price": 2000.0,
                "profit": -1.25,
            }
        ],
    }
    (state / "broker_positions_live.json").write_text(json.dumps(payload), encoding="utf-8")
    bot.handle(42, "پوزیشن‌ها")
    text = bot.send.call_args.args[1]
    assert "زنده از بروکر" in text
    assert "ETHUSD" in text
    assert "#111" in text


def test_open_positions_empty_live_snapshot(bot: TelegramControlBot, tmp_path: Path) -> None:
    import json
    from datetime import UTC, datetime

    state = Path(bot.settings.execution["state_dir"])
    state.mkdir(parents=True, exist_ok=True)
    (state / "trade_journal_live.json").write_text(
        json.dumps({"mode": "live", "open_trades": [], "closed_trades": []}),
        encoding="utf-8",
    )
    payload = {
        "mode": "live",
        "updated_at": datetime.now(tz=UTC).isoformat(),
        "account": {
            "login": 91323064,
            "server": "LiteFinance-MT5-Demo",
            "equity": 9426.47,
            "margin": 0.0,
        },
        "positions": [],
    }
    (state / "broker_positions_live.json").write_text(json.dumps(payload), encoding="utf-8")
    bot.handle(42, "پوزیشن‌ها")
    text = bot.send.call_args.args[1]
    assert "پوزیشن بازی روی بروکر نیست" in text
    assert "91323064" in text
    assert "equity=9426.47" in text


def test_open_positions_mt5_does_not_call_initialize(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot.settings.execution["broker"] = "mt5"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Telegram must not call fetch_mt5_open_positions")

    monkeypatch.setattr(
        "chronoscalp.saas.broker_wizard.fetch_mt5_open_positions",
        boom,
    )
    bot.handle(42, "پوزیشن‌ها")
    assert bot.send.called
    assert "پوزیشن" in bot.send.call_args.args[1]


def test_logs_button_sends_tail(bot: TelegramControlBot) -> None:
    bot.handle(42, "لاگ")
    text = bot.send.call_args.args[1]
    assert "line-a" in text
    assert "line-b" in text


def test_tail_logs_reads_last_lines_only(tmp_path: Path) -> None:
    from chronoscalp.saas.process_control import tail_logs

    log = tmp_path / "chronoscalp_2026-08-24.log"
    log.write_text(("old\n" * 500) + "last-a\nlast-b\n", encoding="utf-8")
    assert tail_logs(2, log_dir=tmp_path) == ["last-a", "last-b"]


def test_status_warns_when_logs_show_mt5_ipc(bot: TelegramControlBot) -> None:
    bot._logs_fn = lambda _n: ["MT5 initialize() failed err=(-10005, 'IPC timeout')"]
    bot.handle(42, "وضعیت")
    assert "IPC timeout" in bot.send.call_args.args[1]


def test_gold_and_eur_catalogs_show_operator_style(bot: TelegramControlBot) -> None:
    bot.settings.symbols = ["XAUUSD", "EURUSD"]
    bot.handle(42, "استراتژی نمادها")
    text = bot.send.call_args.args[1]
    gold_line = next(line for line in text.splitlines() if line.startswith("• XAUUSD"))
    eur_line = next(line for line in text.splitlines() if line.startswith("• EURUSD"))
    assert "دلتا" in gold_line and "سبک اپراتور" in gold_line and "استرادل خبر" in gold_line
    assert "سبک اپراتور" in eur_line and "استرادل خبر" in eur_line
    assert "دلتا" not in eur_line
    assert "پولبک VWAP" not in text
    assert "SMC" not in gold_line
    assert 42 not in bot._pending


def test_status_shows_settings_source_and_mode(bot: TelegramControlBot) -> None:
    bot.handle(42, "/status")
    text = bot.send.call_args.args[1]
    assert "منبع تنظیم" in text
    assert "دلتا" in text
    assert "shadow_only" not in text


def test_getupdates_http_timeout_outlives_long_poll(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_post(*_a: object, **kwargs: object) -> MagicMock:
        captured["timeout"] = kwargs.get("timeout")
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = lambda: None
        response.json.return_value = {"ok": True, "result": []}
        return response

    monkeypatch.setattr("chronoscalp.telegram.control_bot.requests.post", fake_post)
    bot._api("getUpdates", offset=0, timeout=25)
    timeout = captured["timeout"]
    assert isinstance(timeout, tuple)
    connect_s, read_s = timeout
    assert connect_s >= 10
    assert read_s >= 70


def test_telegram_poll_error_omits_token(bot: TelegramControlBot, caplog, monkeypatch) -> None:
    import requests

    token = bot.token
    poison = (
        f"HTTPSConnectionPool(host='api.telegram.org', port=443): "
        f"Max retries exceeded with url: /bot{token}/getUpdates"
    )

    def _boom(*_a, **_k):
        raise requests.RequestException(poison)

    monkeypatch.setattr(bot, "_api", _boom)
    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.time.sleep",
        lambda *_a, **_k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    caplog.set_level("WARNING")
    with contextlib.suppress(KeyboardInterrupt):
        bot.run_forever()
    logged = caplog.text
    assert token not in logged
    assert f"bot{token}" not in logged
    assert "api.telegram.org" not in logged
    summary = telegram_error_summary(requests.RequestException(poison))
    assert token not in summary
    assert "api.telegram.org" not in summary


def test_telegram_error_summary_keeps_short_reason() -> None:
    import requests

    wrapped = requests.RequestException("ConnectionError")
    assert telegram_error_summary(wrapped) == "ConnectionError"


def test_send_retries_then_succeeds(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests

    calls = {"n": 0}

    def fake_post(*_a: object, **kwargs: object) -> MagicMock:
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("connection dropped")
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = lambda: None
        response.json.return_value = {"ok": True, "result": {}}
        return response

    monkeypatch.setattr("chronoscalp.telegram.control_bot.requests.post", fake_post)
    monkeypatch.setattr("chronoscalp.telegram.control_bot.time.sleep", lambda _s: None)
    # Fixture replaced send with a MagicMock — restore the real method.
    bot.send = TelegramControlBot.send.__get__(bot, TelegramControlBot)  # type: ignore[method-assign]
    bot.send(42, "hi")
    assert calls["n"] == 3
    timeout = None

    def capture_timeout(*_a: object, **kwargs: object) -> MagicMock:
        nonlocal timeout
        timeout = kwargs.get("timeout")
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = lambda: None
        response.json.return_value = {"ok": True, "result": {}}
        return response

    monkeypatch.setattr("chronoscalp.telegram.control_bot.requests.post", capture_timeout)
    bot.send(42, "again")
    assert timeout == (5.0, 10.0)


def test_poll_readtimeout_retries_without_sleep(
    bot: TelegramControlBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests

    calls = {"n": 0, "slept": []}

    def _api(method: str, **_params: object) -> dict:
        calls["n"] += 1
        if method == "deleteWebhook":
            return {"ok": True}
        if calls["n"] >= 4:
            raise KeyboardInterrupt()
        raise requests.RequestException("ReadTimeout")

    monkeypatch.setattr(bot, "_api", _api)
    monkeypatch.setattr(
        "chronoscalp.telegram.control_bot.time.sleep",
        lambda seconds: calls["slept"].append(seconds),
    )
    with contextlib.suppress(KeyboardInterrupt):
        bot.run_forever()
    assert calls["slept"] == []
    assert calls["n"] >= 4
