"""Start/stop the trading bot as a managed subprocess (Windows/Linux)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from chronoscalp.logging_setup import logger

PID_FILE = Path("data/user/bot.pid")
ROOT = Path(__file__).resolve().parents[3]


def _agent_dbg(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "eb4742",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000),
        }
        with open(ROOT / "debug-eb4742.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
    # #endregion


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
        # #region agent log
        _agent_dbg("B", "process_control.bot_is_running", "pid dead; clearing pid file", {"pid": pid})
        # #endregion
        pid_file.unlink(missing_ok=True)
        return False
    return True


def start_bot(mode: str = "paper", pid_file: Path = PID_FILE) -> tuple[bool, str]:
    """Spawn ``scripts/run_live.py`` in the background."""
    if bot_is_running(pid_file):
        return False, "ربات از قبل در حال اجراست"

    # Fail fast before spawn when live gate is missing (avoids false "started" UI).
    if mode == "live":
        from chronoscalp.config import get_settings

        settings = get_settings()
        confirmed = bool(settings.secrets.live_trading_confirmed)
        # #region agent log
        _agent_dbg(
            "A",
            "process_control.start_bot",
            "live gate check",
            {"mode": mode, "confirmed": confirmed, "env_exists": (ROOT / ".env").exists()},
        )
        # #endregion
        if not confirmed:
            return (
                False,
                "حالت Live نیاز به CHRONOSCALP_CONFIRM_LIVE=yes در فایل .env دارد. "
                "در پنل کنترل، تأیید Live را فعال و ذخیره کنید، یا .env را دستی تنظیم کنید.",
            )

    script = ROOT / "scripts" / "run_live.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    # Ensure child sees the same live-gate value the panel just validated (not a stale OS env).
    if mode == "live":
        env["CHRONOSCALP_CONFIRM_LIVE"] = "yes"
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "bot_stdout.log"
    stdout = stdout_path.open("a", encoding="utf-8")

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
    # #region agent log
    _agent_dbg("C", "process_control.start_bot", "spawned", {"pid": proc.pid, "mode": mode})
    # #endregion

    # Detect immediate crash (e.g. broker connect fail after gate passes).
    time.sleep(1.5)
    exit_code = proc.poll()
    if exit_code is not None:
        pid_file.unlink(missing_ok=True)
        tail = ""
        try:
            lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-8:])
        except OSError:
            pass
        # #region agent log
        _agent_dbg(
            "A",
            "process_control.start_bot",
            "child exited immediately",
            {"pid": proc.pid, "exit_code": exit_code, "tail": tail[-500:]},
        )
        # #endregion
        return False, f"ربات فوراً متوقف شد (exit={exit_code}). آخرین لاگ:\n{tail}"

    return True, f"ربات با PID {proc.pid} در حالت {mode} شروع شد"


def stop_bot(pid_file: Path = PID_FILE) -> tuple[bool, str]:
    if not pid_file.exists():
        return False, "ربات در حال اجرا نیست"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return False, "فایل PID نامعتبر بود"

    # #region agent log
    _agent_dbg("D", "process_control.stop_bot", "stopping", {"pid": pid})
    # #endregion
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
