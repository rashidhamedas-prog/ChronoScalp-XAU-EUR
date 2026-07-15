#!/usr/bin/env python3
"""ChronoScalp monitoring dashboard (Streamlit).

Reads local state, spread history, backtest reports, and logs — no broker
connection required. Works on Windows/Linux (ideal alongside VPS paper mode).

Usage:
    pip install streamlit
    streamlit run scripts/dashboard.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.orchestration.kill_switch import KillSwitch, STOP_FILE_NAME  # noqa: E402

st.set_page_config(
    page_title="ChronoScalp Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


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


def _tail_log(log_dir: Path, lines: int = 40) -> str:
    if not log_dir.exists():
        return "(no logs yet — start run_live.py to generate logs)"
    logs = sorted(log_dir.glob("chronoscalp_*.log"), reverse=True)
    if not logs:
        return "(no log files found)"
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
    settings = get_settings()
    state_dir = Path(settings.execution.get("state_dir", "data/state"))
    spread_dir = Path(settings.spread_filter.get("spread_history_dir", "data/spread_history"))
    report_dir = ROOT / "data" / "reports"
    log_dir = ROOT / "logs"

    st.title("ChronoScalp Dashboard")
    st.caption("Local monitoring — state, spreads, backtests, logs (no live broker required to view)")

    # --- Sidebar ---
    with st.sidebar:
        st.header("Deployment")
        broker = settings.execution.get("broker", "paper")
        data_src = settings.execution.get("data_source", "auto")
        st.write(f"**Broker:** `{broker}`")
        st.write(f"**Data source:** `{data_src}`")
        oanda_env = settings.raw.get("oanda", {}).get("environment", "practice")
        if broker == "oanda" or data_src == "oanda":
            st.write(f"**OANDA env:** `{oanda_env}`")
        st.divider()
        state_mode = st.radio("State file", ["paper", "live"], horizontal=True)
        st.divider()
        st.markdown("**Risk (hard limits)**")
        st.write(f"Max risk/trade: {settings.risk.get('max_risk_per_trade_pct')}%")
        st.write(f"Min R:R: {settings.risk.get('min_reward_risk_ratio')}")
        st.write(f"Max daily loss: {settings.risk.get('max_daily_loss_pct')}%")
        st.divider()
        if st.button("Refresh"):
            st.rerun()

    # --- Kill switch & safety ---
    ks = KillSwitch(state_dir=state_dir, env_stop=settings.secrets.chronoscalp_stop_trading)
    kill_active = ks.is_active()
    live_confirmed = settings.secrets.live_trading_confirmed

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Kill switch", "ACTIVE" if kill_active else "Off", delta_color="inverse" if kill_active else "normal")
    c2.metric("Live gate", "OPEN" if live_confirmed else "Closed", help="CHRONOSCALP_CONFIRM_LIVE=yes")
    c3.metric("Symbols", len(settings.symbols))
    c4.metric("ML gate", "On" if settings.ml.get("enabled") else "Off")

    if kill_active:
        st.error(f"Trading halted: {ks.reason()}")

    # --- Trading state ---
    state_path = state_dir / f"trading_state_{state_mode}.json"
    state = _load_state(state_path)

    st.subheader(f"Trading state ({state_mode})")
    if state is None:
        st.info(f"No state at `{state_path}` — bot has not run in {state_mode} mode yet.")
    else:
        sc1, sc2, sc3 = st.columns(3)
        open_tickets = state.get("open_tickets") or {}
        sc1.metric("Open positions", len(open_tickets))
        sc2.metric("Dedup keys", len(state.get("processed_signals") or []))
        sc3.metric("Last saved", state.get("updated_at") or "—")

        if open_tickets:
            st.dataframe(
                pd.DataFrame(
                    [{"symbol": k, "ticket": v} for k, v in open_tickets.items()]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("No open positions in state.")

        with st.expander("Raw state JSON"):
            st.json(state)

    # --- Spread history ---
    st.subheader("Live spread sampling")
    spread_tabs = st.tabs(settings.symbols)
    for tab, symbol in zip(spread_tabs, settings.symbols, strict=True):
        with tab:
            df = _load_spread_csv(spread_dir / f"{symbol}_spread.csv")
            if df.empty:
                st.write(f"No spread samples for {symbol}. Enable `spread_filter.sample_live_spread` and run the bot.")
            else:
                max_cfg = settings.spread_filter.get("max_spread_pips", {}).get(symbol, "—")
                latest = float(df["spread_pips"].iloc[-1])
                st.metric(f"{symbol} spread (pips)", f"{latest:.2f}", f"max allowed: {max_cfg}")
                st.line_chart(df.set_index("timestamp")["spread_pips"], height=220)

    # --- Backtest reports ---
    st.subheader("Backtest reports")
    reports = _load_backtest_reports(report_dir)
    if not reports:
        st.info(
            "No reports in `data/reports/`. Run: "
            "`python scripts/run_backtest.py --symbol XAUUSD --report data/reports/xauusd.json`"
        )
    else:
        for rep in reports:
            summary = rep.get("summary") or rep
            with st.expander(f"{summary.get('symbol', '?')} — {rep.get('_file', '')}"):
                cols = st.columns(4)
                cols[0].write(f"**Trades:** {summary.get('total_trades', '—')}")
                cols[1].write(f"**Win rate:** {summary.get('win_rate_pct', '—')}%")
                cols[2].write(f"**Profit factor:** {summary.get('profit_factor', '—')}")
                cols[3].write(f"**Return:** {summary.get('return_pct', '—')}%")
                st.json(summary)

    # --- Logs ---
    st.subheader("Recent logs")
    st.code(_tail_log(log_dir), language="log")

    st.divider()
    st.caption(
        f"ChronoScalp · {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')} · "
        "See docs/DEPLOY_NL_VPS.md for Netherlands VPS setup"
    )


if __name__ == "__main__":
    main()
