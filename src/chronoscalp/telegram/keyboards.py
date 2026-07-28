"""Telegram keyboards, labels, and help text for ChronoScalp control bot."""

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

# --- Control ---
BTN_CTRL_SHOW = "نمایش کنترل"
BTN_SYMBOLS = "نمادها"
BTN_STRATEGIES = "استراتژی‌ها"
BTN_HOURS_LONDON = "سشن لندن/آمریکا"
BTN_HOURS_24H = "۲۴ ساعته"
BTN_RISK_05 = "ریسک ۰٫۵٪"
BTN_RISK_10 = "ریسک ۱٪"
BTN_RISK_15 = "ریسک ۱٫۵٪"

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
        [{"text": BTN_CONN}, {"text": BTN_CONTROL}],
        [{"text": BTN_CONN_SHOW}, {"text": BTN_CTRL_SHOW}],
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
        [{"text": BTN_HOURS_LONDON}, {"text": BTN_HOURS_24H}],
        [{"text": BTN_RISK_05}, {"text": BTN_RISK_10}, {"text": BTN_RISK_15}],
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
    "ChronoScalp — کنترل کامل از تلگرام\n\n"
    "اجرا:\n"
    "/status /start_paper /start_live /bot_stop\n"
    "/pnl /open /halt /resume /logs\n\n"
    "اتصال:\n"
    "/conn — خلاصه اتصال\n"
    "/provider mt5|oanda\n"
    "/mode paper|live\n"
    "/set_mt5 LOGIN PASS SERVER [PATH]\n"
    "/set_oanda TOKEN ACCOUNT [practice|live]\n"
    "/test_conn\n"
    "/live_confirm yes|no\n\n"
    "کنترل:\n"
    "/config — همه تنظیمات\n"
    "/symbols XAUUSD,EURUSD\n"
    "/strategies smc_confluence,liquidity_volume,ultra_scalp\n"
    "/hours london_ny|always_on_24h\n"
    "/risk 0.5|1|1.5\n\n"
    "منو: /settings\n"
    "نکته: Live بدون CHRONOSCALP_CONFIRM_LIVE=yes استارت نمی‌شود."
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
    "نمایش کنترل": "config",
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
    BTN_SYMBOLS: "symbols_prompt",
    "نمادها": "symbols_prompt",
    "/symbols": "symbols",
    BTN_STRATEGIES: "strategies_prompt",
    "استراتژی‌ها": "strategies_prompt",
    "/strategies": "strategies",
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
    "/provider": "provider",
    "/mode": "mode",
    "/set_mt5": "set_mt5",
    "/set_oanda": "set_oanda",
    BTN_OANDA_PRACTICE: "oanda_env_practice",
    BTN_OANDA_LIVE: "oanda_env_live",
    BTN_CANCEL: "cancel",
    "لغو": "cancel",
}
