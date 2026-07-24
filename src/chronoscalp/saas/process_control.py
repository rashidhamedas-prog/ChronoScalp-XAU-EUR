"""Start/stop the trading bot as a managed subprocess (Windows/Linux)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from chronoscalp.logging_setup import logger

PID_FILE = Path("data/user/bot.pid")
ROOT = Path(__file__).resolve().parents[3]


def _python_executable() -> str:
    """Prefer project venv so panel and bot share one interpreter."""
    win = ROOT / ".venv" / "Scripts" / "python.exe"
    if win.exists():
        return str(win)
    unix = ROOT / ".venv" / "bin" / "python"
    if unix.exists():
        return str(unix)
    return sys.executable


def bot_is_running(pid_file: Path = PID_FILE) -> bool:
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        pid_file.unlink(missing_ok=True)
        return False
    return True


def start_bot(mode: str = "paper", pid_file: Path = PID_FILE) -> tuple[bool, str]:
    """Spawn ``scripts/run_live.py`` in the background."""
    if bot_is_running(pid_file):
        return False, "ربات از قبل در حال اجراست"

    script = ROOT / "scripts" / "run_live.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "bot_stdout.log").open("a", encoding="utf-8")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    proc = subprocess.Popen(
        [_python_executable(), str(script), "--mode", mode],
        cwd=str(ROOT),
        env=env,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    logger.info("Started bot pid={} mode={}", proc.pid, mode)
    return True, f"ربات با PID {proc.pid} در حالت {mode} شروع شد"


def stop_bot(pid_file: Path = PID_FILE) -> tuple[bool, str]:
    if not pid_file.exists():
        return False, "ربات در حال اجرا نیست"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return False, "فایل PID نامعتبر بود"

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        pid_file.unlink(missing_ok=True)
        return False, f"خطا در توقف: {exc}"

    pid_file.unlink(missing_ok=True)
    logger.info("Stopped bot pid={}", pid)
    return True, f"ربات (PID {pid}) متوقف شد"
