#!/usr/bin/env python3
"""Generate a Persian HTML performance report from a live trade journal.

Example:
  PYTHONPATH=src python scripts/generate_account_report_fa.py \\
    --journal /path/to/trade_journal_live.json \\
    --account-json /path/to/broker_positions_live.json \\
    --state /path/to/trading_state_live.json \\
    --login 55625500 \\
    --out reports/report_55625500.html
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from chronoscalp.utils.strategy_tags import resolve_strategy_tag

# LiteFinance / AUSCommercial broker clock is typically UTC+3.
BROKER_UTC_OFFSET = timedelta(hours=3)

STRATEGY_FA: dict[str, str] = {
    "ultra_scalp": "اولترا اسکالپ (S15)",
    "institutional": "نهادی / Institutional",
    "news_straddle": "استرادل خبری",
    "smc_confluence": "SMC / ساختار",
    "liquidity_volume": "نقدینگی + حجم",
    "unknown": "نامشخص / بدون تگ",
}

SYMBOL_FA: dict[str, str] = {
    "XAUUSD": "طلا (XAUUSD)",
    "EURUSD": "یورو/دلار",
    "USDJPY": "دلار/ین",
    "EURJPY": "یورو/ین",
    "BTCUSD": "بیت‌کوین",
    "ETHUSD": "اتریوم",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fa_num(value: float, digits: int = 2) -> str:
    """Format a number with Persian digits and separators."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    formatted = f"{value:,.{digits}f}"
    trans = str.maketrans("0123456789.-", "۰۱۲۳۴۵۶۷۸۹.-")
    return formatted.translate(trans)


def _fa_int(value: int) -> str:
    return _fa_num(float(value), 0).replace(".", "")


def _fa_pct(value: float) -> str:
    return _fa_num(value, 1) + "٪"


def _session_name(local_hour: int) -> str:
    if 11 <= local_hour < 14:
        return "لندن"
    if 16 <= local_hour < 20:
        return "نیویورک"
    if 0 <= local_hour < 8:
        return "آسیا / شب"
    return "سایر ساعات"


def _load_signals(state_path: Path | None) -> list[tuple[str, str, datetime, str]]:
    if state_path is None or not state_path.exists():
        return []
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    out: list[tuple[str, str, datetime, str]] = []
    for item in raw.get("processed_signals") or []:
        parts = str(item).split("|")
        if len(parts) < 4:
            continue
        ts = _parse_dt(parts[2])
        if ts is None:
            continue
        out.append((parts[0].replace("_o", ""), parts[1], ts, parts[3]))
    return out


def enrich_trades(
    closed: list[dict[str, Any]],
    signals: list[tuple[str, str, datetime, str]],
) -> tuple[list[dict[str, Any]], int]:
    """Normalize trades; drop negative-duration clock-skew rows."""
    rows: list[dict[str, Any]] = []
    dropped = 0
    for trade in closed:
        strategy = resolve_strategy_tag(
            explicit=trade.get("strategy"),
            reason=trade.get("reason"),
        )
        opened = _parse_dt(str(trade.get("open_time") or ""))
        closed_at = _parse_dt(str(trade.get("close_time") or ""))
        source = "journal"
        if strategy == "unknown" and opened is not None:
            symbol = str(trade.get("symbol") or "").replace("_o", "")
            candidates = [
                s
                for s in signals
                if s[0] == symbol and abs((s[2] - opened).total_seconds()) < 180
            ]
            if candidates:
                best = min(candidates, key=lambda s: abs((s[2] - opened).total_seconds()))
                if best[1] == "S15":
                    strategy = "ultra_scalp"
                    source = "signal_S15"
        if opened and closed_at and (closed_at - opened).total_seconds() < 0:
            dropped += 1
            continue
        local = opened + BROKER_UTC_OFFSET if opened else None
        pnl = float(trade.get("pnl") or 0.0)
        rows.append(
            {
                "ticket": int(trade.get("ticket") or 0),
                "symbol": str(trade.get("symbol") or "").replace("_o", ""),
                "direction": str(trade.get("direction") or ""),
                "volume": float(trade.get("volume") or 0.0),
                "pnl": pnl,
                "strategy": strategy,
                "strategy_source": source,
                "exit_reason": str(trade.get("exit_reason") or ""),
                "open_time": str(trade.get("open_time") or ""),
                "close_time": str(trade.get("close_time") or ""),
                "local_hour": local.hour if local else None,
                "local_date": local.date().isoformat() if local else None,
                "duration_s": (
                    (closed_at - opened).total_seconds()
                    if opened and closed_at
                    else None
                ),
                "win": pnl > 0,
                "loss": pnl < 0,
            }
        )
    return rows, dropped


def _group_stats(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row[key])].append(row)
    out: list[dict[str, Any]] = []
    for name, items in buckets.items():
        wins = sum(1 for r in items if r["win"])
        losses = sum(1 for r in items if r["loss"])
        pnl = sum(r["pnl"] for r in items)
        gp = sum(r["pnl"] for r in items if r["pnl"] > 0)
        gl = abs(sum(r["pnl"] for r in items if r["pnl"] < 0))
        out.append(
            {
                "key": name,
                "n": len(items),
                "wins": wins,
                "losses": losses,
                "win_rate": (100.0 * wins / len(items)) if items else 0.0,
                "pnl": pnl,
                "profit_factor": (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0),
            }
        )
    out.sort(key=lambda x: (-x["wins"], -x["win_rate"], -x["n"]))
    return out


def _hour_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hour0 in range(0, 24, 2):
        label = f"{hour0:02d}:00–{hour0 + 2:02d}:00"
        items = [
            r
            for r in rows
            if r["local_hour"] is not None and hour0 <= int(r["local_hour"]) < hour0 + 2
        ]
        if not items:
            continue
        wins = sum(1 for r in items if r["win"])
        out.append(
            {
                "label": label,
                "n": len(items),
                "wins": wins,
                "win_rate": 100.0 * wins / len(items),
                "pnl": sum(r["pnl"] for r in items),
            }
        )
    out.sort(key=lambda x: (-x["win_rate"], -x["pnl"]))
    return out


def build_summary(rows: list[dict[str, Any]], account: dict[str, Any]) -> dict[str, Any]:
    wins = [r for r in rows if r["win"]]
    losses = [r for r in rows if r["loss"]]
    gp = sum(r["pnl"] for r in wins)
    gl = abs(sum(r["pnl"] for r in losses))
    total_pnl = sum(r["pnl"] for r in rows)
    balance = float(account.get("balance") or 0.0)
    implied_start = balance - total_pnl

    streak = 0
    max_lose_streak = 0
    for row in sorted(rows, key=lambda r: r["open_time"]):
        if row["loss"]:
            streak += 1
            max_lose_streak = max(max_lose_streak, streak)
        else:
            streak = 0

    oversized = [r for r in rows if r["volume"] >= 10]
    small = [r for r in rows if r["volume"] < 10]
    crypto = [r for r in rows if r["symbol"] in {"BTCUSD", "ETHUSD"}]
    fx = [r for r in rows if r["symbol"] not in {"BTCUSD", "ETHUSD"}]

    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["local_hour"] is None:
            continue
        sessions[_session_name(int(row["local_hour"]))].append(row)

    session_stats = []
    for name, items in sessions.items():
        w = sum(1 for r in items if r["win"])
        session_stats.append(
            {
                "key": name,
                "n": len(items),
                "wins": w,
                "win_rate": 100.0 * w / len(items) if items else 0.0,
                "pnl": sum(r["pnl"] for r in items),
            }
        )
    session_stats.sort(key=lambda x: (-x["win_rate"], -x["pnl"]))

    by_day: dict[str, dict[str, float | int]] = {}
    for row in rows:
        day = row["local_date"] or "?"
        bucket = by_day.setdefault(day, {"n": 0, "pnl": 0.0, "wins": 0})
        bucket["n"] = int(bucket["n"]) + 1
        bucket["pnl"] = float(bucket["pnl"]) + row["pnl"]
        if row["win"]:
            bucket["wins"] = int(bucket["wins"]) + 1

    return {
        "n": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(rows) - len(wins) - len(losses),
        "win_rate": 100.0 * len(wins) / len(rows) if rows else 0.0,
        "total_pnl": total_pnl,
        "profit_factor": (gp / gl) if gl > 0 else 0.0,
        "avg_win": (gp / len(wins)) if wins else 0.0,
        "avg_loss": (gl / len(losses)) if losses else 0.0,
        "max_lose_streak": max_lose_streak,
        "balance": balance,
        "equity": float(account.get("equity") or balance),
        "implied_start": implied_start,
        "return_pct": (100.0 * total_pnl / implied_start) if implied_start else 0.0,
        "oversized_n": len(oversized),
        "oversized_pnl": sum(r["pnl"] for r in oversized),
        "small_n": len(small),
        "small_pnl": sum(r["pnl"] for r in small),
        "crypto_n": len(crypto),
        "crypto_wins": sum(1 for r in crypto if r["win"]),
        "crypto_pnl": sum(r["pnl"] for r in crypto),
        "fx_n": len(fx),
        "fx_wins": sum(1 for r in fx if r["win"]),
        "fx_pnl": sum(r["pnl"] for r in fx),
        "session_stats": session_stats,
        "by_day": dict(sorted(by_day.items())),
        "strategy_stats": _group_stats(rows, "strategy"),
        "symbol_stats": _group_stats(rows, "symbol"),
        "hour_buckets": _hour_buckets(rows),
    }


def render_html(
    *,
    login: str,
    server: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    period_from: str,
    period_to: str,
    dropped: int,
    generated_at: str,
) -> str:
    best_strategy = next(
        (s for s in summary["strategy_stats"] if s["n"] >= 5),
        summary["strategy_stats"][0] if summary["strategy_stats"] else None,
    )
    # Prefer highest win rate among strategies with enough samples.
    if summary["strategy_stats"]:
        best_strategy = max(
            [s for s in summary["strategy_stats"] if s["n"] >= 5] or summary["strategy_stats"],
            key=lambda s: (s["win_rate"], s["pnl"]),
        )
    best_symbol = next(
        (s for s in summary["symbol_stats"] if s["wins"] > 0),
        summary["symbol_stats"][0] if summary["symbol_stats"] else None,
    )
    best_window = next(
        (h for h in summary["hour_buckets"] if h["n"] >= 5),
        summary["hour_buckets"][0] if summary["hour_buckets"] else None,
    )
    best_session = summary["session_stats"][0] if summary["session_stats"] else None

    strategy_rows_html = "".join(
        f"""<tr>
          <td>{STRATEGY_FA.get(s['key'], s['key'])}</td>
          <td>{_fa_int(s['n'])}</td>
          <td>{_fa_int(s['wins'])}</td>
          <td>{_fa_int(s['losses'])}</td>
          <td>{_fa_pct(s['win_rate'])}</td>
          <td class="{'pos' if s['pnl']>=0 else 'neg'}">{_fa_num(s['pnl'])}</td>
          <td>{_fa_num(s['profit_factor'] if math.isfinite(s['profit_factor']) else 0.0)}</td>
        </tr>"""
        for s in summary["strategy_stats"]
    )

    symbol_rows_html = "".join(
        f"""<tr>
          <td>{SYMBOL_FA.get(s['key'], s['key'])}</td>
          <td><code>{s['key']}</code></td>
          <td>{_fa_int(s['n'])}</td>
          <td>{_fa_int(s['wins'])}</td>
          <td>{_fa_pct(s['win_rate'])}</td>
          <td class="{'pos' if s['pnl']>=0 else 'neg'}">{_fa_num(s['pnl'])}</td>
        </tr>"""
        for s in summary["symbol_stats"]
    )

    hour_rows_html = "".join(
        f"""<tr>
          <td>{h['label'].translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))}</td>
          <td>{_fa_int(h['n'])}</td>
          <td>{_fa_int(h['wins'])}</td>
          <td>{_fa_pct(h['win_rate'])}</td>
          <td class="{'pos' if h['pnl']>=0 else 'neg'}">{_fa_num(h['pnl'])}</td>
        </tr>"""
        for h in summary["hour_buckets"]
    )

    session_rows_html = "".join(
        f"""<tr>
          <td>{s['key']}</td>
          <td>{_fa_int(s['n'])}</td>
          <td>{_fa_int(s['wins'])}</td>
          <td>{_fa_pct(s['win_rate'])}</td>
          <td class="{'pos' if s['pnl']>=0 else 'neg'}">{_fa_num(s['pnl'])}</td>
        </tr>"""
        for s in summary["session_stats"]
    )

    day_rows_html = "".join(
        f"""<tr>
          <td>{day.translate(str.maketrans('0123456789-', '۰۱۲۳۴۵۶۷۸۹-'))}</td>
          <td>{_fa_int(int(vals['n']))}</td>
          <td>{_fa_int(int(vals['wins']))}</td>
          <td class="{'pos' if float(vals['pnl'])>=0 else 'neg'}">{_fa_num(float(vals['pnl']))}</td>
        </tr>"""
        for day, vals in summary["by_day"].items()
    )

    chart_payload = {
        "strategies": {
            "labels": [STRATEGY_FA.get(s["key"], s["key"]) for s in summary["strategy_stats"]],
            "counts": [s["n"] for s in summary["strategy_stats"]],
            "win_rates": [round(s["win_rate"], 1) for s in summary["strategy_stats"]],
            "pnl": [round(s["pnl"], 2) for s in summary["strategy_stats"]],
        },
        "symbols": {
            "labels": [s["key"] for s in summary["symbol_stats"]],
            "wins": [s["wins"] for s in summary["symbol_stats"]],
            "pnl": [round(s["pnl"], 2) for s in summary["symbol_stats"]],
        },
        "hours": {
            "labels": [h["label"] for h in sorted(summary["hour_buckets"], key=lambda x: x["label"])],
            "win_rates": [
                round(h["win_rate"], 1)
                for h in sorted(summary["hour_buckets"], key=lambda x: x["label"])
            ],
            "pnl": [
                round(h["pnl"], 2)
                for h in sorted(summary["hour_buckets"], key=lambda x: x["label"])
            ],
        },
        "days": {
            "labels": list(summary["by_day"].keys()),
            "pnl": [round(float(v["pnl"]), 2) for v in summary["by_day"].values()],
        },
    }

    verdict_class = "bad" if summary["total_pnl"] < 0 else "good"
    best_strat_fa = (
        STRATEGY_FA.get(best_strategy["key"], best_strategy["key"]) if best_strategy else "—"
    )
    best_sym_fa = (
        SYMBOL_FA.get(best_symbol["key"], best_symbol["key"]) if best_symbol else "—"
    )
    best_win_window = best_window["label"] if best_window else "—"
    if best_window:
        best_win_window = best_win_window.translate(
            str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
        )

    strategy_answer = (
        "<br/>".join(
            f"• {STRATEGY_FA.get(s['key'], s['key'])}: <strong>{_fa_int(s['n'])}</strong> معامله"
            for s in summary["strategy_stats"]
        )
        or "—"
    )
    best_strategy_answer = (
        (
            f"<strong>{best_strat_fa}</strong> با نرخ موفقیت "
            f"<strong>{_fa_pct(best_strategy['win_rate'])}</strong> از "
            f"{_fa_int(best_strategy['n'])} معامله."
        )
        if best_strategy
        else "—"
    )
    best_window_cls = (
        "pos" if best_window and best_window["pnl"] >= 0 else "neg"
    )
    best_window_answer = (
        (
            f"بهترین بازهٔ ۲ساعته (زمان بروکر UTC+۳): <strong>{best_win_window}</strong> "
            f"با {_fa_pct(best_window['win_rate'])} موفقیت و PnL "
            f"<span class='{best_window_cls}'>{_fa_num(best_window['pnl'])}</span>."
        )
        if best_window
        else "—"
    )
    best_session_answer = (
        (
            f"بهترین سشن معاملاتی: <strong>{best_session['key']}</strong> "
            f"({_fa_pct(best_session['win_rate'])}، PnL {_fa_num(best_session['pnl'])})."
        )
        if best_session
        else ""
    )
    best_symbol_answer = (
        (
            f"<strong>{best_sym_fa}</strong> با <strong>{_fa_int(best_symbol['wins'])}</strong> "
            f"معاملهٔ برنده از {_fa_int(best_symbol['n'])} معامله "
            f"({_fa_pct(best_symbol['win_rate'])})."
        )
        if best_symbol
        else "—"
    )
    asia_pnl = next(
        (s["pnl"] for s in summary["session_stats"] if s["key"] == "آسیا / شب"),
        0.0,
    )
    period_from_fa = period_from[:10].translate(
        str.maketrans("0123456789-", "۰۱۲۳۴۵۶۷۸۹-")
    )
    period_to_fa = period_to[:10].translate(
        str.maketrans("0123456789-", "۰۱۲۳۴۵۶۷۸۹-")
    )
    generated_fa = (
        generated_at[:19]
        .replace("T", " ")
        .translate(str.maketrans("0123456789-:", "۰۱۲۳۴۵۶۷۸۹-:"))
    )
    return_word = "کاهش" if summary["return_pct"] < 0 else "رشد"
    verdict_label = "ضعیف / زیان‌ده" if summary["total_pnl"] < 0 else "مثبت"
    small_cls = "pos" if summary["small_pnl"] >= 0 else "neg"
    chart_json = json.dumps(chart_payload, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>گزارش عملکرد ChronoScalp — حساب {_fa_int(int(login))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg: #0f1419;
  --panel: #1a222d;
  --panel-2: #243041;
  --text: #e8eef6;
  --muted: #9aadc2;
  --accent: #3d9cf0;
  --good: #3ecf8e;
  --bad: #f07178;
  --warn: #e6c07b;
  --line: rgba(255,255,255,.08);
  --shadow: 0 12px 40px rgba(0,0,0,.35);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Vazirmatn", Tahoma, sans-serif;
  background:
    radial-gradient(1200px 600px at 100% -10%, rgba(61,156,240,.18), transparent 55%),
    radial-gradient(900px 500px at -10% 20%, rgba(62,207,142,.10), transparent 50%),
    var(--bg);
  color: var(--text);
  line-height: 1.75;
}}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 28px 18px 64px; }}
header.hero {{
  background: linear-gradient(135deg, #1d2a3a 0%, #15202b 55%, #101820 100%);
  border: 1px solid var(--line);
  border-radius: 22px;
  padding: 28px 28px 22px;
  box-shadow: var(--shadow);
  margin-bottom: 22px;
}}
header.hero h1 {{
  margin: 0 0 8px;
  font-size: clamp(1.45rem, 2.4vw, 2rem);
  font-weight: 800;
}}
header.hero .sub {{ color: var(--muted); margin: 0 0 18px; }}
.meta {{
  display: flex; flex-wrap: wrap; gap: 10px;
}}
.chip {{
  background: rgba(255,255,255,.06);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: .92rem;
  color: var(--muted);
}}
.chip strong {{ color: var(--text); font-weight: 700; }}
.grid {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 18px 0 8px;
}}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 520px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.kpi {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px 16px;
}}
.kpi .label {{ color: var(--muted); font-size: .86rem; margin-bottom: 4px; }}
.kpi .value {{ font-size: 1.35rem; font-weight: 800; }}
.kpi .value.pos, .pos {{ color: var(--good); }}
.kpi .value.neg, .neg {{ color: var(--bad); }}
.kpi .value.warn {{ color: var(--warn); }}
section.card {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 20px 22px;
  margin-top: 16px;
  box-shadow: var(--shadow);
}}
section.card h2 {{
  margin: 0 0 6px;
  font-size: 1.2rem;
  font-weight: 750;
}}
section.card p.lead {{
  margin: 0 0 14px;
  color: var(--muted);
}}
.answers {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}}
@media (max-width: 800px) {{ .answers {{ grid-template-columns: 1fr; }} }}
.answer {{
  background: var(--panel-2);
  border-radius: 14px;
  padding: 14px 16px;
  border: 1px solid var(--line);
}}
.answer h3 {{ margin: 0 0 6px; font-size: 1rem; color: var(--accent); }}
.answer p {{ margin: 0; }}
.charts {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}}
@media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
.chart-box {{
  background: var(--panel-2);
  border-radius: 14px;
  padding: 12px;
  border: 1px solid var(--line);
  min-height: 280px;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: .95rem;
}}
th, td {{
  padding: 10px 8px;
  border-bottom: 1px solid var(--line);
  text-align: right;
}}
th {{ color: var(--muted); font-weight: 600; }}
tr:hover td {{ background: rgba(255,255,255,.02); }}
ul.fix {{
  margin: 8px 0 0;
  padding: 0 18px 0 0;
}}
ul.fix li {{ margin: 8px 0; }}
.badge {{
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: .85rem;
  font-weight: 700;
}}
.badge.bad {{ background: rgba(240,113,120,.15); color: var(--bad); }}
.badge.good {{ background: rgba(62,207,142,.15); color: var(--good); }}
.badge.warn {{ background: rgba(230,192,123,.15); color: var(--warn); }}
footer {{
  margin-top: 28px;
  color: var(--muted);
  font-size: .85rem;
  text-align: center;
}}
code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .9em;
  color: #c6d6e8;
}}
.callout {{
  background: rgba(230,192,123,.08);
  border: 1px solid rgba(230,192,123,.25);
  border-radius: 12px;
  padding: 12px 14px;
  color: #f0e2c0;
  margin-top: 12px;
}}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <h1>گزارش عملکرد ربات ChronoScalp</h1>
    <p class="sub">از زمان تغییر بروکر و ورود با حساب دمو — تحلیل ژورنال لایو روی VPS</p>
    <div class="meta">
      <span class="chip">لاگین: <strong>{_fa_int(int(login))}</strong></span>
      <span class="chip">سرور: <strong>{server}</strong></span>
      <span class="chip">بازه: <strong>{period_from_fa} تا {period_to_fa}</strong></span>
      <span class="chip">حالت: <strong>لایو (live)</strong></span>
      <span class="chip">تولید گزارش: <strong>{generated_fa} UTC</strong></span>
    </div>
    <div class="grid" style="margin-top:20px">
      <div class="kpi"><div class="label">تعداد معاملات بسته‌شده</div><div class="value">{_fa_int(summary['n'])}</div></div>
      <div class="kpi"><div class="label">نرخ موفقیت</div><div class="value {'pos' if summary['win_rate']>=50 else 'neg'}">{_fa_pct(summary['win_rate'])}</div></div>
      <div class="kpi"><div class="label">سود/زیان خالص</div><div class="value {'pos' if summary['total_pnl']>=0 else 'neg'}">{_fa_num(summary['total_pnl'])}</div></div>
      <div class="kpi"><div class="label">موجودی فعلی</div><div class="value">{_fa_num(summary['balance'])}</div></div>
      <div class="kpi"><div class="label">ضریب سود (PF)</div><div class="value {'pos' if summary['profit_factor']>=1 else 'neg'}">{_fa_num(summary['profit_factor'])}</div></div>
      <div class="kpi"><div class="label">بازگشت تقریبی</div><div class="value {'pos' if summary['return_pct']>=0 else 'neg'}">{_fa_pct(summary['return_pct'])}</div></div>
      <div class="kpi"><div class="label">میانگین سود</div><div class="value pos">{_fa_num(summary['avg_win'])}</div></div>
      <div class="kpi"><div class="label">میانگین ضرر</div><div class="value neg">{_fa_num(summary['avg_loss'])}</div></div>
    </div>
  </header>

  <section class="card">
    <h2>پاسخ مستقیم به سؤالات شما</h2>
    <p class="lead">خلاصهٔ یافته‌ها بر اساس ژورنال لایو حساب {_fa_int(int(login))}.</p>
    <div class="answers">
      <div class="answer">
        <h3>۱) با هر استراتژی چند معامله باز شده؟</h3>
        <p>{strategy_answer}</p>
        <p style="margin-top:8px;color:var(--muted);font-size:.9rem">توجه: بخشی از معاملات قدیمی بدون تگ استراتژی بودند؛ با تطبیق سیگنال S15 به اولترا اسکالپ نسبت داده شدند.</p>
      </div>
      <div class="answer">
        <h3>۲) درصد موفقیت کدام استراتژی بیشتر بوده؟</h3>
        <p>{best_strategy_answer}</p>
      </div>
      <div class="answer">
        <h3>۳) بهترین تایم معامله‌های برنده؟</h3>
        <p>{best_window_answer}</p>
        <p style="margin-top:8px">{best_session_answer}</p>
      </div>
      <div class="answer">
        <h3>۴) بیشترین معامله‌های برنده مال کدام نماد؟</h3>
        <p>{best_symbol_answer}</p>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>عملکرد کلی ربات</h2>
    <p class="lead">
      وضعیت کلی:
      <span class="badge {verdict_class}">{verdict_label}</span>
      — از سرمایهٔ تقریبی {_fa_num(summary['implied_start'])} به {_fa_num(summary['balance'])} رسیده
      (حدود {_fa_pct(abs(summary['return_pct']))} {return_word}).
    </p>
    <ul class="fix">
      <li>از {_fa_int(summary['n'])} معاملهٔ معتبر، {_fa_int(summary['wins'])} برنده و {_fa_int(summary['losses'])} بازنده ثبت شده است.</li>
      <li>میانگین سود برنده ({_fa_num(summary['avg_win'])}) از میانگین ضرر ({_fa_num(summary['avg_loss'])}) بزرگ‌تر است، اما به‌خاطر تعداد زیاد بازنده‌ها و حجم‌های خیلی بزرگ، خالص منفی شده.</li>
      <li>بیشینهٔ باخت‌های پشت‌سرهم: <strong>{_fa_int(summary['max_lose_streak'])}</strong> معامله.</li>
      <li>معاملات با حجم ≥ ۱۰ لات: {_fa_int(summary['oversized_n'])} عدد با PnL <span class="neg">{_fa_num(summary['oversized_pnl'])}</span> — در مقابل حجم‌های کوچک‌تر با PnL <span class="{small_cls}">{_fa_num(summary['small_pnl'])}</span>.</li>
      <li>کریپتو (BTC/ETH): {_fa_int(summary['crypto_n'])} معامله، {_fa_int(summary['crypto_wins'])} برنده، PnL <span class="neg">{_fa_num(summary['crypto_pnl'])}</span>.</li>
      <li>{_fa_int(dropped)} ردیف به‌خاطر زمان بسته شدن قبل از باز شدن (ناسازگاری ساعت) از آمار حذف شد.</li>
    </ul>
    <div class="callout">
      نکتهٔ داده: تقریباً همهٔ خروج‌ها در ژورنال به‌صورت <code>external</code> ثبت شده و قیمت ورود/خروج یکسان ذخیره شده؛
      مبلغ PnL از بروکر آمده و برای این گزارش قابل اتکاست، اما R-multiple و قیمت خروج برای تحلیل دقیق‌تر نیاز به بهبود ثبت ژورنال دارد.
    </div>
  </section>

  <section class="card">
    <h2>نمودارها</h2>
    <div class="charts">
      <div class="chart-box"><canvas id="chartStrategyCount"></canvas></div>
      <div class="chart-box"><canvas id="chartStrategyWR"></canvas></div>
      <div class="chart-box"><canvas id="chartSymbolWins"></canvas></div>
      <div class="chart-box"><canvas id="chartHours"></canvas></div>
      <div class="chart-box" style="grid-column:1/-1"><canvas id="chartDaily"></canvas></div>
    </div>
  </section>

  <section class="card">
    <h2>جدول استراتژی‌ها</h2>
    <table>
      <thead><tr><th>استراتژی</th><th>تعداد</th><th>برنده</th><th>بازنده</th><th>موفقیت</th><th>PnL</th><th>PF</th></tr></thead>
      <tbody>{strategy_rows_html}</tbody>
    </table>
  </section>

  <section class="card">
    <h2>جدول نمادها</h2>
    <table>
      <thead><tr><th>نماد</th><th>کد</th><th>تعداد</th><th>برنده</th><th>موفقیت</th><th>PnL</th></tr></thead>
      <tbody>{symbol_rows_html}</tbody>
    </table>
  </section>

  <section class="card">
    <h2>بازهٔ زمانی (ساعت بروکر UTC+۳)</h2>
    <table>
      <thead><tr><th>بازه</th><th>تعداد</th><th>برنده</th><th>موفقیت</th><th>PnL</th></tr></thead>
      <tbody>{hour_rows_html}</tbody>
    </table>
    <h2 style="margin-top:22px">سشن معاملاتی</h2>
    <table>
      <thead><tr><th>سشن</th><th>تعداد</th><th>برنده</th><th>موفقیت</th><th>PnL</th></tr></thead>
      <tbody>{session_rows_html}</tbody>
    </table>
  </section>

  <section class="card">
    <h2>عملکرد روزانه</h2>
    <table>
      <thead><tr><th>تاریخ (بروکر)</th><th>معاملات</th><th>برنده</th><th>PnL</th></tr></thead>
      <tbody>{day_rows_html}</tbody>
    </table>
  </section>

  <section class="card">
    <h2>نقص‌ها و پیشنهاد برای عملکرد بهتر</h2>
    <p class="lead">این‌ها بر اساس دادهٔ واقعی همین حساب اولویت‌بندی شده‌اند — بدون شل کردن سقف ریسک ۱٪ یا کف R:R.</p>
    <ul class="fix">
      <li><strong>حجم‌های غیرعادی بزرگ (مهم‌ترین نقص):</strong> ده‌ها معامله با حجم ۱۰ تا ۵۰ لات روی EURUSD/USDJPY/XAUUSD ثبت شده و بخش عمدهٔ زیان از همین‌هاست.
      حجم‌های زیر ۱۰ لات در همین دوره در مجموع مثبت بوده‌اند. باید سقف لات سخت‌گیرانه، چک <code>volume_max</code> و صحت <code>pip_value_per_lot</code>/مارجین قبل از <code>order_send</code> اعمال شود.</li>
      <li><strong>کریپتو (BTCUSD/ETHUSD) فعلاً صفر برنده:</strong> کارمزد/اسپرد اولترا اسکالپ روی این نمادها را می‌بلعد. پیشنهاد: تا اصلاح هندسهٔ اقتصادی، کریپتو را خاموش کنید یا فقط در سشن نقدشوندگی بالا با فیلتر اسپرد/کمیسیون سخت‌تر معامله شود.</li>
      <li><strong>معامله در آسیا/شب زیان‌ده است:</strong> سشن آسیا حدود {_fa_num(asia_pnl)} ضرر داشته. حالت <code>london_ny</code> به‌جای <code>always_on_24h</code> برای فارکس/طلا منطقی‌تر است.</li>
      <li><strong>بازه ۱۴:۰۰–۱۶:۰۰ (بروکر) ضعیف است:</strong> نرخ موفقیت بسیار پایین؛ بهتر است در پنل/تلگرام برای این پنجره فیلتر زمانی یا کاهش ریسک اعمال شود.</li>
      <li><strong>USDJPY بدترین نماد از نظر PnL:</strong> با وجود تعداد کمتر، زیان سنگین داشته. موقتاً حذف از لیست نمادها یا کاهش ریسک جداگانه توصیه می‌شود.</li>
      <li><strong>ثبت استراتژی و قیمت خروج ناقص است:</strong> ۱۴۶ معامله ابتدا <code>unknown</code> بودند و تقریباً همهٔ خروج‌ها <code>external</code> با قیمت ورود=خروج. باید تگ استراتژی هنگام <code>record_open</code> اجباری شود و در reconcile قیمت/دلیل واقعی از deal history بروکر نوشته شود — وگرنه گزارش‌گیری و بهینه‌سازی گمراه‌کننده می‌ماند.</li>
      <li><strong>استریک باخت بلند:</strong> {_fa_int(summary['max_lose_streak'])} باخت پشت‌سرهم نشان می‌دهد circuit breaker / daily loss / سه-ضربه باید زودتر فعال شود یا حساسیت‌شان برای اولترا اسکالپ جدا تنظیم شود.</li>
      <li><strong>XAUUSD نسبتاً امیدوارکننده است:</strong> بیشترین تعداد برد و تنها نماد با PnL مثبت معنادار در این نمونه؛ تمرکز روی طلا + سشن لندن منطقی‌ترین مسیر بهبود کوتاه‌مدت است.</li>
    </ul>
  </section>

  <footer>
    منبع داده: <code>trade_journal_live.json</code> روی VPS —
    حساب {_fa_int(int(login))} / {server}.
    این گزارش برای تصمیم‌گیری عملیاتی است و تضمین سود آینده نیست.
  </footer>
</div>
<script>
const DATA = {chart_json};
const gridColor = 'rgba(255,255,255,0.08)';
const textColor = '#9aadc2';
Chart.defaults.color = textColor;
Chart.defaults.font.family = 'Vazirmatn, Tahoma, sans-serif';
Chart.defaults.borderColor = gridColor;

new Chart(document.getElementById('chartStrategyCount'), {{
  type: 'bar',
  data: {{
    labels: DATA.strategies.labels,
    datasets: [{{
      label: 'تعداد معاملات',
      data: DATA.strategies.counts,
      backgroundColor: '#3d9cf0'
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'تعداد معامله به تفکیک استراتژی', color: '#e8eef6' }} }},
    scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }} }}
  }}
}});

new Chart(document.getElementById('chartStrategyWR'), {{
  type: 'bar',
  data: {{
    labels: DATA.strategies.labels,
    datasets: [{{
      label: 'نرخ موفقیت ٪',
      data: DATA.strategies.win_rates,
      backgroundColor: '#3ecf8e'
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'نرخ موفقیت استراتژی‌ها', color: '#e8eef6' }} }},
    scales: {{ y: {{ beginAtZero: true, max: 100 }} }}
  }}
}});

new Chart(document.getElementById('chartSymbolWins'), {{
  type: 'bar',
  data: {{
    labels: DATA.symbols.labels,
    datasets: [
      {{ label: 'تعداد برد', data: DATA.symbols.wins, backgroundColor: '#3ecf8e' }},
      {{ label: 'PnL', data: DATA.symbols.pnl, backgroundColor: '#e6c07b', yAxisID: 'y1' }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'برد و PnL به تفکیک نماد', color: '#e8eef6' }} }},
    scales: {{
      y: {{ beginAtZero: true, position: 'right', ticks: {{ precision: 0 }} }},
      y1: {{ beginAtZero: false, position: 'left', grid: {{ drawOnChartArea: false }} }}
    }}
  }}
}});

new Chart(document.getElementById('chartHours'), {{
  type: 'line',
  data: {{
    labels: DATA.hours.labels,
    datasets: [{{
      label: 'نرخ موفقیت ٪',
      data: DATA.hours.win_rates,
      borderColor: '#3d9cf0',
      backgroundColor: 'rgba(61,156,240,.2)',
      fill: true,
      tension: .3
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'نرخ موفقیت در بازه‌های ۲ساعته (UTC+۳)', color: '#e8eef6' }} }},
    scales: {{ y: {{ beginAtZero: true, max: 100 }} }}
  }}
}});

new Chart(document.getElementById('chartDaily'), {{
  type: 'bar',
  data: {{
    labels: DATA.days.labels,
    datasets: [{{
      label: 'PnL روزانه',
      data: DATA.days.pnl,
      backgroundColor: DATA.days.pnl.map(v => v >= 0 ? '#3ecf8e' : '#f07178')
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ title: {{ display: true, text: 'سود و زیان روزانه', color: '#e8eef6' }} }}
  }}
}});
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--account-json", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--login", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    journal = json.loads(args.journal.read_text(encoding="utf-8"))
    closed = list(journal.get("closed_trades") or [])
    account: dict[str, Any] = {}
    if args.account_json and args.account_json.exists():
        payload = json.loads(args.account_json.read_text(encoding="utf-8"))
        account = dict(payload.get("account") or {})
    login = str(args.login or account.get("login") or "unknown")
    server = str(account.get("server") or "—")

    signals = _load_signals(args.state)
    rows, dropped = enrich_trades(closed, signals)
    if not rows:
        raise SystemExit("No valid closed trades found in journal.")

    summary = build_summary(rows, account)
    period_from = min(r["open_time"] for r in rows if r["open_time"])
    period_to = max(r["close_time"] for r in rows if r["close_time"])
    generated_at = datetime.now(tz=UTC).isoformat()

    html = render_html(
        login=login,
        server=server,
        rows=rows,
        summary=summary,
        period_from=period_from,
        period_to=period_to,
        dropped=dropped,
        generated_at=generated_at,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote {args.out} ({len(rows)} trades, dropped={dropped})")


if __name__ == "__main__":
    main()
