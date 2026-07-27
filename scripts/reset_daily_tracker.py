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
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["live", "paper"], default="live")
    parser.add_argument(
        "--state-dir",
        default="data/state",
        help="State directory (default: data/state)",
    )
    args = parser.parse_args()

    path = Path(args.state_dir) / f"daily_reset_{args.mode}.json"
    payload = {"reset_at": datetime.now(tz=UTC).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Daily tracker reset marker written: {path} -> {payload['reset_at']}")
    print("Restart the bot (run_live) for the reset to take effect.")


if __name__ == "__main__":
    main()
