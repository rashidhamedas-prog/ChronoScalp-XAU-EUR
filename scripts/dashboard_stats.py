"""Shared Streamlit widgets for live trading statistics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from chronoscalp.orchestration.trade_journal import JournalSnapshot, TradingStats


def render_trading_stats(
    snapshot: JournalSnapshot,
    *,
    t: Callable[..., str],
    lang: str,
) -> None:
    """Render live P&L / trade metrics, open table, and closed history."""
    stats = snapshot.stats
    st.subheader(t("live_stats_section", lang))
    st.caption(t("live_stats_caption", lang, mode=snapshot.mode))

    if stats.closed_trades == 0 and stats.open_trades == 0:
        st.info(t("no_live_trades", lang))
        return

    _metric_row_primary(stats, t, lang)
    _metric_row_secondary(stats, t, lang)
    _metric_row_streaks(stats, t, lang)

    st.markdown(f"**{t('open_trades_table', lang)}**")
    if snapshot.open_trades:
        open_df = pd.DataFrame([_open_row(r, t, lang) for r in snapshot.open_trades])
        st.dataframe(open_df, use_container_width=True, hide_index=True)
    else:
        st.write(t("no_open_positions", lang))

    st.markdown(f"**{t('closed_trades_table', lang)}**")
    if snapshot.closed_trades:
        closed_sorted = sorted(
            snapshot.closed_trades, key=lambda r: r.close_time or "", reverse=True
        )
        closed_df = pd.DataFrame([_closed_row(r, t, lang) for r in closed_sorted[:100]])
        st.dataframe(closed_df, use_container_width=True, hide_index=True)
        if len(closed_sorted) > 100:
            st.caption(t("showing_latest", lang, n=100, total=len(closed_sorted)))
    else:
        st.write(t("no_closed_trades", lang))


def _fmt_pf(value: float | None | str) -> str:
    if value is None:
        return "—"
    if value == "inf" or value == float("inf"):
        return "∞"
    return f"{float(value):.2f}"


def _metric_row_primary(stats: TradingStats, t: Callable[..., str], lang: str) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("stat_net_pnl", lang), f"{stats.net_pnl:+.2f}")
    c2.metric(t("stat_today_pnl", lang), f"{stats.today_pnl:+.2f}")
    c3.metric(t("stat_closed", lang), stats.closed_trades)
    c4.metric(t("stat_open", lang), stats.open_trades)
    c5.metric(t("stat_total", lang), stats.total_trades)


def _metric_row_secondary(stats: TradingStats, t: Callable[..., str], lang: str) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("stat_win_rate", lang), f"{stats.win_rate_pct:.1f}%")
    c2.metric(t("stat_avg_pnl", lang), f"{stats.avg_pnl:+.2f}")
    avg_ret = (
        f"{stats.avg_return_pct:+.3f}%" if stats.avg_return_pct else f"{stats.avg_r_multiple:+.2f}R"
    )
    c3.metric(t("stat_avg_return", lang), avg_ret)
    c4.metric(t("stat_profit_factor", lang), _fmt_pf(stats.profit_factor))
    c5.metric(t("stat_expectancy", lang), f"{stats.expectancy:+.2f}")


def _metric_row_streaks(stats: TradingStats, t: Callable[..., str], lang: str) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("stat_wins", lang), stats.wins)
    c2.metric(t("stat_losses", lang), stats.losses)
    c3.metric(t("stat_best", lang), f"{stats.best_trade:+.2f}")
    c4.metric(t("stat_worst", lang), f"{stats.worst_trade:+.2f}")
    c5.metric(
        t("stat_streaks", lang),
        f"W{stats.max_consecutive_wins}/L{stats.max_consecutive_losses}",
    )


def _open_row(rec: Any, t: Callable[..., str], lang: str) -> dict[str, Any]:
    return {
        t("col_ticket", lang): rec.ticket,
        t("col_symbol", lang): rec.symbol,
        t("col_direction", lang): rec.direction,
        t("col_volume", lang): rec.volume,
        t("col_entry", lang): rec.entry_price,
        t("col_sl", lang): rec.stop_loss,
        t("col_tp", lang): rec.take_profit,
        t("col_open_time", lang): rec.open_time,
    }


def _closed_row(rec: Any, t: Callable[..., str], lang: str) -> dict[str, Any]:
    return {
        t("col_ticket", lang): rec.ticket,
        t("col_symbol", lang): rec.symbol,
        t("col_direction", lang): rec.direction,
        t("col_volume", lang): rec.volume,
        t("col_entry", lang): rec.entry_price,
        t("col_exit", lang): rec.exit_price,
        t("col_pnl", lang): round(rec.pnl, 2),
        t("col_r", lang): rec.r_multiple,
        t("col_reason", lang): rec.exit_reason,
        t("col_close_time", lang): rec.close_time,
    }
