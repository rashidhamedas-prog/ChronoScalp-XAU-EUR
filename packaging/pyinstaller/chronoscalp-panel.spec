# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for the Streamlit control panel.

Streamlit's data files are collected on the Windows build machine.
If collection fails, fix the spec once; do not commit a stand-in exe.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

spec_dir = Path(SPECPATH).resolve()
root = spec_dir.parents[1]

hidden = collect_submodules("chronoscalp") + collect_submodules("streamlit")
hidden += [
    "yaml",
    "pydantic",
    "pydantic_settings",
    "loguru",
    "dotenv",
    "altair",
    "pyarrow",
]
datas = collect_data_files("streamlit")
datas += [
    (str(root / "config"), "config"),
    (str(root / ".env.example"), "."),
    (str(root / "scripts" / "app.py"), "scripts"),
    (str(root / "scripts" / "dashboard_i18n.py"), "scripts"),
    (str(root / "scripts" / "dashboard_stats.py"), "scripts"),
    (str(root / "scripts" / "panel_theme.py"), "scripts"),
]

a = Analysis(
    [str(root / "scripts" / "windows" / "panel_entry.py")],
    pathex=[str(root / "src"), str(root / "scripts")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChronoScalpPanel",
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
    name="ChronoScalpPanel",
)
