"""Telegram keyboards, labels, and help text for ChronoScalp control bot.

Settings are **menu-only** (reply keyboards): tap to toggle / choose — no typing
required for symbols, strategies, hours, or risk. Credential wizards (MT5/OANDA
passwords) still accept typed secrets because those values cannot be enumerated.
"""

from __future__ import annotations

from typing import Any

# --- Main control ---
BTN_STATUS = "وضعیت"
BTN_PNL = "سود/زیان"
BTN_OPEN = "پوزیشن‌ها"
BTN_START_PAPER = "استارت Paper"
BTN_START_LIVE = "استارت Live"
BTN_STOP_BOT = "توقف ربات"
BTN_HALT = "توقف ورود"
BTN_RESUME = "ادامه ورود"
BTN_LOGS = "لاگ"
BTN_HELP = "راهنما"
BTN_SETTINGS = "تنظیمات"
BTN_MENU = "منوی اصلی"

# --- Settings hub ---
BTN_CONN = "اتصال"
BTN_CONTROL = "کنترل"
BTN_HOURS_MENU = "ساعات معامله"
BTN_RISK_MENU = "ریسک معامله"
BTN_SUMMARY = "خلاصه تنظیمات"

# --- Connection ---
BTN_CONN_SHOW = "نمایش اتصال"
BTN_PROVIDER_MT5 = "بروکر MT5"
BTN_PROVIDER_OANDA = "بروکر OANDA"
BTN_MODE_PAPER = "حالت Paper"
BTN_MODE_LIVE = "حالت Live"
BTN_TEST_CONN = "تست اتصال"
BTN_LIVE_ON = "تأیید Live روشن"
BTN_LIVE_OFF = "تأیید Live خاموش"
BTN_OANDA_PRACTICE = "OANDA practice"
BTN_OANDA_LIVE = "OANDA live"
BTN_CANCEL = "لغو"

# --- Control / trading settings ---
BTN_CTRL_SHOW = "نمایش کنترل"
BTN_SYMBOLS = "نمادها"
BTN_STRATEGIES = "استراتژی‌ها"
BTN_HOURS_LONDON = "سشن لندن/آمریکا"
BTN_HOURS_24H = "۲۴ ساعته"
BTN_RISK_05 = "ریسک ۰٫۵٪"
BTN_RISK_10 = "ریسک ۱٪"
BTN_RISK_15 = "ریسک ۱٫۵٪"
BTN_DAILY_LOSS_ON = "قفل ضرر روزانه روشن"
BTN_DAILY_LOSS_OFF = "قفل ضرر روزانه خاموش"
BTN_DAILY_LOSS_UNLOCK = "باز کردن قفل امروز"

BTN_SYM_ALL = "همه نمادها ✓"
BTN_SYM_NONE = "پاک کردن نمادها"
BTN_SYM_SAVE = "ذخیره نمادها"
BTN_STRAT_ALL = "همه استراتژی‌ها ✓"
BTN_STRAT_NONE = "فقط MACD/trend"
BTN_STRAT_SAVE = "ذخیره استراتژی‌ها"

# Toggle markers (menu-only pickers)
TOGGLE_ON = "✅"
TOGGLE_OFF = "⬜"

STRATEGY_LABELS: dict[str, str] = {
    "delta": "دلتا (طلا/یورو)",
    "smc_confluence": "SMC",
    "liquidity_volume": "نقدینگی+حجم",
    "ultra_scalp": "اسکلپ S15",
    "news_straddle": "استرادل خبر",
}
STRATEGY_LABEL_TO_KEY: dict[str, str] = {v: k for k, v in STRATEGY_LABELS.items()}


def toggle_label(name: str, *, enabled: bool) -> str:
    """Build a tap-to-toggle reply-keyboard label."""
    mark = TOGGLE_ON if enabled else TOGGLE_OFF
    return f"{mark} {name}"


def parse_toggle_label(text: str) -> str | None:
    """Extract the payload after ✅/⬜, or None if not a toggle button."""
    raw = (text or "").strip()
    for mark in (TOGGLE_ON, TOGGLE_OFF, "✓", "○"):
        prefix = f"{mark} "
        if raw.startswith(prefix):
            return raw[len(prefix) :].strip() or None
    return None


def _chunk_buttons(labels: list[str], per_row: int = 2) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for label in labels:
        row.append({"text": label})
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def symbols_keyboard(catalog: list[str], selected: list[str] | set[str]) -> dict[str, Any]:
    """Reply keyboard: one toggle per symbol + save / bulk actions."""
    selected_u = {str(s).strip().upper() for s in selected}
    labels = [toggle_label(sym, enabled=str(sym).strip().upper() in selected_u) for sym in catalog]
    rows = _chunk_buttons(labels, per_row=2)
    rows.append([{"text": BTN_SYM_ALL}, {"text": BTN_SYM_NONE}])
    rows.append([{"text": BTN_SYM_SAVE}, {"text": BTN_CANCEL}])
    rows.append([{"text": BTN_CONTROL}, {"text": BTN_SETTINGS}])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def strategies_keyboard(selected: list[str] | set[str]) -> dict[str, Any]:
    """Reply keyboard: toggle each known strategy + save."""
    selected_l = {str(s).strip().lower() for s in selected}
    labels = [
        toggle_label(STRATEGY_LABELS[key], enabled=key in selected_l) for key in STRATEGY_LABELS
    ]
    rows = _chunk_buttons(labels, per_row=2)
    rows.append([{"text": BTN_STRAT_ALL}, {"text": BTN_STRAT_NONE}])
    rows.append([{"text": BTN_STRAT_SAVE}, {"text": BTN_CANCEL}])
    rows.append([{"text": BTN_CONTROL}, {"text": BTN_SETTINGS}])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def hours_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [
            [{"text": BTN_HOURS_LONDON}, {"text": BTN_HOURS_24H}],
            [{"text": BTN_SUMMARY}, {"text": BTN_SETTINGS}],
            [{"text": BTN_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def risk_keyboard(*, daily_loss_enabled: bool = True) -> dict[str, Any]:
    daily_row = (
        [{"text": BTN_DAILY_LOSS_OFF}, {"text": BTN_DAILY_LOSS_UNLOCK}]
        if daily_loss_enabled
        else [{"text": BTN_DAILY_LOSS_ON}, {"text": BTN_DAILY_LOSS_UNLOCK}]
    )
    return {
        "keyboard": [
            [{"text": BTN_RISK_05}, {"text": BTN_RISK_10}, {"text": BTN_RISK_15}],
            daily_row,
            [{"text": BTN_SUMMARY}, {"text": BTN_SETTINGS}],
            [{"text": BTN_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


MAIN_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": BTN_STATUS}, {"text": BTN_PNL}, {"text": BTN_OPEN}],
        [{"text": BTN_START_PAPER}, {"text": BTN_START_LIVE}, {"text": BTN_STOP_BOT}],
        [{"text": BTN_HALT}, {"text": BTN_RESUME}],
        [{"text": BTN_LOGS}, {"text": BTN_SETTINGS}, {"text": BTN_HELP}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

SETTINGS_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": BTN_SUMMARY}],
        [{"text": BTN_CONN}, {"text": BTN_CONTROL}],
        [{"text": BTN_SYMBOLS}, {"text": BTN_STRATEGIES}],
        [{"text": BTN_HOURS_MENU}, {"text": BTN_RISK_MENU}],
        [{"text": BTN_LIVE_ON}, {"text": BTN_LIVE_OFF}],
        [{"text": BTN_MENU}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

CONN_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": BTN_CONN_SHOW}, {"text": BTN_TEST_CONN}],
        [{"text": BTN_PROVIDER_MT5}, {"text": BTN_PROVIDER_OANDA}],
        [{"text": BTN_MODE_PAPER}, {"text": BTN_MODE_LIVE}],
        [{"text": BTN_LIVE_ON}, {"text": BTN_LIVE_OFF}],
        [{"text": BTN_SETTINGS}, {"text": BTN_MENU}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

CONTROL_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": BTN_CTRL_SHOW}],
        [{"text": BTN_SYMBOLS}, {"text": BTN_STRATEGIES}],
        [{"text": BTN_HOURS_MENU}, {"text": BTN_RISK_MENU}],
        [{"text": BTN_HOURS_LONDON}, {"text": BTN_HOURS_24H}],
        [{"text": BTN_RISK_05}, {"text": BTN_RISK_10}, {"text": BTN_RISK_15}],
        [{"text": BTN_DAILY_LOSS_ON}, {"text": BTN_DAILY_LOSS_OFF}],
        [{"text": BTN_DAILY_LOSS_UNLOCK}],
        [{"text": BTN_SETTINGS}, {"text": BTN_MENU}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

OANDA_ENV_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": BTN_OANDA_PRACTICE}, {"text": BTN_OANDA_LIVE}],
        [{"text": BTN_CANCEL}],
    ],
    "resize_keyboard": True,
}

HELP_TEXT = (
    "ChronoScalp — کنترل از تلگرام\n\n"
    "اجرا (منوی اصلی):\n"
    "وضعیت · سود/زیان · پوزیشن‌ها · استارت/توقف · Kill Switch · لاگ\n\n"
    "تنظیمات (فقط از منو — بدون تایپ):\n"
    "• نمادها → تیک بزنید → ذخیره نمادها\n"
    "• استراتژی‌ها → دلتا / SMC / نقدینگی / اسکلپ / استرادل خبر → ذخیره\n"
    "• ساعات معامله → لندن/آمریکا یا ۲۴ ساعته\n"
    "• ریسک → ۰٫۵٪ / ۱٪ / ۱٫۵٪ (سقف امن ۱٪)\n"
    "• قفل ضرر روزانه → روشن/خاموش یا باز کردن قفل امروز\n"
    "• اتصال → بروکر / حالت Paper|Live / تست / تأیید Live\n\n"
    "رمز MT5/OANDA فقط در ویزارد اتصال تایپ می‌شود (اجباری).\n"
    "نکته: Live بدون تأیید Live روشن استارت نمی‌شود.\n"
    "بعد از تغییر تنظیمات ربات را Stop سپس Start کنید."
)

# Map button labels / command aliases → canonical command key.
ALIASES: dict[str, str] = {
    "/start": "help",
    "/help": "help",
    BTN_HELP: "help",
    "راهنما": "help",
    "/whoami": "whoami",
    "/status": "status",
    BTN_STATUS: "status",
    "وضعیت": "status",
    "/pnl": "pnl",
    BTN_PNL: "pnl",
    "سود/زیان": "pnl",
    "/open": "open",
    BTN_OPEN: "open",
    "پوزیشن‌ها": "open",
    "/start_paper": "start_paper",
    BTN_START_PAPER: "start_paper",
    "استارت paper": "start_paper",
    "/start_live": "start_live",
    BTN_START_LIVE: "start_live",
    "استارت live": "start_live",
    "/bot_stop": "bot_stop",
    "/stop_bot": "bot_stop",
    BTN_STOP_BOT: "bot_stop",
    "توقف ربات": "bot_stop",
    "/halt": "halt",
    "/stop": "halt",
    BTN_HALT: "halt",
    "توقف ورود": "halt",
    "/resume": "resume",
    BTN_RESUME: "resume",
    "ادامه ورود": "resume",
    "/logs": "logs",
    BTN_LOGS: "logs",
    "لاگ": "logs",
    "/menu": "menu",
    BTN_MENU: "menu",
    "منوی اصلی": "menu",
    "/settings": "settings",
    BTN_SETTINGS: "settings",
    "تنظیمات": "settings",
    "/conn": "conn",
    "/connection": "conn",
    BTN_CONN: "conn_menu",
    "اتصال": "conn_menu",
    BTN_CONN_SHOW: "conn",
    "نمایش اتصال": "conn",
    BTN_CONTROL: "control_menu",
    "کنترل": "control_menu",
    BTN_CTRL_SHOW: "config",
    BTN_SUMMARY: "config",
    "نمایش کنترل": "config",
    "خلاصه تنظیمات": "config",
    "/config": "config",
    BTN_PROVIDER_MT5: "wizard_mt5",
    "بروکر mt5": "wizard_mt5",
    BTN_PROVIDER_OANDA: "wizard_oanda",
    "بروکر oanda": "wizard_oanda",
    BTN_MODE_PAPER: "mode_paper",
    "حالت paper": "mode_paper",
    BTN_MODE_LIVE: "mode_live",
    "حالت live": "mode_live",
    BTN_TEST_CONN: "test_conn",
    "تست اتصال": "test_conn",
    "/test_conn": "test_conn",
    BTN_LIVE_ON: "live_on",
    "تأیید live روشن": "live_on",
    BTN_LIVE_OFF: "live_off",
    "تأیید live خاموش": "live_off",
    "/live_confirm": "live_confirm",
    BTN_SYMBOLS: "symbols_menu",
    "نمادها": "symbols_menu",
    "/symbols": "symbols",
    BTN_STRATEGIES: "strategies_menu",
    "استراتژی‌ها": "strategies_menu",
    "/strategies": "strategies",
    BTN_HOURS_MENU: "hours_menu",
    "ساعات معامله": "hours_menu",
    BTN_RISK_MENU: "risk_menu",
    "ریسک معامله": "risk_menu",
    BTN_HOURS_LONDON: "hours_london_ny",
    "سشن لندن/آمریکا": "hours_london_ny",
    BTN_HOURS_24H: "hours_24h",
    "۲۴ ساعته": "hours_24h",
    "/hours": "hours",
    BTN_RISK_05: "risk_05",
    "ریسک ۰٫۵٪": "risk_05",
    BTN_RISK_10: "risk_10",
    "ریسک ۱٪": "risk_10",
    BTN_RISK_15: "risk_15",
    "ریسک ۱٫۵٪": "risk_15",
    "/risk": "risk",
    BTN_DAILY_LOSS_ON: "daily_loss_on",
    "قفل ضرر روزانه روشن": "daily_loss_on",
    BTN_DAILY_LOSS_OFF: "daily_loss_off",
    "قفل ضرر روزانه خاموش": "daily_loss_off",
    BTN_DAILY_LOSS_UNLOCK: "daily_loss_unlock",
    "باز کردن قفل امروز": "daily_loss_unlock",
    "/daily_loss": "daily_loss",
    "/provider": "provider",
    "/mode": "mode",
    "/set_mt5": "set_mt5",
    "/set_oanda": "set_oanda",
    BTN_OANDA_PRACTICE: "oanda_env_practice",
    BTN_OANDA_LIVE: "oanda_env_live",
    BTN_CANCEL: "cancel",
    "لغو": "cancel",
    BTN_SYM_ALL: "symbols_all",
    BTN_SYM_NONE: "symbols_none",
    BTN_SYM_SAVE: "symbols_save",
    "ذخیره نمادها": "symbols_save",
    BTN_STRAT_ALL: "strategies_all",
    BTN_STRAT_NONE: "strategies_none",
    BTN_STRAT_SAVE: "strategies_save",
    "ذخیره استراتژی‌ها": "strategies_save",
}
