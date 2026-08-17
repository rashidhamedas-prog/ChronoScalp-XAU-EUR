#!/usr/bin/env python3
"""Measure how much of the entry funnel the spread guard consumes.

Research only — this reports, it never edits config. On the VPS the XAUUSD
spread was repeatedly observed at 8-13 against a ``MA x 1.20`` cap of roughly
7.4, which raises the question of whether the guard is mis-tuned for this
broker or whether the broker is simply expensive. Answering that needs a
distribution over days, not a handful of log lines.

Two facts are recovered from the daily logs:

* ``institutional_guards`` logs one line per *rejection* with the observed
  spread and the cap that rejected it. That gives the shape of the rejections,
  but not of accepted spreads, so treat the quantiles as "how bad is it when it
  blocks", never as the spread distribution.
* The entry skip heartbeat counts every skipped evaluation by reason, which is
  what turns those rejections into a share of the funnel.

Usage::

    python scripts/analyze_spread_guard.py --logs logs --days 7
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.logging_setup import logger  # noqa: E402

GUARD_RE = re.compile(
    r"(?P<symbol>[A-Z0-9._]+) spread guard: "
    r"(?P<spread>[\d.]+) > MA(?P<ma>[\d.]+)\*(?P<mult>[\d.]+)"
)
HEARTBEAT_RE = re.compile(r"Entry skip heartbeat \(\d+s\): (?P<body>.+)$")


@dataclass
class SymbolStats:
    """Spread-guard evidence accumulated for one symbol."""

    skips_total: int = 0
    skips_by_reason: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    blocked_spreads: list[float] = field(default_factory=list)
    blocked_caps: list[float] = field(default_factory=list)

    @property
    def spread_skips(self) -> int:
        return self.skips_by_reason.get("spread_ma", 0)


def _quantile(values: list[float], fraction: float) -> float:
    """Nearest-rank quantile — the samples are far too few to interpolate."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def parse_heartbeat(body: str, stats: dict[str, SymbolStats]) -> None:
    """Accumulate ``SYMBOL:reason=count`` entries from one heartbeat line.

    Reasons legitimately contain ``:`` and ``|`` (for example
    ``scalp:scalp:symbol_blocked|inst:inst:trend_neutral``), so the symbol is
    taken from the first colon and the count from the last equals sign.
    """
    for chunk in body.split(", "):
        symbol, sep, rest = chunk.partition(":")
        if not sep:
            continue
        reason, sep, raw_count = rest.rpartition("=")
        if not sep:
            continue
        try:
            count = int(raw_count)
        except ValueError:
            continue
        entry = stats[symbol.strip()]
        entry.skips_total += count
        entry.skips_by_reason[reason] += count


def parse_log(path: Path, stats: dict[str, SymbolStats]) -> None:
    """Fold one daily log file into ``stats``."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            guard = GUARD_RE.search(line)
            if guard is not None:
                entry = stats[guard["symbol"]]
                entry.blocked_spreads.append(float(guard["spread"]))
                entry.blocked_caps.append(float(guard["ma"]) * float(guard["mult"]))
                continue
            heartbeat = HEARTBEAT_RE.search(line)
            if heartbeat is not None:
                parse_heartbeat(heartbeat["body"], stats)


def build_report(stats: dict[str, SymbolStats], sources: list[str]) -> dict:
    """Turn accumulated stats into a JSON-serialisable report."""
    symbols: dict[str, dict] = {}
    for symbol in sorted(stats):
        entry = stats[symbol]
        spreads = entry.blocked_spreads
        caps = entry.blocked_caps
        share = entry.spread_skips / entry.skips_total if entry.skips_total else 0.0
        symbols[symbol] = {
            "skipped_evaluations": entry.skips_total,
            "spread_guard_skips": entry.spread_skips,
            "spread_guard_share_of_skips": round(share, 4),
            "rejections_sampled": len(spreads),
            "observed_spread_when_blocked": {
                "min": round(min(spreads), 2) if spreads else None,
                "median": round(median(spreads), 2) if spreads else None,
                "p90": round(_quantile(spreads, 0.9), 2) if spreads else None,
                "max": round(max(spreads), 2) if spreads else None,
            },
            "cap_when_blocked_median": round(median(caps), 2) if caps else None,
            "median_excess_ratio": (
                round(median(spreads) / median(caps), 2) if spreads and caps else None
            ),
            "top_skip_reasons": dict(
                sorted(entry.skips_by_reason.items(), key=lambda kv: kv[1], reverse=True)[:5]
            ),
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "log_files": sources,
        "symbols": symbols,
        "caveat": (
            "Only rejected spreads are logged, so the quantiles describe blocked "
            "samples and not the full spread distribution."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", default="logs", help="directory holding chronoscalp_*.log")
    parser.add_argument("--days", type=int, default=7, help="how many recent log files to read")
    parser.add_argument("--out", default="", help="optional path for the JSON report")
    args = parser.parse_args()

    log_dir = Path(args.logs)
    files = sorted(log_dir.glob("chronoscalp_*.log"))[-args.days :]
    if not files:
        logger.error("No chronoscalp_*.log files under {}", log_dir)
        return 1

    stats: dict[str, SymbolStats] = defaultdict(SymbolStats)
    for path in files:
        logger.info("Reading {}", path.name)
        parse_log(path, stats)

    report = build_report(stats, [p.name for p in files])
    for symbol, data in report["symbols"].items():
        logger.info(
            "{}: {} skips, {} by spread guard ({:.0%}); blocked spread median {} vs cap {}",
            symbol,
            data["skipped_evaluations"],
            data["spread_guard_skips"],
            data["spread_guard_share_of_skips"],
            data["observed_spread_when_blocked"]["median"],
            data["cap_when_blocked_median"],
        )

    out = Path(args.out) if args.out else Path("data/reports/spread_guard_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Wrote {}", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
