#!/usr/bin/env python3
"""ChronoScalp monitoring dashboard (Streamlit) — bilingual EN/FA.

Usage:
    pip install streamlit
    streamlit run scripts/dashboard.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPTS))

import streamlit as st  # noqa: E402

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.orchestration.kill_switch import KillSwitch  # noqa: E402
from chronoscalp.orchestration.trade_journal import load_journal_snapshot  # noqa: E402
from dashboard_i18n import t  # noqa: E402
from dashboard_stats import render_trading_stats  # noqa: E402
from panel_theme import hero_html, panel_theme_css  # noqa: E402

Lang = str


def _init_lang() -> Lang:
    if "lang" not in st.session_state:
        st.session_state.lang = "fa"
    return st.session_state.lang


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_spread_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["timestamp", "spread_pips"])
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.sort_values("timestamp")


def _tail_log(log_dir: Path, lang: Lang, lines: int = 40) -> str:
    if not log_dir.exists():
        return t("no_logs", lang)
    logs = sorted(log_dir.glob("chronoscalp_*.log"), reverse=True)
    if not logs:
        return t("no_log_files", lang)
    text = logs[0].read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])


def _load_backtest_reports(report_dir: Path) -> list[dict]:
    if not report_dir.exists():
        return []
    reports = []
    for path in sorted(report_dir.glob("*.json"), reverse=True)[:5]:
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            data["_file"] = path.name
            reports.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return reports


def main() -> None:
    lang = _init_lang()
    st.set_page_config(
        page_title=t("page_title", lang),
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(panel_theme_css(rtl=(lang == "fa")), unsafe_allow_html=True)
    st.markdown(
        hero_html(
            title=t("title", lang),
            subtitle=t("caption", lang),
            badge="LIVE MONITOR" if lang == "en" else "مانیتور زنده",
        ),
        unsafe_allow_html=True,
    )

    settings = get_settings()
    state_dir = Path(settings.execution.get("state_dir", "data/state"))
    spread_dir = Path(settings.spread_filter.get("spread_history_dir", "data/spread_history"))
    report_dir = ROOT / "data" / "reports"
    log_dir = ROOT / "logs"
    reference_equity = float(settings.backtest.get("initial_balance", 10_000))

    with st.sidebar:
        if st.button(t("lang_btn", lang), use_container_width=True, key="lang_toggle"):
            st.session_state.lang = "en" if lang == "fa" else "fa"
            st.rerun()

        st.divider()
        st.header(t("sidebar_deploy", lang))
        broker = settings.execution.get("broker", "paper")
        data_src = settings.execution.get("data_source", "auto")
        st.write(f"**{t('broker', lang)}:** `{broker}`")
        st.write(f"**{t('data_source', lang)}:** `{data_src}`")
        oanda_env = settings.raw.get("oanda", {}).get("environment", "practice")
        if broker == "oanda" or data_src == "oanda":
            st.write(f"**{t('oanda_env', lang)}:** `{oanda_env}`")
        st.divider()
        state_mode = st.radio(t("state_file", lang), ["paper", "live"], horizontal=True)
        refresh_sec = st.slider(t("auto_refresh", lang), min_value=0, max_value=30, value=5, step=1)
        st.divider()
        st.markdown(f"**{t('risk_limits', lang)}**")
        st.write(f"{t('max_risk', lang)}: {settings.risk.get('max_risk_per_trade_pct')}%")
        st.write(f"{t('min_rr', lang)}: {settings.risk.get('min_reward_risk_ratio')}")
        st.write(f"{t('max_daily', lang)}: {settings.risk.get('max_daily_loss_pct')}%")
        st.divider()
        if st.button(t("refresh", lang), use_container_width=True):
            st.rerun()

    ks = KillSwitch(state_dir=state_dir, env_stop=settings.secrets.chronoscalp_stop_trading)
    kill_active = ks.is_active()
    live_confirmed = settings.secrets.live_trading_confirmed

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        t("kill_switch", lang),
        t("kill_active", lang) if kill_active else t("kill_off", lang),
        delta_color="inverse" if kill_active else "normal",
    )
    c2.metric(
        t("live_gate", lang),
        t("live_open", lang) if live_confirmed else t("live_closed", lang),
        help=t("live_gate_help", lang),
    )
    c3.metric(t("symbols", lang), len(settings.symbols))
    c4.metric(
        t("ml_gate", lang),
        t("ml_on", lang) if settings.ml.get("enabled") else t("ml_off", lang),
    )

    if kill_active:
        st.error(f"{t('trading_halted', lang)}: {ks.reason()}")

    run_every = timedelta(seconds=refresh_sec) if refresh_sec > 0 else None

    @st.fragment(run_every=run_every)
    def _live_trading_block() -> None:
        snapshot = load_journal_snapshot(state_dir, state_mode, reference_equity=reference_equity)
        render_trading_stats(snapshot, t=t, lang=lang)

    _live_trading_block()

    state_path = state_dir / f"trading_state_{state_mode}.json"
    state = _load_state(state_path)

    st.subheader(f"{t('trading_state', lang)} ({state_mode})")
    if state is None:
        st.info(t("no_state", lang, path=str(state_path), mode=state_mode))
    else:
        sc1, sc2, sc3 = st.columns(3)
        open_tickets = state.get("open_tickets") or {}
        sc1.metric(t("open_positions", lang), len(open_tickets))
        sc2.metric(t("dedup_keys", lang), len(state.get("processed_signals") or []))
        sc3.metric(t("last_saved", lang), state.get("updated_at") or "—")

        if open_tickets:
            st.dataframe(
                pd.DataFrame(
                    [
                        {t("col_symbol", lang): k, t("col_ticket", lang): v}
                        for k, v in open_tickets.items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write(t("no_open_positions", lang))

        with st.expander(t("raw_json", lang)):
            st.json(state)

    st.subheader(t("spread_section", lang))
    spread_tabs = st.tabs(settings.symbols)
    for tab, symbol in zip(spread_tabs, settings.symbols, strict=True):
        with tab:
            df = _load_spread_csv(spread_dir / f"{symbol}_spread.csv")
            if df.empty:
                st.write(t("no_spread", lang, symbol=symbol))
            else:
                max_cfg = settings.spread_filter.get("max_spread_pips", {}).get(symbol, "—")
                latest = float(df["spread_pips"].iloc[-1])
                st.metric(
                    t("spread_metric", lang, symbol=symbol),
                    f"{latest:.2f}",
                    f"{t('max_allowed', lang)}: {max_cfg}",
                )
                st.line_chart(df.set_index("timestamp")["spread_pips"], height=220)

    st.subheader(t("backtest_section", lang))
    reports = _load_backtest_reports(report_dir)
    if not reports:
        st.info(t("no_reports", lang))
    else:
        for rep in reports:
            summary = rep.get("summary") or rep
            with st.expander(f"{summary.get('symbol', '?')} — {rep.get('_file', '')}"):
                cols = st.columns(4)
                cols[0].write(f"**{t('trades', lang)}:** {summary.get('total_trades', '—')}")
                cols[1].write(f"**{t('win_rate', lang)}:** {summary.get('win_rate_pct', '—')}%")
                cols[2].write(
                    f"**{t('profit_factor', lang)}:** {summary.get('profit_factor', '—')}"
                )
                cols[3].write(f"**{t('return_pct', lang)}:** {summary.get('return_pct', '—')}%")
                st.json(summary)

    st.subheader(t("logs_section", lang))
    st.code(_tail_log(log_dir, lang), language="log")

    st.divider()
    st.caption(t("footer", lang, ts=datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")))


if __name__ == "__main__":
    main()
