# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for the paper/live runner.

Build on Windows only. This file does not embed a fake executable.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

spec_dir = Path(SPECPATH).resolve()
root = spec_dir.parents[1]

hidden = collect_submodules("chronoscalp")
hidden += ["yaml", "pydantic", "pydantic_settings", "loguru", "dotenv"]

a = Analysis(
    [str(root / "scripts" / "windows" / "runner_entry.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(root / "config"), "config"),
        (str(root / ".env.example"), "."),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["streamlit"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChronoScalpRunner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ChronoScalpRunner",
)
