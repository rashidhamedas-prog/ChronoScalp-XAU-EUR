"""Write an explicit daily-loss-tracker reset marker (operator action).

The live bot seeds today's realized P&L from the trade journal at startup so
restarts cannot bypass the 3% daily stop. This script records a conscious
operator reset: trades closed before the marker stop counting toward today's
limit. Restart the bot afterwards for it to take effect.

Usage:
    python scripts/reset_daily_tracker.py [--mode live|paper]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from chronoscalp.orchestration.trade_journal import write_daily_reset_marker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["live", "paper"], default="live")
    parser.add_argument(
        "--state-dir",
        default="data/state",
        help="State directory (default: data/state)",
    )
    args = parser.parse_args()

    reset_at = write_daily_reset_marker(Path(args.state_dir), args.mode)
    path = Path(args.state_dir) / f"daily_reset_{args.mode}.json"
    print(f"Daily tracker reset marker written: {path} -> {reset_at.isoformat()}")
    print("Restart the bot (run_live) for the reset to take effect.")


if __name__ == "__main__":
    main()
