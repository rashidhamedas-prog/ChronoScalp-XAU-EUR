"""Build Persian HTML performance reports from the trade journal."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chronoscalp.orchestration.trade_journal import (
    ClosedTradeRecord,
    TradeJournal,
    compute_strategy_stats,
    compute_trading_stats,
    journal_path_for,
)
from chronoscalp.utils.strategy_tags import STRATEGY_REPORT_ORDER

STRATEGY_FA: dict[str, str] = {
    "ultra_scalp": "اسکالپ فوق‌سریع (S15)",
    "institutional": "ورود نهادی",
    "news_straddle": "استرادل خبری",
    "smc_confluence": "همگرایی SMC",
    "liquidity_volume": "نقدینگی / حجم",
    "unknown": "نامشخص",
}

SESSION_LABELS_FA: dict[str, str] = {
    "london": "لندن (۰۸:۰۰–۱۱:۰۰ GMT)",
    "new_york": "نیویورک (۱۳:۳۰–۱۶:۳۰ GMT)",
    "asia": "آسیا (۰۰:۰۰–۰۸:۰۰ GMT)",
    "overlap": "هم‌پوشانی لندن–نیویورک",
    "off_hours": "خارج از سشن‌های اصلی",
}

HOUR_LABELS_FA: list[str] = [
    "۰۰",
    "۰۱",
    "۰۲",
    "۰۳",
    "۰۴",
    "۰۵",
    "۰۶",
    "۰۷",
    "۰۸",
    "۰۹",
    "۱۰",
    "۱۱",
    "۱۲",
    "۱۳",
    "۱۴",
    "۱۵",
    "۱۶",
    "۱۷",
    "۱۸",
    "۱۹",
    "۲۰",
    "۲۱",
    "۲۲",
    "۲۳",
]


def _fa_digits(value: str | float | int) -> str:
    """Convert Western digits to Persian for display."""
    text = f"{value}"
    return text.translate(str.maketrans("0123456789.%+-", "۰۱۲۳۴۵۶۷۸۹.٪+-"))


def strategy_label_fa(strategy_id: str) -> str:
    return STRATEGY_FA.get(strategy_id, strategy_id)


def _parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _session_bucket(moment: datetime) -> str:
    """Classify a UTC timestamp into configured liquidity windows."""
    t = moment.time()
    london = _time_in_range(t, 8, 0, 11, 0)
    ny = _time_in_range(t, 13, 30, 16, 30)
    asia = _time_in_range(t, 0, 0, 8, 0)
    if london and ny:
        return "overlap"
    if london:
        return "london"
    if ny:
        return "new_york"
    if asia:
        return "asia"
    return "off_hours"


def _time_in_range(t: Any, sh: int, sm: int, eh: int, em: int) -> bool:
    start = sh * 60 + sm
    end = eh * 60 + em
    cur = t.hour * 60 + t.minute
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end


@dataclass
class StrategyBreakdown:
    strategy: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    net_pnl: float = 0.0
    avg_pnl: float = 0.0


@dataclass
class HourBucket:
    hour: int
    wins: int = 0
    losses: int = 0
    net_pnl: float = 0.0

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate_pct(self) -> float:
        return round(self.wins / self.total * 100, 1) if self.total else 0.0


@dataclass
class SessionBucket:
    session: str
    wins: int = 0
    losses: int = 0
    net_pnl: float = 0.0

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate_pct(self) -> float:
        return round(self.wins / self.total * 100, 1) if self.total else 0.0


@dataclass
class SymbolBreakdown:
    symbol: str
    wins: int = 0
    losses: int = 0
    net_pnl: float = 0.0

    @property
    def total(self) -> int:
        return self.wins + self.losses


@dataclass
class PerformanceReport:
    """Aggregated analytics payload for HTML rendering."""

    account_login: str = ""
    broker_server: str = ""
    mode: str = "live"
    generated_at: str = ""
    period_start: str = ""
    period_end: str = ""
    total_closed: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    win_rate_pct: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float | None = None
    avg_pnl: float = 0.0
    avg_r_multiple: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    strategies: list[StrategyBreakdown] = field(default_factory=list)
    best_strategy_win_rate: str = ""
    best_strategy_win_rate_pct: float = 0.0
    best_win_hour: int | None = None
    best_win_hour_count: int = 0
    best_win_session: str = ""
    best_win_session_count: int = 0
    hour_buckets: list[HourBucket] = field(default_factory=list)
    session_buckets: list[SessionBucket] = field(default_factory=list)
    symbol_wins: list[SymbolBreakdown] = field(default_factory=list)
    top_winning_symbol: str = ""
    top_winning_symbol_wins: int = 0
    recommendations: list[str] = field(default_factory=list)
    data_warning: str = ""


def filter_trades_since(
    trades: list[ClosedTradeRecord],
    since: datetime | None,
) -> list[ClosedTradeRecord]:
    if since is None:
        return list(trades)
    out: list[ClosedTradeRecord] = []
    for trade in trades:
        opened = _parse_iso_dt(trade.open_time) or _parse_iso_dt(trade.close_time)
        if opened is None or opened >= since:
            out.append(trade)
    return out


def load_closed_trades(
    *,
    state_dir: str | Path = "data/state",
    mode: str = "live",
    journal_path: Path | None = None,
    since: datetime | None = None,
) -> list[ClosedTradeRecord]:
    path = journal_path or journal_path_for(state_dir, mode)
    journal = TradeJournal(path, mode=mode)
    journal.load()
    return filter_trades_since(journal.closed_trades, since)


def analyze_performance(
    trades: list[ClosedTradeRecord],
    *,
    account_login: str = "",
    broker_server: str = "",
    mode: str = "live",
    reference_equity: float | None = None,
) -> PerformanceReport:
    """Compute full analytics from closed journal rows."""
    stats = compute_trading_stats(trades, [], reference_equity=reference_equity)
    strategy_rows = compute_strategy_stats(trades, [], reference_equity=reference_equity)

    strategies = [
        StrategyBreakdown(
            strategy=row.strategy,
            trades=row.trades,
            wins=row.wins,
            losses=row.losses,
            win_rate_pct=row.win_rate_pct,
            net_pnl=row.net_pnl,
            avg_pnl=row.avg_pnl,
        )
        for row in strategy_rows
        if row.trades > 0 or row.strategy in STRATEGY_REPORT_ORDER
    ]
    strategies = [s for s in strategies if s.trades > 0]

    hour_map: dict[int, HourBucket] = {h: HourBucket(hour=h) for h in range(24)}
    session_map: dict[str, SessionBucket] = {
        key: SessionBucket(session=key) for key in SESSION_LABELS_FA
    }
    symbol_map: dict[str, SymbolBreakdown] = {}

    win_hours: Counter[int] = Counter()
    win_sessions: Counter[str] = Counter()
    symbol_win_counts: Counter[str] = Counter()

    close_times: list[datetime] = []
    for trade in trades:
        close_dt = _parse_iso_dt(trade.close_time) or _parse_iso_dt(trade.open_time)
        if close_dt:
            close_times.append(close_dt)

        sym = trade.symbol
        if sym not in symbol_map:
            symbol_map[sym] = SymbolBreakdown(symbol=sym)
        sym_row = symbol_map[sym]
        sym_row.net_pnl += trade.pnl
        if trade.pnl > 0:
            sym_row.wins += 1
            symbol_win_counts[sym] += 1
        elif trade.pnl < 0:
            sym_row.losses += 1

        if close_dt is None:
            continue
        hour = close_dt.hour
        bucket = hour_map[hour]
        if trade.pnl > 0:
            bucket.wins += 1
            win_hours[hour] += 1
        elif trade.pnl < 0:
            bucket.losses += 1
        bucket.net_pnl += trade.pnl

        session = _session_bucket(close_dt)
        sess = session_map[session]
        if trade.pnl > 0:
            sess.wins += 1
            win_sessions[session] += 1
        elif trade.pnl < 0:
            sess.losses += 1
        sess.net_pnl += trade.pnl

    best_strategy = ""
    best_wr = -1.0
    for row in strategies:
        if row.trades >= 2 and row.win_rate_pct > best_wr:
            best_wr = row.win_rate_pct
            best_strategy = row.strategy

    best_hour: int | None = None
    best_hour_count = 0
    if win_hours:
        best_hour, best_hour_count = win_hours.most_common(1)[0]

    best_session = ""
    best_session_count = 0
    if win_sessions:
        best_session, best_session_count = win_sessions.most_common(1)[0]

    top_symbol = ""
    top_symbol_wins = 0
    if symbol_win_counts:
        top_symbol, top_symbol_wins = symbol_win_counts.most_common(1)[0]

    period_start = min(close_times).isoformat() if close_times else ""
    period_end = max(close_times).isoformat() if close_times else ""

    report = PerformanceReport(
        account_login=account_login,
        broker_server=broker_server,
        mode=mode,
        generated_at=datetime.now(tz=UTC).isoformat(),
        period_start=period_start,
        period_end=period_end,
        total_closed=stats.closed_trades,
        wins=stats.wins,
        losses=stats.losses,
        breakevens=stats.breakevens,
        win_rate_pct=stats.win_rate_pct,
        net_pnl=round(stats.net_pnl, 2),
        gross_profit=round(stats.gross_profit, 2),
        gross_loss=round(stats.gross_loss, 2),
        profit_factor=stats.profit_factor,
        avg_pnl=round(stats.avg_pnl, 2),
        avg_r_multiple=round(stats.avg_r_multiple, 3),
        best_trade=round(stats.best_trade, 2),
        worst_trade=round(stats.worst_trade, 2),
        max_consecutive_wins=stats.max_consecutive_wins,
        max_consecutive_losses=stats.max_consecutive_losses,
        strategies=strategies,
        best_strategy_win_rate=best_strategy,
        best_strategy_win_rate_pct=best_wr if best_wr >= 0 else 0.0,
        best_win_hour=best_hour,
        best_win_hour_count=best_hour_count,
        best_win_session=best_session,
        best_win_session_count=best_session_count,
        hour_buckets=[hour_map[h] for h in range(24)],
        session_buckets=[session_map[k] for k in SESSION_LABELS_FA],
        symbol_wins=sorted(symbol_map.values(), key=lambda s: (-s.wins, s.symbol)),
        top_winning_symbol=top_symbol,
        top_winning_symbol_wins=top_symbol_wins,
        recommendations=_build_recommendations(
            strategies=strategies,
            stats=stats,
            session_buckets=list(session_map.values()),
            symbol_rows=list(symbol_map.values()),
            win_hours=win_hours,
        ),
    )
    return report


def _build_recommendations(
    *,
    strategies: list[StrategyBreakdown],
    stats: Any,
    session_buckets: list[SessionBucket],
    symbol_rows: list[SymbolBreakdown],
    win_hours: Counter[int],
) -> list[str]:
    tips: list[str] = []
    if stats.closed_trades == 0:
        tips.append(
            "هنوز معامله بسته‌شده‌ای در ژورنال ثبت نشده است. "
            "پس از اجرای ربات در حالت live، این گزارش را دوباره بسازید."
        )
        return tips

    if stats.net_pnl < 0:
        tips.append(
            f"سود خالص کل منفی است ({stats.net_pnl:.2f}). "
            "اولویت: بررسی استراتژی‌های زیان‌ده و کاهش تعداد نمادهای فعال."
        )
    elif stats.profit_factor is not None and stats.profit_factor < 1.0:
        tips.append(
            f"فاکتور سود ({stats.profit_factor:.2f}) زیر ۱ است — "
            "میانگین ضررها از میانگین سودها بیشتر است."
        )

    losers = [s for s in strategies if s.trades >= 5 and s.net_pnl < 0]
    for row in sorted(losers, key=lambda s: s.net_pnl):
        tips.append(
            f"استراتژی «{strategy_label_fa(row.strategy)}» با {row.trades} معامله "
            f"و نرخ برد {row.win_rate_pct:.1f}٪، {row.net_pnl:.2f} زیان خالص داده — "
            "غیرفعال‌سازی موقت یا بازبینی پارامترها پیشنهاد می‌شود."
        )

    low_wr = [s for s in strategies if s.trades >= 5 and s.win_rate_pct < 40]
    for row in low_wr:
        if row.net_pnl >= 0:
            continue
        tips.append(
            f"نرخ برد پایین در «{strategy_label_fa(row.strategy)}» "
            f"({row.win_rate_pct:.1f}٪) — فیلتر روند یا حداقل اطمینان سیگنال را افزایش دهید."
        )

    off = next((s for s in session_buckets if s.session == "off_hours"), None)
    london = next((s for s in session_buckets if s.session == "london"), None)
    ny = next((s for s in session_buckets if s.session == "new_york"), None)
    if off and off.total >= 5 and off.net_pnl < 0:
        tips.append(
            "بیشتر زیان‌ها در ساعات خارج از سشن لندن/نیویورک رخ داده — "
            "حالت `trading_hours_mode: london_ny` را فعال نگه دارید."
        )
    if london and ny and london.wins + ny.wins > 0 and off and off.wins > london.wins + ny.wins:
        tips.append(
            "معاملات برنده بیشتر در ساعات غیرسشن ثبت شده — "
            "با تنظیمات فعلی سشن هم‌خوانی ندارد؛ لاگ ورود سیگنال را بررسی کنید."
        )

    if win_hours:
        peak_hour, peak_count = win_hours.most_common(1)[0]
        if peak_count >= 3:
            tips.append(
                f"بهترین ساعت بستن معاملات برنده: {_fa_digits(peak_hour)}:۰۰ UTC "
                f"({_fa_digits(peak_count)} برد) — تمرکز معاملاتی را در این بازه حفظ کنید."
            )

    symbol_losers = [s for s in symbol_rows if s.total >= 5 and s.net_pnl < 0]
    for sym in sorted(symbol_losers, key=lambda s: s.net_pnl)[:2]:
        tips.append(
            f"نماد {sym.symbol} با {sym.losses} ضرر از {sym.total} معامله "
            f"({sym.net_pnl:.2f} خالص) — اسپرد/کمیسیون یا حد ضرر را برای این نماد بازبینی کنید."
        )

    if stats.max_consecutive_losses >= 3:
        tips.append(
            f"حداکثر {stats.max_consecutive_losses} ضرر پیاپی — "
            "قانون سه ضربه (three_strikes) و توقف موقت پس از باخت‌های متوالی را فعال نگه دارید."
        )

    if stats.avg_r_multiple < 0 and stats.closed_trades >= 5:
        tips.append(
            "میانگین R منفی است — نسبت ریسک به پاداش واقعی پس از اسپرد/کمیسیون "
            "ممکن است زیر حداقل ۱:۱.۵ باشد؛ `cost_aware_geometry` را برای اسکالپ بررسی کنید."
        )

    if not tips:
        tips.append(
            "عملکرد کلی در محدوده قابل قبول است. "
            "برای بهبود بیشتر: بک‌تست هفتگی و مقایسه استراتژی‌ها در داشبورد را ادامه دهید."
        )
    return tips


def build_performance_report(
    *,
    state_dir: str | Path = "data/state",
    mode: str = "live",
    journal_path: Path | None = None,
    since: datetime | None = None,
    account_login: str = "",
    broker_server: str = "",
    reference_equity: float | None = None,
) -> PerformanceReport:
    trades = load_closed_trades(
        state_dir=state_dir,
        mode=mode,
        journal_path=journal_path,
        since=since,
    )
    report = analyze_performance(
        trades,
        account_login=account_login,
        broker_server=broker_server,
        mode=mode,
        reference_equity=reference_equity,
    )
    if not trades:
        report.data_warning = (
            "فایل ژورنال خالی است یا معامله‌ای در بازه انتخاب‌شده یافت نشد. "
            "مطمئن شوید ربات در حالت live اجرا شده و `data/state/trade_journal_live.json` "
            "روی VPS به‌روز است."
        )
    return report


def _pf_text(value: float | None) -> str:
    if value is None:
        return "—"
    if value == float("inf"):
        return "∞"
    return _fa_digits(f"{value:.2f}")


def render_persian_html(report: PerformanceReport) -> str:
    """Render a self-contained RTL Persian HTML document."""
    strategies_rows = ""
    for row in report.strategies:
        pnl_class = "pos" if row.net_pnl >= 0 else "neg"
        strategies_rows += f"""
        <tr>
          <td>{strategy_label_fa(row.strategy)}</td>
          <td>{_fa_digits(row.trades)}</td>
          <td>{_fa_digits(row.wins)}</td>
          <td>{_fa_digits(row.losses)}</td>
          <td>{_fa_digits(f"{row.win_rate_pct:.1f}")}٪</td>
          <td class="{pnl_class}">{_fa_digits(f"{row.net_pnl:.2f}")}</td>
          <td>{_fa_digits(f"{row.avg_pnl:.2f}")}</td>
        </tr>"""

    hour_rows = ""
    max_hour_wins = max((b.wins for b in report.hour_buckets), default=1) or 1
    for bucket in report.hour_buckets:
        bar = int(bucket.wins / max_hour_wins * 100) if max_hour_wins else 0
        hour_rows += f"""
        <tr>
          <td>{_fa_digits(bucket.hour)}:۰۰ UTC</td>
          <td>{_fa_digits(bucket.wins)}</td>
          <td>{_fa_digits(bucket.losses)}</td>
          <td>{_fa_digits(f"{bucket.win_rate_pct:.1f}")}٪</td>
          <td><div class="bar"><span style="width:{bar}%"></span></div></td>
        </tr>"""

    session_rows = ""
    for bucket in report.session_buckets:
        if bucket.total == 0:
            continue
        session_rows += f"""
        <tr>
          <td>{SESSION_LABELS_FA.get(bucket.session, bucket.session)}</td>
          <td>{_fa_digits(bucket.wins)}</td>
          <td>{_fa_digits(bucket.losses)}</td>
          <td>{_fa_digits(f"{bucket.win_rate_pct:.1f}")}٪</td>
          <td>{_fa_digits(f"{bucket.net_pnl:.2f}")}</td>
        </tr>"""

    symbol_rows = ""
    for sym in report.symbol_wins[:12]:
        symbol_rows += f"""
        <tr>
          <td>{sym.symbol}</td>
          <td>{_fa_digits(sym.wins)}</td>
          <td>{_fa_digits(sym.losses)}</td>
          <td>{_fa_digits(sym.total)}</td>
          <td>{_fa_digits(f"{sym.net_pnl:.2f}")}</td>
        </tr>"""

    rec_items = "".join(f"<li>{tip}</li>" for tip in report.recommendations)
    warning = ""
    if report.data_warning:
        warning = f'<div class="warn">{report.data_warning}</div>'

    login_line = _fa_digits(report.account_login) if report.account_login else "—"
    server_line = report.broker_server or "—"
    best_strat = (
        f"{strategy_label_fa(report.best_strategy_win_rate)} "
        f"({_fa_digits(f'{report.best_strategy_win_rate_pct:.1f}')}٪)"
        if report.best_strategy_win_rate
        else "—"
    )
    best_hour = (
        f"{_fa_digits(report.best_win_hour)}:۰۰ UTC "
        f"({_fa_digits(report.best_win_hour_count)} برد)"
        if report.best_win_hour is not None
        else "—"
    )
    best_sess = (
        f"{SESSION_LABELS_FA.get(report.best_win_session, report.best_win_session)} "
        f"({_fa_digits(report.best_win_session_count)} برد)"
        if report.best_win_session
        else "—"
    )
    top_sym = (
        f"{report.top_winning_symbol} ({_fa_digits(report.top_winning_symbol_wins)} برد)"
        if report.top_winning_symbol
        else "—"
    )
    net_class = "pos" if report.net_pnl >= 0 else "neg"

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>گزارش عملکرد ChronoScalp</title>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a2332;
      --text: #e8edf4;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --pos: #22c55e;
      --neg: #ef4444;
      --warn-bg: #422006;
      --warn-border: #f59e0b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Tahoma, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.7;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
    h1 {{ font-size: 1.6rem; margin: 0 0 8px; }}
    h2 {{ font-size: 1.15rem; margin: 28px 0 12px; color: var(--accent); }}
    .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 20px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin: 16px 0;
    }}
    .card {{
      background: var(--card);
      border-radius: 10px;
      padding: 14px 16px;
      border: 1px solid #2a3548;
    }}
    .card .label {{ color: var(--muted); font-size: 0.8rem; }}
    .card .value {{ font-size: 1.25rem; font-weight: 700; margin-top: 4px; }}
    .pos {{ color: var(--pos); }}
    .neg {{ color: var(--neg); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border-radius: 10px;
      overflow: hidden;
      font-size: 0.9rem;
    }}
    th, td {{ padding: 10px 12px; text-align: right; border-bottom: 1px solid #2a3548; }}
    th {{ background: #243044; color: var(--muted); font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    .bar {{ background: #2a3548; border-radius: 4px; height: 8px; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: var(--accent); border-radius: 4px; }}
    .warn {{
      background: var(--warn-bg);
      border: 1px solid var(--warn-border);
      border-radius: 8px;
      padding: 12px 16px;
      margin: 16px 0;
    }}
    ul.rec {{ padding-right: 20px; }}
    ul.rec li {{ margin-bottom: 8px; }}
    .highlight {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin: 12px 0 20px;
    }}
    .highlight .card .value {{ font-size: 1rem; }}
    footer {{ margin-top: 32px; color: var(--muted); font-size: 0.8rem; text-align: center; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>گزارش عملکرد ربات ChronoScalp</h1>
    <p class="meta">
      حساب: <strong>{login_line}</strong> · سرور: {server_line} · حالت: {report.mode}
      · تولید: {_fa_digits(report.generated_at[:19].replace("T", " "))} UTC
    </p>
    {warning}
    <div class="grid">
      <div class="card"><div class="label">معاملات بسته</div><div class="value">{_fa_digits(report.total_closed)}</div></div>
      <div class="card"><div class="label">نرخ برد</div><div class="value">{_fa_digits(f"{report.win_rate_pct:.1f}")}٪</div></div>
      <div class="card"><div class="label">سود خالص</div><div class="value {net_class}">{_fa_digits(f"{report.net_pnl:.2f}")}</div></div>
      <div class="card"><div class="label">فاکتور سود</div><div class="value">{_pf_text(report.profit_factor)}</div></div>
      <div class="card"><div class="label">میانگین سود/معامله</div><div class="value">{_fa_digits(f"{report.avg_pnl:.2f}")}</div></div>
      <div class="card"><div class="label">میانگین R</div><div class="value">{_fa_digits(f"{report.avg_r_multiple:.2f}")}</div></div>
    </div>

    <h2>خلاصه کلیدی</h2>
    <div class="highlight">
      <div class="card"><div class="label">بیشترین نرخ برد (حداقل ۲ معامله)</div><div class="value">{best_strat}</div></div>
      <div class="card"><div class="label">بهترین ساعت معاملات برنده</div><div class="value">{best_hour}</div></div>
      <div class="card"><div class="label">بهترین بازه سشن</div><div class="value">{best_sess}</div></div>
      <div class="card"><div class="label">پربردترین نماد</div><div class="value">{top_sym}</div></div>
    </div>

    <h2>عملکرد به تفکیک استراتژی</h2>
    <table>
      <thead>
        <tr>
          <th>استراتژی</th><th>تعداد</th><th>برد</th><th>باخت</th><th>نرخ برد</th><th>سود خالص</th><th>میانگین</th>
        </tr>
      </thead>
      <tbody>{strategies_rows or '<tr><td colspan="7">داده‌ای نیست</td></tr>'}</tbody>
    </table>

    <h2>توزیع ساعتی معاملات برنده (UTC)</h2>
    <table>
      <thead>
        <tr><th>ساعت</th><th>برد</th><th>باخت</th><th>نرخ برد</th><th>نمودار برد</th></tr>
      </thead>
      <tbody>{hour_rows or '<tr><td colspan="5">داده‌ای نیست</td></tr>'}</tbody>
    </table>

    <h2>عملکرد بر اساس سشن معاملاتی</h2>
    <table>
      <thead>
        <tr><th>سشن</th><th>برد</th><th>باخت</th><th>نرخ برد</th><th>سود خالص</th></tr>
      </thead>
      <tbody>{session_rows or '<tr><td colspan="5">داده‌ای نیست</td></tr>'}</tbody>
    </table>

    <h2>عملکرد به تفکیک نماد</h2>
    <table>
      <thead>
        <tr><th>نماد</th><th>برد</th><th>باخت</th><th>کل</th><th>سود خالص</th></tr>
      </thead>
      <tbody>{symbol_rows or '<tr><td colspan="5">داده‌ای نیست</td></tr>'}</tbody>
    </table>

    <h2>پیشنهادهای بهبود عملکرد</h2>
    <ul class="rec">{rec_items}</ul>

    <footer>ChronoScalp · گزارش خودکار از trade journal · حداکثر ریسک ۱٪ و R:R حداقل ۱:۱.۵</footer>
  </div>
</body>
</html>"""


def write_persian_html_report(
    output_path: str | Path,
    *,
    state_dir: str | Path = "data/state",
    mode: str = "live",
    journal_path: Path | None = None,
    since: datetime | None = None,
    account_login: str = "",
    broker_server: str = "",
    reference_equity: float | None = None,
) -> PerformanceReport:
    """Build report and write UTF-8 HTML to ``output_path``."""
    report = build_performance_report(
        state_dir=state_dir,
        mode=mode,
        journal_path=journal_path,
        since=since,
        account_login=account_login,
        broker_server=broker_server,
        reference_equity=reference_equity,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_persian_html(report), encoding="utf-8")
    return report


def read_account_from_snapshot(state_dir: str | Path, mode: str) -> tuple[str, str]:
    """Read login/server from broker_positions snapshot if present."""
    path = Path(state_dir) / f"broker_positions_{mode}.json"
    if not path.exists():
        return "", ""
    import json

    with path.open(encoding="utf-8-sig") as f:
        raw = json.load(f)
    account = raw.get("account") if isinstance(raw.get("account"), dict) else {}
    login = str(account.get("login") or "")
    server = str(account.get("server") or "")
    return login, server
