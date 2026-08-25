"""Start/stop the trading bot as a managed subprocess (Windows/Linux)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from chronoscalp.logging_setup import agent_debug_log, logger

ROOT = Path(__file__).resolve().parents[3]
PID_FILE = ROOT / "data" / "user" / "bot.pid"
_BOT_STDOUT_MAX_BYTES = 50 * 1024 * 1024  # 50 MiB — rotate before VPS disk fills
_RUN_LIVE_MARKER = "run_live.py"
DEFAULT_MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
# Private bytes, not working set: Windows trims the working set of an idle
# background terminal to ~20–30 MiB, which made a healthy terminal look
# hollow and got it killed every few minutes. Commit charge is not trimmed —
# a loaded terminal stays above 40 MiB, a session-0 zombie under 20 MiB.
HOLLOW_MT5_PRIVATE_MB = 20.0


def terminal64_private_mb() -> float | None:
    """Return ``terminal64`` private-bytes MiB, or ``None`` if it is not running."""
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process -Name terminal64 -ErrorAction SilentlyContinue "
                "| Measure-Object PrivateMemorySize64 -Maximum).Maximum",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw)) / (1024 * 1024)
    except ValueError:
        return None


def ensure_mt5_terminal(
    *,
    min_private_mb: float = HOLLOW_MT5_PRIVATE_MB,
    terminal_path: str | None = None,
    wait_seconds: float = 45.0,
) -> tuple[bool, str]:
    """Kill a hollow/missing ``terminal64`` and start it; wait until memory looks loaded.

    A healthy logged-in terminal is typically well above ``min_private_mb``.
    Session-0 zombies sit around 6–8 MiB and cause IPC timeout ``-10005``.
    """
    if sys.platform != "win32":
        return True, "not-windows"
    priv = terminal64_private_mb()
    if priv is not None and priv >= min_private_mb:
        return True, f"terminal64_ok priv_mb={priv:.1f}"

    path = terminal_path or os.environ.get("MT5_TERMINAL_PATH") or DEFAULT_MT5_TERMINAL_PATH
    logger.warning(
        "MT5 terminal hollow or missing (priv_mb={}); recycling {}",
        None if priv is None else round(priv, 1),
        path,
    )
    subprocess.run(
        ["taskkill", "/IM", "terminal64.exe", "/F"],
        check=False,
        capture_output=True,
        timeout=20,
    )
    if not Path(path).is_file():
        return False, f"mt5_missing:{path}"
    quoted = f'"{path}"'
    subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            "ChronoScalpMT5",
            "/TR",
            quoted,
            "/SC",
            "ONSTART",
            "/F",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    run = subprocess.run(
        ["schtasks", "/Run", "/TN", "ChronoScalpMT5"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if run.returncode != 0:
        try:
            subprocess.Popen(
                [path],
                cwd=str(Path(path).parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except OSError as exc:
            return False, f"mt5_start_failed:{exc}"

    deadline = time.time() + max(5.0, wait_seconds)
    last_priv = terminal64_private_mb()
    while time.time() < deadline:
        time.sleep(5)
        last_priv = terminal64_private_mb()
        if last_priv is not None and last_priv >= min_private_mb:
            logger.info("MT5 terminal recycled priv_mb={:.1f}", last_priv)
            return True, f"terminal64_recycled priv_mb={last_priv:.1f}"
    detail = "none" if last_priv is None else f"{last_priv:.1f}"
    return False, f"terminal64_hollow priv_mb={detail}"


def _python_executable() -> str:
    """Prefer project venv so panel and bot share one interpreter."""
    win = ROOT / ".venv" / "Scripts" / "python.exe"
    if win.exists():
        return str(win)
    unix = ROOT / ".venv" / "bin" / "python"
    if unix.exists():
        return str(unix)
    return sys.executable


def resolve_pid_file(pid_file: Path | None = None) -> Path:
    """Return an absolute pid-file path (relative paths resolve under ``ROOT``)."""
    path = PID_FILE if pid_file is None else Path(pid_file)
    if not path.is_absolute():
        return (ROOT / path).resolve()
    return path


def stop_marker_path(pid_file: Path | None = None) -> Path:
    """Sidecar file that tells watchdogs not to auto-restart after an operator stop."""
    return resolve_pid_file(pid_file).with_name("bot.stopped")


def _write_stop_marker(pid_file: Path) -> None:
    marker = stop_marker_path(pid_file)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("stopped_via_control\n", encoding="utf-8")


def _clear_stop_marker(pid_file: Path) -> None:
    stop_marker_path(pid_file).unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    """Return True when ``pid`` still exists (best-effort, cross-platform)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) can raise SystemError on some Windows/Python builds.
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        except Exception:  # noqa: BLE001
            return False
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _list_run_live_pids() -> list[int]:
    """PIDs whose command line is ``scripts/run_live.py`` (not the Telegram bot)."""
    me = os.getpid()
    parent = os.getppid()
    found: list[int] = []
    try:
        if sys.platform == "win32":
            cmd = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -and "
                "($_.CommandLine -match 'run_live\\.py') -and "
                "($_.CommandLine -notmatch 'telegram_control_bot') } | "
                "ForEach-Object { $_.ProcessId }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            for line in (result.stdout or "").splitlines():
                token = line.strip()
                if token.isdigit():
                    found.append(int(token))
        else:
            result = subprocess.run(
                ["pgrep", "-f", _RUN_LIVE_MARKER],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            for line in (result.stdout or "").splitlines():
                token = line.strip()
                if token.isdigit():
                    found.append(int(token))
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not list run_live processes: {}", exc)
        return []
    return [pid for pid in found if pid not in {me, parent}]


def _managed_pids(pid_file: Path) -> set[int]:
    """Union of pid-file PID (if alive) and any live ``run_live.py`` processes."""
    pids: set[int] = set(_list_run_live_pids())
    if pid_file.exists():
        try:
            recorded = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            recorded = 0
        if recorded and _pid_alive(recorded):
            pids.add(recorded)
    return pids


def _kill_pid_tree(pid: int) -> None:
    """Force-kill ``pid`` and its children. Best-effort; does not raise."""
    if pid <= 0 or pid == os.getpid():
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=20,
            )
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                return
            time.sleep(0.3)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not kill pid={}: {}", pid, exc)


def bot_is_running(pid_file: Path = PID_FILE) -> bool:
    """True when the managed pid or any ``run_live.py`` process is still alive."""
    path = resolve_pid_file(pid_file)
    if _managed_pids(path):
        return True
    if path.exists():
        path.unlink(missing_ok=True)
    return False


def _rotate_bot_stdout_if_needed(stdout_path: Path) -> None:
    """Rotate ``bot_stdout.log`` when oversized (no built-in rotation otherwise)."""
    try:
        if not stdout_path.exists() or stdout_path.stat().st_size < _BOT_STDOUT_MAX_BYTES:
            return
        backup = stdout_path.with_suffix(".log.1")
        backup.unlink(missing_ok=True)
        stdout_path.rename(backup)
        logger.info("Rotated oversized bot_stdout.log -> {}", backup.name)
    except OSError as exc:
        logger.warning("Could not rotate bot_stdout.log: {}", exc)


def start_bot(mode: str = "paper", pid_file: Path = PID_FILE) -> tuple[bool, str]:
    """Spawn ``scripts/run_live.py`` in the background."""
    pid_file = resolve_pid_file(pid_file)
    already = bot_is_running(pid_file)
    # #region agent log
    agent_debug_log(
        location="process_control.py:start_bot",
        message="start_bot requested",
        data={"mode": mode, "already_running": already},
        hypothesis_id="B",
    )
    # #endregion
    if already:
        return False, "ربات از قبل در حال اجراست"

    # Fail fast before spawn when live gate is missing (avoids false "started" UI).
    if mode == "live":
        from chronoscalp.config import get_settings

        settings = get_settings()
        if not settings.secrets.live_trading_confirmed:
            return (
                False,
                "حالت Live نیاز به CHRONOSCALP_CONFIRM_LIVE=yes در فایل .env دارد. "
                "در پنل کنترل، تأیید Live را فعال و ذخیره کنید، یا .env را دستی تنظیم کنید.",
            )
        mt5_ok, mt5_msg = ensure_mt5_terminal(wait_seconds=15.0)
        if not mt5_ok:
            logger.warning(
                "Starting live bot while MT5 is not loaded ({}); "
                "initialize() will try to launch/login the terminal",
                mt5_msg,
            )

    script = ROOT / "scripts" / "run_live.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONUNBUFFERED"] = "1"
    # Ensure child sees the same live-gate value the panel just validated (not a stale OS env).
    if mode == "live":
        env["CHRONOSCALP_CONFIRM_LIVE"] = "yes"
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "bot_stdout.log"
    _rotate_bot_stdout_if_needed(stdout_path)
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
    _clear_stop_marker(pid_file)
    logger.info("Started bot pid={} mode={}", proc.pid, mode)

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
        agent_debug_log(
            location="process_control.py:start_bot",
            message="start_bot early exit",
            data={"mode": mode, "pid": proc.pid, "exit_code": exit_code},
            hypothesis_id="B",
        )
        # #endregion
        return False, f"ربات فوراً متوقف شد (exit={exit_code}). آخرین لاگ:\n{tail}"

    # #region agent log
    agent_debug_log(
        location="process_control.py:start_bot",
        message="start_bot spawned",
        data={"mode": mode, "pid": proc.pid},
        hypothesis_id="B",
    )
    # #endregion
    return True, f"ربات با PID {proc.pid} در حالت {mode} شروع شد"


def stop_bot(pid_file: Path = PID_FILE) -> tuple[bool, str]:
    """Stop every managed ``run_live.py`` process, not just the pid-file PID.

    Windows venv launchers often leave a child ``python.exe run_live.py`` that
    outlives the recorded PID. Telegram Stop must kill that tree too, and write
    ``bot.stopped`` so scheduled watchdogs do not immediately revive it.
    """
    pid_file = resolve_pid_file(pid_file)
    pids = _managed_pids(pid_file)
    if not pids:
        pid_file.unlink(missing_ok=True)
        _write_stop_marker(pid_file)
        return True, "ربات از قبل متوقف بود"

    for pid in sorted(pids):
        _kill_pid_tree(pid)

    deadline = time.time() + 3.0
    leftover: set[int] = set()
    while time.time() < deadline:
        leftover = _managed_pids(pid_file)
        if not leftover:
            break
        for pid in leftover:
            _kill_pid_tree(pid)
        time.sleep(0.25)

    pid_file.unlink(missing_ok=True)
    _write_stop_marker(pid_file)
    if leftover:
        logger.warning("Stop incomplete; leftover pids={}", leftover)
        return False, f"توقف ناقص؛ هنوز در حال اجرا: {sorted(leftover)}"

    logger.info("Stopped bot pids={}", sorted(pids))
    return True, f"ربات متوقف شد (PID {', '.join(str(p) for p in sorted(pids))})"


def bot_pid(pid_file: Path = PID_FILE) -> int | None:
    """Return a live managed PID (pid file first, else any ``run_live.py``)."""
    path = resolve_pid_file(pid_file)
    if path.exists():
        try:
            recorded = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            recorded = 0
        if recorded and _pid_alive(recorded):
            return recorded
    live = _list_run_live_pids()
    return live[0] if live else None


def _tail_file_lines(path: Path, n: int) -> list[str]:
    """Read the last ``n`` lines without loading the whole file."""
    n = max(1, n)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            data = b""
            block = 8192
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size)
                size -= step
                handle.seek(size)
                data = handle.read(step) + data
                if len(data) > 512 * 1024:
                    break
            text = data.decode("utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-n:]


def tail_logs(n: int = 40, log_dir: Path | None = None) -> list[str]:
    """Return the last ``n`` lines from the newest chronoscalp / bot_stdout log."""
    directory = Path(log_dir) if log_dir is not None else ROOT / "logs"
    candidates = list(directory.glob("chronoscalp_*.log"))
    stdout_path = directory / "bot_stdout.log"
    if stdout_path.exists():
        candidates.append(stdout_path)
    if not candidates:
        return []
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    return _tail_file_lines(path, n)
