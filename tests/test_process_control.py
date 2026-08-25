"""Unit tests for Telegram/panel process start-stop (no live spawn)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chronoscalp.saas import process_control as pc


def test_resolve_pid_file_relative_uses_repo_root() -> None:
    resolved = pc.resolve_pid_file(Path("data/user/bot.pid"))
    assert resolved.is_absolute()
    assert resolved == (pc.ROOT / "data" / "user" / "bot.pid").resolve()


def test_resolve_pid_file_absolute_unchanged(tmp_path: Path) -> None:
    custom = tmp_path / "bot.pid"
    assert pc.resolve_pid_file(custom) == custom


def test_bot_is_running_false_without_pid_or_live_procs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "_list_run_live_pids", lambda: [])
    pid_file = tmp_path / "bot.pid"
    assert pc.bot_is_running(pid_file) is False


def test_bot_is_running_true_when_run_live_exists_without_pid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "_list_run_live_pids", lambda: [4242])
    monkeypatch.setattr(pc, "_pid_alive", lambda _pid: True)
    assert pc.bot_is_running(tmp_path / "bot.pid") is True


def test_stop_bot_kills_orphaned_run_live_and_writes_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    live = [8801]

    def fake_list() -> list[int]:
        return list(live)

    def fake_kill(pid: int) -> None:
        killed.append(pid)
        if pid in live:
            live.remove(pid)

    monkeypatch.setattr(pc, "_list_run_live_pids", fake_list)
    monkeypatch.setattr(pc, "_pid_alive", lambda pid: pid in live)
    monkeypatch.setattr(pc, "_kill_pid_tree", fake_kill)

    pid_file = tmp_path / "bot.pid"
    ok, msg = pc.stop_bot(pid_file)
    assert ok is True
    assert killed == [8801]
    assert "8801" in msg
    assert pc.stop_marker_path(pid_file).exists()
    assert not pid_file.exists()


def test_stop_bot_when_nothing_running_is_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "_list_run_live_pids", lambda: [])
    monkeypatch.setattr(pc, "_pid_alive", lambda _pid: False)
    pid_file = tmp_path / "bot.pid"
    ok, msg = pc.stop_bot(pid_file)
    assert ok is True
    assert "متوقف" in msg
    assert pc.stop_marker_path(pid_file).exists()


def test_start_bot_refuses_when_run_live_still_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "_list_run_live_pids", lambda: [99])
    monkeypatch.setattr(pc, "_pid_alive", lambda _pid: True)
    ok, msg = pc.start_bot("paper", pid_file=tmp_path / "bot.pid")
    assert ok is False
    assert "از قبل در حال اجراست" in msg


def test_start_bot_clears_stop_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProc:
        pid = 3210

        def poll(self) -> int | None:
            return None

    pid_file = tmp_path / "bot.pid"
    marker = pc.stop_marker_path(pid_file)
    marker.write_text("stopped_via_control\n", encoding="utf-8")

    monkeypatch.setattr(pc, "_list_run_live_pids", lambda: [])
    monkeypatch.setattr(pc, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(pc, "_rotate_bot_stdout_if_needed", lambda _p: None)
    monkeypatch.setattr(pc, "_python_executable", lambda: "python")
    monkeypatch.setattr(pc.subprocess, "Popen", lambda *_a, **_k: _FakeProc())
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)

    stdout = tmp_path / "bot_stdout.log"
    stdout.write_text("", encoding="utf-8")
    monkeypatch.setattr(pc, "ROOT", tmp_path)

    ok, msg = pc.start_bot("paper", pid_file=pid_file)
    assert ok is True
    assert "3210" in msg
    assert pid_file.read_text(encoding="utf-8").strip() == "3210"
    assert not marker.exists()


def test_ensure_mt5_terminal_ok_when_private_bytes_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc.sys, "platform", "win32")
    monkeypatch.setattr(pc, "terminal64_private_mb", lambda: 49.0)
    ok, msg = pc.ensure_mt5_terminal()
    assert ok is True
    assert "terminal64_ok" in msg


def test_terminal64_health_reads_private_bytes_not_working_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows trims the working set of an idle terminal, so measuring it made a
    healthy MT5 look hollow and the watchdog recycled it every few minutes."""
    seen: list[str] = []

    def fake_run(cmd, **_kwargs):  # noqa: ANN001
        seen.append(" ".join(cmd))

        class _R:
            returncode = 0
            stdout = str(49 * 1024 * 1024)

        return _R()

    monkeypatch.setattr(pc.sys, "platform", "win32")
    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    assert pc.terminal64_private_mb() == pytest.approx(49.0)
    assert "PrivateMemorySize64" in seen[0]
    assert "WorkingSet64" not in seen[0]


def test_ensure_mt5_terminal_recycles_hollow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "terminal64.exe"
    exe.write_bytes(b"mz")
    calls: list[list[str]] = []
    priv_values = [7.0, 7.0, 95.0]

    def fake_priv() -> float | None:
        return priv_values.pop(0) if priv_values else 95.0

    def fake_run(cmd, **_kwargs):  # noqa: ANN001
        calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(pc.sys, "platform", "win32")
    monkeypatch.setattr(pc, "terminal64_private_mb", fake_priv)
    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)
    ok, msg = pc.ensure_mt5_terminal(terminal_path=str(exe), wait_seconds=10)
    assert ok is True
    assert "terminal64_recycled" in msg
    assert any(cmd[:2] == ["taskkill", "/IM"] for cmd in calls)
    assert any(cmd[:2] == ["schtasks", "/Run"] for cmd in calls)


def test_start_bot_live_continues_if_mt5_hollow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeProc:
        pid = 4400

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(pc, "_list_run_live_pids", lambda: [])
    monkeypatch.setattr(pc, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(pc, "_rotate_bot_stdout_if_needed", lambda _p: None)
    monkeypatch.setattr(pc, "_python_executable", lambda: "python")
    monkeypatch.setattr(pc.subprocess, "Popen", lambda *_a, **_k: _FakeProc())
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        pc, "ensure_mt5_terminal", lambda **_k: (False, "terminal64_hollow priv_mb=7.0")
    )

    class _Secrets:
        live_trading_confirmed = True

    class _Settings:
        secrets = _Secrets()

    monkeypatch.setattr("chronoscalp.config.get_settings", lambda: _Settings())
    stdout = tmp_path / "bot_stdout.log"
    stdout.write_text("", encoding="utf-8")
    monkeypatch.setattr(pc, "ROOT", tmp_path)
    ok, msg = pc.start_bot("live", pid_file=tmp_path / "bot.pid")
    assert ok is True
    assert "4400" in msg
