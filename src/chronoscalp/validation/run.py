"""CLI entry: ``python -m chronoscalp.validation.run --all``.

Without broker history this runs a **synthetic smoke path** so CI can exercise
the validation plane. Pass ``--from-json`` with net trade-R series for real
reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from chronoscalp.logging_setup import logger
from chronoscalp.validation.reports import build_report_from_trade_r, write_report


def _synthetic_trade_r(n: int = 80, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    # Mild positive expectancy net of costs (~0.15R) with fat left tail.
    wins = rng.normal(1.6, 0.35, size=n)
    losses = rng.normal(-1.0, 0.25, size=n)
    mask = rng.random(n) < 0.58
    return [float(w if m else loss) for w, loss, m in zip(wins, losses, mask, strict=False)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ChronoScalp Phase 1 validation runner")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run the full validation pack (synthetic if no --from-json).",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="JSON file with {strategy, symbol, trade_r: [...]} net R multiples.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/reports/validation"),
        help="Directory for machine-readable reports.",
    )
    parser.add_argument("--n-trials", type=int, default=None)
    args = parser.parse_args(argv)

    if not args.all and args.from_json is None:
        parser.print_help()
        return 2

    payloads: list[dict] = []
    if args.from_json is not None:
        raw = json.loads(args.from_json.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            payloads.extend(raw)
        else:
            payloads.append(raw)
    else:
        payloads.append(
            {
                "strategy": "synthetic_smoke",
                "symbol": "XAUUSD",
                "trade_r": _synthetic_trade_r(),
            }
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for item in payloads:
        strategy = str(item.get("strategy", "unknown"))
        symbol = str(item.get("symbol", "UNKNOWN"))
        trade_r = [float(x) for x in item.get("trade_r", [])]
        report = build_report_from_trade_r(
            strategy=strategy,
            symbol=symbol,
            trade_r=trade_r,
            n_trials=args.n_trials,
        )
        path = args.out_dir / f"{symbol}_{strategy}_validation.json"
        write_report(report, path)
        written.append(str(path))
        logger.info(
            "Validation {} {} verdict={} dsr={:.3f} pbo={:.3f} n={}",
            symbol,
            strategy,
            report.verdict,
            report.dsr,
            report.pbo,
            report.n_trades,
        )

    summary_path = args.out_dir / "validation_run_summary.json"
    summary_path.write_text(
        json.dumps({"reports": written, "count": len(written)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "reports": written}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
