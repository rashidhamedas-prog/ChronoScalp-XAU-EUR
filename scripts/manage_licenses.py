#!/usr/bin/env python3
"""Issue / list / revoke ChronoScalp license keys (seller CLI).

Usage:
    python scripts/manage_licenses.py issue --tier monthly --email customer@example.com
    python scripts/manage_licenses.py list
    python scripts/manage_licenses.py revoke CS-MONTHLY-XXXX-...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.licensing import LicenseStore, LicenseTier, issue_license  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage ChronoScalp licenses")
    sub = parser.add_subparsers(dest="cmd", required=True)

    issue_p = sub.add_parser("issue", help="Issue a new license key")
    issue_p.add_argument("--tier", choices=[t.value for t in LicenseTier], default="monthly")
    issue_p.add_argument("--email", default="")
    issue_p.add_argument("--name", default="")
    issue_p.add_argument("--notes", default="")
    issue_p.add_argument("--max-activations", type=int, default=1)

    sub.add_parser("list", help="List issued licenses")

    revoke_p = sub.add_parser("revoke", help="Revoke a license key")
    revoke_p.add_argument("key")

    args = parser.parse_args()
    settings = get_settings()
    secret = settings.secrets.license_admin_secret
    if not secret.strip():
        logger.error("Set LICENSE_ADMIN_SECRET in .env before issuing licenses")
        sys.exit(1)

    store = LicenseStore()

    if args.cmd == "issue":
        rec = issue_license(
            admin_secret=secret,
            tier=LicenseTier(args.tier),
            customer_email=args.email,
            customer_name=args.name,
            notes=args.notes,
            max_activations=args.max_activations,
        )
        store.add(rec)
        print(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False))
        print(f"\nKEY: {rec.key}")
    elif args.cmd == "list":
        print(json.dumps([r.to_dict() for r in store.list_all()], indent=2, ensure_ascii=False))
    elif args.cmd == "revoke":
        ok = store.revoke(args.key)
        print("revoked" if ok else "not found")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
