#!/usr/bin/env python3
"""Generate a Persian HTML performance report from the trade journal.

Examples::

    # Default: live journal on VPS / local install
    python scripts/generate_performance_report.py

    # Filter trades after broker change (ISO date, UTC)
    python scripts/generate_performance_report.py --since 2026-07-20 --login 55625500

    # Custom journal export copied from VPS
    python scripts/generate_performance_report.py --journal /path/trade_journal_live.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.reports.performance_report import (  # noqa: E402
    read_account_from_snapshot,
    write_persian_html_report,
)


def _parse_since(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _import_mt5_history(
    *,
    login: int,
    password: str,
    server: str,
    terminal_path: str,
    since: datetime | None,
    output_journal: Path,
) -> int:
    """Windows-only: rebuild closed trades from MT5 deal history into journal JSON."""
    try:
        from chronoscalp.data.mt5_connector import MT5Connector
        from chronoscalp.execution.mt5_utils import CHRONOSCALP_MAGIC
        from chronoscalp.utils.strategy_tags import resolve_strategy_tag
    except Exception as exc:  # noqa: BLE001
        logger.error("MT5 import unavailable: {}", exc)
        return 0

    connector = MT5Connector(login, password, server, terminal_path)
    connector.connect()
    import MetaTrader5 as mt5  # type: ignore[import-untyped]

    date_from = since or datetime(2020, 1, 1, tzinfo=UTC)
    date_to = datetime.now(tz=UTC)
    deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        logger.warning("No MT5 deals returned: {}", mt5.last_error())
        connector.disconnect()
        return 0

    by_position: dict[int, list] = {}
    for deal in deals:
        if deal.magic != CHRONOSCALP_MAGIC:
            continue
        pos_id = int(getattr(deal, "position_id", 0) or 0)
        if pos_id <= 0:
            continue
        by_position.setdefault(pos_id, []).append(deal)

    closed_rows: list[dict] = []
    for pos_id, group in by_position.items():
        entry = next((d for d in group if d.entry == 0), None)
        exit_deal = next((d for d in group if d.entry == 1), None)
        if entry is None or exit_deal is None:
            continue
        pnl = float(sum(d.profit + d.swap + d.commission for d in group))
        direction = "buy" if entry.type in (0, 2) else "sell"
        strategy = resolve_strategy_tag(comment=str(entry.comment or ""))
        closed_rows.append(
            {
                "ticket": pos_id,
                "symbol": str(entry.symbol),
                "direction": direction,
                "volume": float(entry.volume),
                "entry_price": float(entry.price),
                "exit_price": float(exit_deal.price),
                "open_time": datetime.fromtimestamp(entry.time, tz=UTC).isoformat(),
                "close_time": datetime.fromtimestamp(exit_deal.time, tz=UTC).isoformat(),
                "pnl": round(pnl, 2),
                "r_multiple": 0.0,
                "exit_reason": "mt5_import",
                "mode": "live",
                "strategy": strategy,
                "reason": str(entry.comment or ""),
            }
        )

    payload = {
        "mode": "live",
        "updated_at": datetime.now(tz=UTC).isoformat(),
        "open_trades": [],
        "closed_trades": closed_rows,
        "imported_from_mt5": True,
        "account_login": login,
    }
    output_journal.parent.mkdir(parents=True, exist_ok=True)
    output_journal.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    connector.disconnect()
    logger.info("Imported {} closed trades from MT5 into {}", len(closed_rows), output_journal)
    return len(closed_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Persian HTML trading performance report")
    parser.add_argument("--state-dir", default="data/state", help="State directory (default: data/state)")
    parser.add_argument("--mode", default="live", choices=("live", "paper"))
    parser.add_argument("--journal", default=None, help="Override trade journal JSON path")
    parser.add_argument("--output", default="data/reports/performance_report.html")
    parser.add_argument("--since", default=None, help="Only trades on/after this date (YYYY-MM-DD)")
    parser.add_argument("--login", default=None, help="MT5 account login label for the report header")
    parser.add_argument("--server", default=None, help="Broker server name for the report header")
    parser.add_argument("--equity", type=float, default=None, help="Reference equity for %% metrics")
    parser.add_argument(
        "--import-mt5",
        action="store_true",
        help="Windows only: import deals from MT5 before reporting (uses .env credentials)",
    )
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    journal_path = Path(args.journal) if args.journal else None
    since = _parse_since(args.since)

    login = str(args.login or "")
    server = str(args.server or "")
    snap_login, snap_server = read_account_from_snapshot(state_dir, args.mode)
    if not login:
        login = snap_login
    if not server:
        server = snap_server

    if args.import_mt5:
        from chronoscalp.config import get_settings

        secrets = get_settings().secrets
        target = journal_path or state_dir / f"trade_journal_{args.mode}.json"
        count = _import_mt5_history(
            login=int(secrets.mt5_login or args.login or 0),
            password=str(secrets.mt5_password or ""),
            server=str(secrets.mt5_server or ""),
            terminal_path=str(secrets.mt5_path or ""),
            since=since,
            output_journal=target,
        )
        if count == 0:
            logger.warning("MT5 import produced 0 trades — falling back to existing journal")
        journal_path = target
        if not login and secrets.mt5_login:
            login = str(secrets.mt5_login)

    report = write_persian_html_report(
        args.output,
        state_dir=state_dir,
        mode=args.mode,
        journal_path=journal_path,
        since=since,
        account_login=login,
        broker_server=server,
        reference_equity=args.equity,
    )

    if args.login and snap_login and args.login != snap_login:
        logger.warning(
            "Requested login {} differs from snapshot login {}",
            args.login,
            snap_login,
        )

    print(f"Report written: {args.output}")
    print(f"Closed trades: {report.total_closed}")
    print(f"Net P&L: {report.net_pnl}")
    if report.data_warning:
        print(f"Warning: {report.data_warning}")


if __name__ == "__main__":
    main()
