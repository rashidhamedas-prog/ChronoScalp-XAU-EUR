#!/usr/bin/env python3
"""CLI wrapper — generate a Persian HTML account performance report.

Example:
  PYTHONPATH=src python scripts/generate_account_report_fa.py \\
    --journal data/state/trade_journal_live.json \\
    --account-json data/state/broker_positions_live.json \\
    --state data/state/trading_state_live.json \\
    --login 55625500 \\
    --out reports/report_55625500_fa.html
"""

from __future__ import annotations

from chronoscalp.reporting.account_report_fa import main

if __name__ == "__main__":
    main()
