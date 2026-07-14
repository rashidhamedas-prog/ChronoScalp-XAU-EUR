from __future__ import annotations

from pathlib import Path

from chronoscalp.orchestration.kill_switch import STOP_FILE_NAME, KillSwitch


def test_kill_switch_env_active():
    ks = KillSwitch(state_dir="/tmp", env_stop="yes")
    assert ks.is_active() is True
    assert ks.reason() == "CHRONOSCALP_STOP_TRADING=yes"


def test_kill_switch_file_active(tmp_path: Path):
    ks = KillSwitch(state_dir=tmp_path, env_stop="no")
    assert ks.is_active() is False
    (tmp_path / STOP_FILE_NAME).touch()
    assert ks.is_active() is True
    assert "STOP_TRADING" in (ks.reason() or "")


def test_kill_switch_logs_transition(tmp_path: Path):
    ks = KillSwitch(state_dir=tmp_path, env_stop="no")
    assert ks.check_and_log() is False
    (tmp_path / STOP_FILE_NAME).touch()
    assert ks.check_and_log() is True
    (tmp_path / STOP_FILE_NAME).unlink()
    assert ks.check_and_log() is False
