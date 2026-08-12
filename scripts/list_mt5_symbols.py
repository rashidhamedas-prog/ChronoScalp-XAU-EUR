#!/usr/bin/env python3
"""List MT5 symbols matching gold/FX names (research helper)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.data.mt5_connector import MT5Connector  # noqa: E402


def main() -> int:
    settings = get_settings()
    connector = MT5Connector(
        login=settings.secrets.mt5_login,
        password=settings.secrets.mt5_password,
        server=settings.secrets.mt5_server,
        terminal_path=settings.secrets.mt5_terminal_path,
    )
    if not connector.connect():
        print("CONNECT_FAIL")
        return 1
    try:
        import MetaTrader5 as mt5  # noqa: N813

        all_syms = mt5.symbols_get() or []
        needles = ("XAU", "GOLD", "EURUSD", "EUR", "USD")
        hits = []
        for s in all_syms:
            name = str(getattr(s, "name", "") or "")
            upper = name.upper()
            if any(n in upper for n in needles):
                visible = bool(getattr(s, "visible", False))
                hits.append((name, visible))
        print(f"TOTAL_SYMBOLS={len(all_syms)}")
        print(f"MATCHES={len(hits)}")
        for name, visible in sorted(hits)[:80]:
            print(f"{'V' if visible else '.'} {name}")
        # Try common candidates
        for cand in ("XAUUSD", "XAUUSD_o", "GOLD", "EURUSD", "EURUSD_o"):
            info = mt5.symbol_info(cand)
            selected = mt5.symbol_select(cand, True)
            print(f"CANDIDATE {cand} info={info is not None} select={selected} err={mt5.last_error()}")
    finally:
        connector.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
