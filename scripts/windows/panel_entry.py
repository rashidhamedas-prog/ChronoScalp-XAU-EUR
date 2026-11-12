#!/usr/bin/env python3
"""Desktop entry for the Streamlit control panel.

Does not set ``CHRONOSCALP_CONFIRM_LIVE``. The panel can record an explicit
yes only after the operator asks for it; the logon task never does that.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap() -> Path:
    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    scripts = root / "scripts"
    for path in (src, scripts):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from chronoscalp.platform.desktop import prepare_desktop_home

    bundled = Path(getattr(sys, "_MEIPASS", root))
    config = bundled / "config"
    if not config.is_dir():
        config = root / "config"
    example = bundled / ".env.example"
    if not example.is_file():
        example = root / ".env.example"
    home = prepare_desktop_home(config, example if example.is_file() else None)
    os.chdir(home)
    return home


def _panel_script() -> Path:
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    candidates = [
        bundled / "scripts" / "app.py",
        Path(__file__).resolve().parents[1] / "app.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("scripts/app.py was not bundled with the panel")


def main() -> None:
    _bootstrap()
    script = _panel_script()
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(script),
        "--global.developmentMode",
        "false",
        "--server.port",
        "8501",
        "--server.headless",
        "true",
    ]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    main()
