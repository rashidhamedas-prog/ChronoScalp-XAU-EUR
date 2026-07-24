#!/usr/bin/env python3
"""CLI entry point for paper/live trading.

Usage:
    python scripts/run_live.py --mode paper
    python scripts/run_live.py --mode live      # requires CHRONOSCALP_CONFIRM_LIVE=yes in .env

Deployment:
    Windows + MT5  →  execution.broker=mt5, data_source=mt5
    Linux VPS (NL) →  execution.broker=oanda, data_source=oanda  (see docs/DEPLOY_NL_VPS.md)
    Paper anywhere →  execution.broker=paper, data_source=oanda|mt5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.main import TradingBot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ChronoScalp in paper or live mode")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    # #region agent log
    try:
        import json
        from datetime import UTC, datetime
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        with open(root / "debug-eb4742.log", "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "sessionId": "eb4742",
                        "runId": "pre-fix",
                        "hypothesisId": "A",
                        "location": "run_live.main",
                        "message": "run_live entry",
                        "data": {
                            "mode": args.mode,
                            "confirm": settings.secrets.live_trading_confirmed,
                            "env_exists": (root / ".env").exists(),
                            "broker": settings.execution.get("broker"),
                        },
                        "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:  # noqa: BLE001
        pass
    # #endregion

    try:
        from chronoscalp.licensing import require_valid_license

        require_valid_license(settings)
        bot = TradingBot(settings, mode=args.mode)
    except RuntimeError as exc:
        logger.error(str(exc))
        # #region agent log
        try:
            import json
            from datetime import UTC, datetime
            from pathlib import Path

            root = Path(__file__).resolve().parents[1]
            with open(root / "debug-eb4742.log", "a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "sessionId": "eb4742",
                            "runId": "pre-fix",
                            "hypothesisId": "A",
                            "location": "run_live.main",
                            "message": "run_live RuntimeError exit",
                            "data": {"error": str(exc)[:300]},
                            "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:  # noqa: BLE001
            pass
        # #endregion
        sys.exit(1)

    bot.start()


if __name__ == "__main__":
    main()
