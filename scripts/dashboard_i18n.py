"""Bilingual strings for the Streamlit dashboard (EN / FA)."""

from __future__ import annotations

from typing import Any

Lang = str  # "en" | "fa"

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "page_title": "ChronoScalp Dashboard",
        "title": "ChronoScalp Dashboard",
        "caption": "Local monitoring — state, spreads, backtests, logs (no broker connection required)",
        "lang_btn": "🇮🇷 فارسی",
        "sidebar_deploy": "Deployment",
        "broker": "Broker",
        "data_source": "Data source",
        "oanda_env": "OANDA env",
        "state_file": "State file",
        "risk_limits": "Risk (hard limits)",
        "max_risk": "Max risk/trade",
        "min_rr": "Min R:R",
        "max_daily": "Max daily loss",
        "refresh": "Refresh",
        "kill_switch": "Kill switch",
        "kill_active": "ACTIVE",
        "kill_off": "Off",
        "live_gate": "Live gate",
        "live_open": "OPEN",
        "live_closed": "Closed",
        "live_gate_help": "Requires CHRONOSCALP_CONFIRM_LIVE=yes in .env",
        "symbols": "Symbols",
        "ml_gate": "ML gate",
        "ml_on": "On",
        "ml_off": "Off",
        "trading_halted": "Trading halted",
        "trading_state": "Trading state",
        "no_state": "No state at `{path}` — bot has not run in {mode} mode yet.",
        "open_positions": "Open positions",
        "dedup_keys": "Dedup keys",
        "last_saved": "Last saved",
        "no_open_positions": "No open positions in state.",
        "raw_json": "Raw state JSON",
        "col_symbol": "Symbol",
        "col_ticket": "Ticket",
        "spread_section": "Live spread sampling",
        "no_spread": "No spread samples for {symbol}. Enable `spread_filter.sample_live_spread` and run the bot.",
        "spread_metric": "{symbol} spread (pips)",
        "max_allowed": "max allowed",
        "backtest_section": "Backtest reports",
        "no_reports": "No reports in `data/reports/`. Run: `python scripts/run_backtest.py --symbol XAUUSD --report data/reports/xauusd.json`",
        "trades": "Trades",
        "win_rate": "Win rate",
        "profit_factor": "Profit factor",
        "return_pct": "Return",
        "logs_section": "Recent logs",
        "no_logs": "(no logs yet — start run_live.py to generate logs)",
        "no_log_files": "(no log files found)",
        "footer": "ChronoScalp · {ts} · See docs/DEPLOY_NL_VPS.md for Netherlands VPS setup",
    },
    "fa": {
        "page_title": "داشبورد ChronoScalp",
        "title": "داشبورد ChronoScalp",
        "caption": "مانیتورینگ محلی — وضعیت، اسپرد، بک‌تست و لاگ (بدون اتصال بروکر)",
        "lang_btn": "🇬🇧 English",
        "sidebar_deploy": "استقرار",
        "broker": "بروکر",
        "data_source": "منبع داده",
        "oanda_env": "محیط OANDA",
        "state_file": "فایل state",
        "risk_limits": "ریسک (محدودیت‌های سخت)",
        "max_risk": "حداکثر ریسک/معامله",
        "min_rr": "حداقل R:R",
        "max_daily": "حداکثر ضرر روزانه",
        "refresh": "بروزرسانی",
        "kill_switch": "کلید توقف",
        "kill_active": "فعال",
        "kill_off": "خاموش",
        "live_gate": "درگاه live",
        "live_open": "باز",
        "live_closed": "بسته",
        "live_gate_help": "نیاز به CHRONOSCALP_CONFIRM_LIVE=yes در .env",
        "symbols": "نمادها",
        "ml_gate": "فیلتر ML",
        "ml_on": "روشن",
        "ml_off": "خاموش",
        "trading_halted": "معامله متوقف شده",
        "trading_state": "وضعیت معاملات",
        "no_state": "فایل state در `{path}` وجود ندارد — bot هنوز در حالت {mode} اجرا نشده.",
        "open_positions": "پوزیشن‌های باز",
        "dedup_keys": "کلیدهای dedup",
        "last_saved": "آخرین ذخیره",
        "no_open_positions": "پوزیشن بازی در state نیست.",
        "raw_json": "JSON خام state",
        "col_symbol": "نماد",
        "col_ticket": "تیکت",
        "spread_section": "نمونه‌گیری اسپرد زنده",
        "no_spread": "نمونه اسپرد برای {symbol} نیست. `spread_filter.sample_live_spread` را فعال کنید و bot را اجرا کنید.",
        "spread_metric": "اسپرد {symbol} (پیپ)",
        "max_allowed": "حداکثر مجاز",
        "backtest_section": "گزارش‌های بک‌تست",
        "no_reports": "گزارشی در `data/reports/` نیست. اجرا کنید: `python scripts/run_backtest.py --symbol XAUUSD --report data/reports/xauusd.json`",
        "trades": "معاملات",
        "win_rate": "نرخ برد",
        "profit_factor": "ضریب سود",
        "return_pct": "بازده",
        "logs_section": "لاگ‌های اخیر",
        "no_logs": "(هنوز لاگی نیست — run_live.py را اجرا کنید)",
        "no_log_files": "(فایل لاگ پیدا نشد)",
        "footer": "ChronoScalp · {ts} · راهنمای VPS هلند: docs/DEPLOY_NL_VPS.md",
    },
}


def t(key: str, lang: Lang, **kwargs: Any) -> str:
    """Translate ``key`` for ``lang``, with optional ``str.format`` kwargs."""
    text = TEXT.get(lang, TEXT["en"]).get(key, TEXT["en"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text


def rtl_css(lang: Lang) -> str:
    if lang != "fa":
        return ""
    return """
    <style>
      section.main > div { direction: rtl; text-align: right; }
      [data-testid="stSidebar"] > div:first-child { direction: rtl; text-align: right; }
      code, pre, .stCode { direction: ltr !important; text-align: left !important; }
    </style>
    """
