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
