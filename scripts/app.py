#!/usr/bin/env python3
"""ChronoScalp Control Panel — لایسنس، اتصال بروکر، استارت ربات، مانیتورینگ.

Usage:
    streamlit run scripts/app.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPTS))

import streamlit as st  # noqa: E402

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.licensing import (  # noqa: E402
    ActivationStore,
    LicenseStore,
    LicenseTier,
    activate_license,
    check_license,
    issue_license,
)
from chronoscalp.orchestration.kill_switch import STOP_FILE_NAME, KillSwitch  # noqa: E402
from chronoscalp.saas import (  # noqa: E402
    UserConfigStore,
    apply_broker_to_settings_yaml,
    bot_is_running,
    save_mt5_credentials,
    save_oanda_credentials,
    save_telegram_credentials,
    start_bot,
    stop_bot,
    test_mt5_connection,
    test_oanda_connection,
)
from chronoscalp.saas.broker_wizard import enable_alerting_override  # noqa: E402
from dashboard_i18n import rtl_css  # noqa: E402

# Extended UI strings (FA-first SaaS panel)
UI = {
    "fa": {
        "title": "پنل ChronoScalp",
        "caption": "اشتراک · اتصال بروکر · کنترل ربات · مانیتورینگ",
        "nav_home": "خانه",
        "nav_license": "لایسنس / اشتراک",
        "nav_broker": "اتصال بروکر",
        "nav_control": "کنترل ربات",
        "nav_monitor": "مانیتورینگ",
        "nav_admin": "مدیر لایسنس (فروشنده)",
        "nav_ib": "معرفی IB",
        "lang": "🇬🇧 English",
        "welcome": "خوش آمدید",
        "step_license": "۱. لایسنس",
        "step_broker": "۲. بروکر",
        "step_run": "۳. اجرا",
        "license_status": "وضعیت لایسنس",
        "enter_key": "کلید لایسنس خود را وارد کنید",
        "activate": "فعال‌سازی",
        "valid": "معتبر",
        "invalid": "نامعتبر",
        "broker_title": "اتصال آسان به بروکر",
        "broker_hint": "فقط اطلاعات حساب خودتان را وارد کنید. رمزها فقط در فایل .env محلی ذخیره می‌شوند.",
        "provider": "نوع بروکر",
        "mode": "حالت اجرا",
        "paper": "Paper (پیشنهادی برای شروع)",
        "live": "Live",
        "test_conn": "تست اتصال",
        "save": "ذخیره و اعمال",
        "oanda_token": "OANDA API Token",
        "oanda_account": "OANDA Account ID",
        "oanda_env": "محیط OANDA",
        "mt5_login": "MT5 Login",
        "mt5_password": "MT5 Password",
        "mt5_server": "MT5 Server",
        "mt5_path": "مسیر ترمینال (اختیاری)",
        "control_title": "استارت / استاپ ربات",
        "bot_running": "در حال اجرا",
        "bot_stopped": "متوقف",
        "start": "▶ استارت ربات",
        "stop": "⏹ استاپ ربات",
        "kill_on": "فعال کردن Kill Switch",
        "kill_off": "برداشتن Kill Switch",
        "admin_title": "صدور لایسنس برای مشتری",
        "admin_secret": "رمز ادمین (LICENSE_ADMIN_SECRET)",
        "tier": "پلن اشتراک",
        "email": "ایمیل مشتری",
        "name": "نام مشتری",
        "issue": "صدور کلید",
        "ib_title": "کمیسیون از طریق IB بروکر",
        "ib_body": (
            "بهترین مدل درآمد پایدار: مشتری با **لینک معرفی (IB)** شما در بروکر ثبت‌نام کند. "
            "خود بروکر به شما کمیسیون می‌دهد — نه از سود معامله داخل ربات.\n\n"
            "مراحل پیشنهادی:\n"
            "1. در OANDA (یا بروکر همکار) برنامه Introducing Broker / Partner را فعال کنید\n"
            "2. لینک referral خود را به مشتری بدهید\n"
            "3. مشتری لایسنس ChronoScalp را می‌خرد + با لینک شما حساب می‌سازد\n"
            "4. شما از اشتراک + کمیسیون IB درآمد دارید\n\n"
            "⚠️ برداشت خودکار ۱٪ از سود معامله مشتری از نظر فنی/قانونی در این معماری پشتیبانی نمی‌شود."
        ),
        "refresh": "بروزرسانی",
        "onboarding_done": "راه‌اندازی اولیه تکمیل شد",
    },
    "en": {
        "title": "ChronoScalp Panel",
        "caption": "Subscription · Broker connect · Bot control · Monitor",
        "nav_home": "Home",
        "nav_license": "License",
        "nav_broker": "Broker",
        "nav_control": "Bot control",
        "nav_monitor": "Monitor",
        "nav_admin": "License admin (seller)",
        "nav_ib": "IB referral",
        "lang": "🇮🇷 فارسی",
        "welcome": "Welcome",
        "step_license": "1. License",
        "step_broker": "2. Broker",
        "step_run": "3. Run",
        "license_status": "License status",
        "enter_key": "Enter your license key",
        "activate": "Activate",
        "valid": "Valid",
        "invalid": "Invalid",
        "broker_title": "Easy broker connection",
        "broker_hint": "Enter your own account credentials. Secrets are stored only in local .env.",
        "provider": "Broker type",
        "mode": "Run mode",
        "paper": "Paper (recommended first)",
        "live": "Live",
        "test_conn": "Test connection",
        "save": "Save & apply",
        "oanda_token": "OANDA API Token",
        "oanda_account": "OANDA Account ID",
        "oanda_env": "OANDA environment",
        "mt5_login": "MT5 Login",
        "mt5_password": "MT5 Password",
        "mt5_server": "MT5 Server",
        "mt5_path": "Terminal path (optional)",
        "control_title": "Start / Stop bot",
        "bot_running": "Running",
        "bot_stopped": "Stopped",
        "start": "▶ Start bot",
        "stop": "⏹ Stop bot",
        "kill_on": "Enable Kill Switch",
        "kill_off": "Clear Kill Switch",
        "admin_title": "Issue license for customer",
        "admin_secret": "Admin secret (LICENSE_ADMIN_SECRET)",
        "tier": "Plan",
        "email": "Customer email",
        "name": "Customer name",
        "issue": "Issue key",
        "ib_title": "Earn via broker IB",
        "ib_body": (
            "Best sustainable model: customer signs up at the broker via **your IB link**. "
            "The broker pays you — not a skim of trade PnL from the bot.\n\n"
            "Suggested flow:\n"
            "1. Enable Introducing Broker / Partner at OANDA (or partner broker)\n"
            "2. Share your referral link with customers\n"
            "3. Customer buys ChronoScalp license + opens account via your link\n"
            "4. You earn subscription + IB rebate\n\n"
            "⚠️ Automatic 1% of customer trade profit is not supported in this architecture."
        ),
        "refresh": "Refresh",
        "onboarding_done": "Onboarding complete",
    },
}


def _t(key: str) -> str:
    lang = st.session_state.get("lang", "fa")
    return UI.get(lang, UI["fa"]).get(key, key)


def _init() -> None:
    if "lang" not in st.session_state:
        st.session_state.lang = "fa"
    if "page" not in st.session_state:
        st.session_state.page = "home"


def _settings():
    get_settings.cache_clear()
    return get_settings()


def page_home(settings) -> None:
    st.subheader(_t("welcome"))
    lic = check_license(
        admin_secret=settings.secrets.license_admin_secret,
        require_license=bool(settings.raw.get("licensing", {}).get("require_license", True)),
    )
    user = UserConfigStore().config
    c1, c2, c3 = st.columns(3)
    c1.metric(_t("license_status"), _t("valid") if lic.valid else _t("invalid"))
    c2.metric("Broker", user.broker.provider)
    c3.metric("Mode", user.broker.mode)
    st.markdown(f"""
### مسیر سریع
1. **{_t("step_license")}** — کلید اشتراک را فعال کنید  
2. **{_t("step_broker")}** — OANDA یا MT5 را وصل و تست کنید  
3. **{_t("step_run")}** — ربات را Paper استارت کنید  
""")
    if lic.valid and user.broker.onboarding_complete:
        st.success(_t("onboarding_done"))


def page_license(settings) -> None:
    st.subheader(_t("nav_license"))
    require = bool(settings.raw.get("licensing", {}).get("require_license", True))
    status = check_license(
        admin_secret=settings.secrets.license_admin_secret,
        require_license=require,
    )
    if status.valid:
        st.success(
            f"{_t('valid')} · {status.tier} · "
            f"days={status.days_remaining} · {status.customer_email or '—'}"
        )
    else:
        st.warning(status.reason)

    key = st.text_input(_t("enter_key"), placeholder="CS-MONTHLY-XXXX-XXXX-XXXX-XXXX")
    if st.button(_t("activate"), type="primary"):
        result = activate_license(
            key=key,
            admin_secret=settings.secrets.license_admin_secret,
            license_store=LicenseStore(),
            activation_store=ActivationStore(),
        )
        if result.valid:
            st.success(result.reason)
            st.rerun()
        else:
            st.error(result.reason)


def page_broker(settings) -> None:
    st.subheader(_t("broker_title"))
    st.caption(_t("broker_hint"))
    store = UserConfigStore()
    cfg = store.config

    provider = st.radio(
        _t("provider"),
        ["oanda", "mt5"],
        index=0 if cfg.broker.provider != "mt5" else 1,
        horizontal=True,
        format_func=lambda x: (
            "OANDA (Linux / VPS هلند)" if x == "oanda" else "MetaTrader 5 (Windows)"
        ),
    )
    mode = st.radio(
        _t("mode"),
        ["paper", "live"],
        index=0 if cfg.broker.mode != "live" else 1,
        horizontal=True,
        format_func=lambda x: _t("paper") if x == "paper" else _t("live"),
    )

    if provider == "oanda":
        env = st.selectbox(
            _t("oanda_env"),
            ["practice", "live"],
            index=0 if cfg.broker.oanda_environment != "live" else 1,
        )
        token = st.text_input(_t("oanda_token"), type="password", value="")
        account = st.text_input(_t("oanda_account"), value="")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button(_t("test_conn")):
                res = test_oanda_connection(token, account, env)
                (st.success if res.ok else st.error)(res.message)
        with col_b:
            if st.button(_t("save"), type="primary"):
                if not token or not account:
                    st.error("توکن و Account ID لازم است")
                else:
                    save_oanda_credentials(token, account)
                    apply_broker_to_settings_yaml(provider, mode, env)
                    cfg.broker.provider = provider
                    cfg.broker.mode = mode
                    cfg.broker.oanda_environment = env
                    cfg.broker.onboarding_complete = True
                    store.save()
                    get_settings.cache_clear()
                    st.success("ذخیره شد — settings.yaml و .env به‌روز شدند")
    else:
        login = st.text_input(_t("mt5_login"))
        password = st.text_input(_t("mt5_password"), type="password")
        server = st.text_input(_t("mt5_server"))
        path = st.text_input(_t("mt5_path"), value=r"C:\Program Files\MetaTrader 5\terminal64.exe")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button(_t("test_conn")):
                try:
                    res = test_mt5_connection(int(login or 0), password, server, path)
                except ValueError:
                    res = type("R", (), {"ok": False, "message": "Login باید عدد باشد"})()
                (st.success if res.ok else st.error)(res.message)
        with col_b:
            if st.button(_t("save"), type="primary"):
                save_mt5_credentials(login, password, server, path)
                apply_broker_to_settings_yaml(provider, mode)
                cfg.broker.provider = provider
                cfg.broker.mode = mode
                cfg.broker.onboarding_complete = True
                store.save()
                get_settings.cache_clear()
                st.success("ذخیره شد")

    st.divider()
    st.markdown("#### Telegram (اختیاری)")
    tg_token = st.text_input("TELEGRAM_BOT_TOKEN", type="password")
    tg_chat = st.text_input("TELEGRAM_CHAT_ID")
    if st.button("ذخیره تلگرام"):
        save_telegram_credentials(tg_token, tg_chat)
        enable_alerting_override()
        get_settings.cache_clear()
        st.success("تلگرام ذخیره و alerting فعال شد")


def page_control(settings) -> None:
    st.subheader(_t("control_title"))
    running = bot_is_running()
    st.metric("Bot", _t("bot_running") if running else _t("bot_stopped"))

    user = UserConfigStore().config
    mode = user.broker.mode if user.broker.mode in ("paper", "live") else "paper"
    st.write(f"Mode از پروفایل کاربر: **{mode}**")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(_t("start"), type="primary", disabled=running):
            try:
                from chronoscalp.licensing import require_valid_license

                require_valid_license(settings)
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                ok, msg = start_bot(mode=mode)
                (st.success if ok else st.warning)(msg)
                st.rerun()
    with c2:
        if st.button(_t("stop"), disabled=not running):
            ok, msg = stop_bot()
            (st.success if ok else st.warning)(msg)
            st.rerun()

    state_dir = Path(settings.execution.get("state_dir", "data/state"))
    ks = KillSwitch(state_dir=state_dir, env_stop=settings.secrets.chronoscalp_stop_trading)
    st.write(f"Kill switch: **{'ACTIVE' if ks.is_active() else 'off'}**")
    k1, k2 = st.columns(2)
    with k1:
        if st.button(_t("kill_on")):
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / STOP_FILE_NAME).touch()
            st.rerun()
    with k2:
        if st.button(_t("kill_off")):
            p = state_dir / STOP_FILE_NAME
            if p.exists():
                p.unlink()
            st.rerun()


def page_monitor(settings) -> None:
    st.subheader(_t("nav_monitor"))
    state_dir = Path(settings.execution.get("state_dir", "data/state"))
    mode = UserConfigStore().config.broker.mode
    path = state_dir / f"trading_state_{mode}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        st.json(data)
        tickets = data.get("open_tickets") or {}
        if tickets:
            st.dataframe(
                pd.DataFrame([{"symbol": k, "ticket": v} for k, v in tickets.items()]),
                hide_index=True,
                use_container_width=True,
            )
    else:
        st.info("هنوز state ذخیره نشده — ربات را یک‌بار اجرا کنید")

    spread_dir = Path(settings.spread_filter.get("spread_history_dir", "data/spread_history"))
    for symbol in settings.symbols:
        csv_path = spread_dir / f"{symbol}_spread.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            st.line_chart(df.set_index("timestamp")["spread_pips"], height=180)
            break

    log_path = Path("logs/bot_stdout.log")
    if log_path.exists():
        st.code(
            "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        )


def page_admin(settings) -> None:
    st.subheader(_t("admin_title"))
    st.caption("فقط برای فروشنده — کلید برای مشتری صادر کنید")
    secret = st.text_input(
        _t("admin_secret"),
        type="password",
        value=settings.secrets.license_admin_secret or "",
    )
    tier = st.selectbox(
        _t("tier"),
        [t.value for t in LicenseTier],
        format_func=lambda x: {
            "trial": "Trial (۷ روز)",
            "monthly": "ماهانه",
            "yearly": "سالانه",
            "lifetime": "مادام‌العمر",
        }.get(x, x),
    )
    email = st.text_input(_t("email"))
    name = st.text_input(_t("name"))
    if st.button(_t("issue"), type="primary"):
        if not secret.strip():
            st.error("LICENSE_ADMIN_SECRET را تنظیم کنید")
        else:
            rec = issue_license(
                admin_secret=secret,
                tier=LicenseTier(tier),
                customer_email=email,
                customer_name=name,
            )
            store = LicenseStore()
            store.add(rec)
            st.success("کلید صادر شد — آن را به مشتری بدهید:")
            st.code(rec.key)
            st.json(rec.to_dict())

    st.divider()
    store = LicenseStore()
    rows = [r.to_dict() for r in store.list_all()]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def page_ib() -> None:
    st.subheader(_t("ib_title"))
    st.markdown(_t("ib_body"))
    settings = _settings()
    link = settings.raw.get("saas", {}).get("ib_referral_url", "")
    if link:
        st.link_button("لینک معرفی بروکر شما", link)
    else:
        st.info("لینک IB خود را در `config/settings.yaml` → `saas.ib_referral_url` قرار دهید.")


def main() -> None:
    _init()
    lang = st.session_state.lang
    st.set_page_config(page_title=_t("title"), page_icon="📈", layout="wide")
    st.markdown(rtl_css(lang), unsafe_allow_html=True)

    settings = _settings()

    with st.sidebar:
        if st.button(_t("lang"), use_container_width=True):
            st.session_state.lang = "en" if lang == "fa" else "fa"
            st.rerun()
        st.title(_t("title"))
        st.caption(_t("caption"))
        pages = [
            ("home", _t("nav_home")),
            ("license", _t("nav_license")),
            ("broker", _t("nav_broker")),
            ("control", _t("nav_control")),
            ("monitor", _t("nav_monitor")),
            ("ib", _t("nav_ib")),
            ("admin", _t("nav_admin")),
        ]
        for key, label in pages:
            if st.button(label, use_container_width=True, key=f"nav_{key}"):
                st.session_state.page = key
                st.rerun()
        if st.button(_t("refresh"), use_container_width=True):
            get_settings.cache_clear()
            st.rerun()

    page = st.session_state.page
    if page == "home":
        page_home(settings)
    elif page == "license":
        page_license(settings)
    elif page == "broker":
        page_broker(settings)
    elif page == "control":
        page_control(settings)
    elif page == "monitor":
        page_monitor(settings)
    elif page == "admin":
        page_admin(settings)
    elif page == "ib":
        page_ib()

    st.divider()
    st.caption(f"ChronoScalp SaaS · {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}")


if __name__ == "__main__":
    main()
