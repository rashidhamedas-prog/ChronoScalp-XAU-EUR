"""Bilingual FA/EN UI strings for the local dashboard (Phase 3)."""

from __future__ import annotations

from typing import Literal

Lang = Literal["fa", "en"]

_STRINGS: dict[str, dict[Lang, str]] = {
    "nav.overview": {"en": "Overview", "fa": "نمای کلی"},
    "nav.trades": {"en": "Trades", "fa": "معاملات"},
    "nav.strategies": {"en": "Strategies", "fa": "استراتژی‌ها"},
    "nav.risk": {"en": "Risk", "fa": "ریسک"},
    "nav.news": {"en": "News", "fa": "تقویم خبری"},
    "nav.diagnostics": {"en": "Diagnostics", "fa": "عیب‌یابی"},
    "nav.settings": {"en": "Settings", "fa": "تنظیمات"},
    "status.active": {"en": "Active", "fa": "فعال"},
    "status.halted": {"en": "Halted", "fa": "متوقف"},
    "status.error": {"en": "Error", "fa": "خطا"},
    "metric.win_rate": {"en": "Win rate", "fa": "نرخ برد"},
    "metric.expectancy": {"en": "Expectancy (net)", "fa": "انتظار ریاضی (خالص)"},
    "metric.profit_factor": {"en": "Profit factor (net)", "fa": "ضریب سود (خالص)"},
    "metric.dsr": {"en": "Deflated Sharpe", "fa": "شارپ تعدیل‌شده"},
    "risk.confirm": {
        "en": "Type CONFIRM to apply risk change",
        "fa": "برای اعمال تغییر ریسک CONFIRM را بنویسید",
    },
}


def t(key: str, lang: Lang = "en") -> str:
    """Translate ``key``; missing keys return the key itself (fail visible)."""
    entry = _STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key


def catalog(lang: Lang = "en") -> dict[str, str]:
    """Full string table for the requested language (dashboard bootstrap)."""
    return {key: t(key, lang) for key in sorted(_STRINGS)}
