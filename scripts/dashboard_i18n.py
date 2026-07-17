"""Bilingual strings for the Streamlit dashboard (EN / FA)."""

from __future__ import annotations

from typing import Any

Lang = str  # "en" | "fa"

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "page_title": "ChronoScalp Dashboard",
        "title": "ChronoScalp Dashboard",
        "caption": "Live monitoring — P&L, trades, spreads, state, logs",
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
        "auto_refresh": "Auto-refresh (sec)",
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
        "live_stats_section": "Live trading statistics",
        "live_stats_caption": (
            "Updated from trade journal ({mode}) — refreshes automatically while this page is open"
        ),
        "no_live_trades": "No trades yet. Start the bot; opens/closes appear here in real time.",
        "stat_net_pnl": "Net P&L",
        "stat_today_pnl": "Today P&L",
        "stat_closed": "Closed trades",
        "stat_open": "Open trades",
        "stat_total": "Total trades",
        "stat_win_rate": "Win rate",
        "stat_avg_pnl": "Avg P&L / trade",
        "stat_avg_return": "Avg return",
        "stat_profit_factor": "Profit factor",
        "stat_expectancy": "Expectancy",
        "stat_wins": "Wins",
        "stat_losses": "Losses",
        "stat_best": "Best trade",
        "stat_worst": "Worst trade",
        "stat_streaks": "Max streak W/L",
        "open_trades_table": "Open positions",
        "closed_trades_table": "Closed trades (latest)",
        "no_closed_trades": "No closed trades yet.",
        "showing_latest": "Showing latest {n} of {total}",
        "col_direction": "Side",
        "col_volume": "Volume",
        "col_entry": "Entry",
        "col_exit": "Exit",
        "col_sl": "SL",
        "col_tp": "TP",
        "col_open_time": "Opened",
        "col_close_time": "Closed",
        "col_pnl": "P&L",
        "col_r": "R",
        "col_reason": "Exit reason",
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
        "no_spread": (
            "No spread samples for {symbol}. Enable `spread_filter.sample_live_spread` "
            "and run the bot."
        ),
        "spread_metric": "{symbol} spread (pips)",
        "max_allowed": "max allowed",
        "backtest_section": "Backtest reports",
        "no_reports": (
            "No reports in `data/reports/`. Run: "
            "`python scripts/run_backtest.py --symbol XAUUSD --report data/reports/xauusd.json`"
        ),
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
        "caption": "مانیتورینگ لحظه‌ای — سود/زیان، معاملات، اسپرد، وضعیت و لاگ",
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
        "auto_refresh": "بروزرسانی خودکار (ثانیه)",
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
        "live_stats_section": "آمار لحظه‌ای معاملات",
        "live_stats_caption": (
            "از ژورنال معاملات ({mode}) — تا وقتی صفحه باز است خودکار تازه می‌شود"
        ),
        "no_live_trades": (
            "هنوز معامله‌ای نیست. ربات را اجرا کنید؛ باز و بسته‌شدن‌ها اینجا لحظه‌ای دیده می‌شوند."
        ),
        "stat_net_pnl": "سود/زیان خالص",
        "stat_today_pnl": "سود/زیان امروز",
        "stat_closed": "معاملات بسته‌شده",
        "stat_open": "معاملات باز",
        "stat_total": "کل معاملات",
        "stat_win_rate": "نرخ برد",
        "stat_avg_pnl": "میانگین سود/معامله",
        "stat_avg_return": "میانگین بازدهی",
        "stat_profit_factor": "ضریب سود",
        "stat_expectancy": "انتظار ریاضی",
        "stat_wins": "بردها",
        "stat_losses": "باخت‌ها",
        "stat_best": "بهترین معامله",
        "stat_worst": "بدترین معامله",
        "stat_streaks": "بیشترین برد/باخت پیاپی",
        "open_trades_table": "پوزیشن‌های باز",
        "closed_trades_table": "معاملات بسته‌شده (آخرین‌ها)",
        "no_closed_trades": "هنوز معامله بسته‌شده‌ای نیست.",
        "showing_latest": "نمایش {n} مورد آخر از {total}",
        "col_direction": "سمت",
        "col_volume": "حجم",
        "col_entry": "ورود",
        "col_exit": "خروج",
        "col_sl": "حد ضرر",
        "col_tp": "حد سود",
        "col_open_time": "باز شدن",
        "col_close_time": "بسته شدن",
        "col_pnl": "سود/زیان",
        "col_r": "R",
        "col_reason": "دلیل خروج",
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
        "no_spread": (
            "نمونه اسپرد برای {symbol} نیست. `spread_filter.sample_live_spread` را فعال کنید "
            "و bot را اجرا کنید."
        ),
        "spread_metric": "اسپرد {symbol} (پیپ)",
        "max_allowed": "حداکثر مجاز",
        "backtest_section": "گزارش‌های بک‌تست",
        "no_reports": (
            "گزارشی در `data/reports/` نیست. اجرا کنید: "
            "`python scripts/run_backtest.py --symbol XAUUSD --report data/reports/xauusd.json`"
        ),
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
