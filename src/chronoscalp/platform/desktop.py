"""Writable per-user paths for the Windows desktop install.

A git checkout leaves ``CHRONOSCALP_HOME`` unset and keeps using the
repository. The frozen app and the installer set the home to
``%APPDATA%\\ChronoScalp`` so ``.env`` and config stay out of a read-only
install directory.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from chronoscalp.config import bundled_root

APP_DIR_NAME = "ChronoScalp"


def default_windows_home() -> Path | None:
    """``%APPDATA%\\ChronoScalp`` when AppData exists. Otherwise ``None``."""
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        return None
    return Path(appdata) / APP_DIR_NAME


def resolve_desktop_home() -> Path:
    """Home directory for this process.

    Explicit ``CHRONOSCALP_HOME`` wins. A frozen Windows build uses AppData.
    A source checkout uses the repository root.
    """
    explicit = os.environ.get("CHRONOSCALP_HOME", "").strip()
    if explicit:
        return Path(explicit)
    if getattr(sys, "frozen", False):
        windows_home = default_windows_home()
        if windows_home is not None:
            return windows_home
    return bundled_root()


def prepare_desktop_home(
    bundled_config: Path,
    bundled_env_example: Path | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """Create the user directory and seed config / ``.env`` once.

    Existing files are left untouched, including a user who later sets
    ``CHRONOSCALP_CONFIRM_LIVE``. A newly created ``.env`` always starts at
    ``no``.
    """
    target = home or resolve_desktop_home()
    target.mkdir(parents=True, exist_ok=True)
    (target / "data" / "state").mkdir(parents=True, exist_ok=True)
    (target / "data" / "user").mkdir(parents=True, exist_ok=True)
    (target / "logs").mkdir(parents=True, exist_ok=True)

    config_dest = target / "config"
    settings_file = config_dest / "settings.yaml"
    if bundled_config.is_dir() and not settings_file.exists():
        config_dest.mkdir(parents=True, exist_ok=True)
        for item in bundled_config.iterdir():
            dest = config_dest / item.name
            if dest.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    env_path = target / ".env"
    if not env_path.exists() and bundled_env_example is not None and bundled_env_example.is_file():
        text = bundled_env_example.read_text(encoding="utf-8")
        text = re.sub(
            r"(?m)^CHRONOSCALP_CONFIRM_LIVE=.*$",
            "CHRONOSCALP_CONFIRM_LIVE=no",
            text,
        )
        if "CHRONOSCALP_CONFIRM_LIVE=" not in text:
            text = text.rstrip() + "\nCHRONOSCALP_CONFIRM_LIVE=no\n"
        env_path.write_text(text, encoding="utf-8")

    os.environ["CHRONOSCALP_HOME"] = str(target)
    if settings_file.exists() or (config_dest / "settings.yaml").exists():
        os.environ["CHRONOSCALP_CONFIG_DIR"] = str(config_dest)
    return target
