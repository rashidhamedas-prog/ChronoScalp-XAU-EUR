#!/usr/bin/env python3
"""Run the ChronoScalp control API (FastAPI / uvicorn).

Usage:
  set CHRONOSCALP_API_TOKEN=your-secret
  python scripts/run_api.py --host 0.0.0.0 --port 8510
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="ChronoScalp control API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8510)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "chronoscalp.saas.api:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
