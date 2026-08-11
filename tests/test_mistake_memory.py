"""Unit tests for deterministic MistakeMemory (learn-from-mistakes)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from chronoscalp.risk.mistake_memory import (
    MistakeMemory,
    MistakeMemoryConfig,
    setup_reason_bucket,
)


def _memory(
    tmp_path: Path,
    *,
    max_repeats: int = 1,
    match_session: bool = True,
    persist: bool = True,
    cooldown_minutes: int = 240,
) -> MistakeMemory:
    cfg = MistakeMemoryConfig(
        enabled=True,
        cooldown_minutes=cooldown_minutes,
        max_repeats=max_repeats,
        min_loss_r=0.0,
        match_session=match_session,
        match_exit_type=False,
        persist=persist,
    )
    return MistakeMemory(config=cfg, path=tmp_path / "lessons_paper.json", mode="paper")


def test_fingerprint_stability(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    a = mem.fingerprint(
        symbol="XAUUSD_o",
        strategy="ultra_scalp",
        session="london",
        direction="BUY",
        reason="ultra_scalp,ema_pullback",
    )
    b = mem.fingerprint(
        symbol="xauusd_o",
        strategy="ultra_scalp",
        session="London",
        direction="buy",
        reason="ultra_scalp, other_noise",
    )
    assert a == "XAUUSD|ultra_scalp|london|buy|ultra_scalp"
    assert a == b
    assert setup_reason_bucket("SMC Confluence,extra") == "smc_confluence"

    mem_any = _memory(tmp_path, match_session=False)
    fp_any = mem_any.fingerprint(
        symbol="EURUSD",
        strategy="delta",
        session="ny",
        direction="sell",
        reason="delta,breakout",
    )
    assert fp_any == "EURUSD|delta|any|sell|delta"


def test_wins_and_incomplete_create_no_lesson(tmp_path: Path) -> None:
    mem = _memory(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

    assert (
        mem.record_loss(
            symbol="XAUUSD",
            strategy="ultra_scalp",
            session="london",
            direction="buy",
            reason="ultra_scalp,pullback",
            pnl=12.0,
            r_multiple=1.2,
            at=now,
        )
        is None
    )
    assert (
        mem.record_loss(
            symbol="XAUUSD",
            strategy="ultra_scalp",
            session="london",
            direction="buy",
            reason="",
            pnl=-10.0,
            r_multiple=-1.0,
            at=now,
        )
        is None
    )
    assert (
        mem.record_loss(
            symbol="",
            strategy="ultra_scalp",
            session="london",
            direction="buy",
            reason="ultra_scalp",
            pnl=-10.0,
            r_multiple=-1.0,
            at=now,
        )
        is None
    )
    assert mem.lessons == []


def test_block_within_cooldown_after_one_loss(tmp_path: Path) -> None:
    mem = _memory(tmp_path, max_repeats=1, cooldown_minutes=240)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    fp = mem.fingerprint(
        symbol="XAUUSD",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
    )
    assert not mem.blocks(fp, now)
    lesson = mem.record_loss(
        symbol="XAUUSD",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
        pnl=-25.0,
        r_multiple=-1.0,
        at=now,
    )
    assert lesson is not None
    assert mem.blocks(fp, now + timedelta(minutes=30))


def test_allow_after_cooldown_expires(tmp_path: Path) -> None:
    mem = _memory(tmp_path, max_repeats=1, cooldown_minutes=240)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    fp = mem.fingerprint(
        symbol="XAUUSD",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
    )
    mem.record_loss(
        symbol="XAUUSD",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
        pnl=-25.0,
        r_multiple=-1.0,
        at=now,
    )
    assert mem.blocks(fp, now + timedelta(minutes=239))
    assert not mem.blocks(fp, now + timedelta(minutes=241))


def test_max_repeats_two_requires_two_losses(tmp_path: Path) -> None:
    mem = _memory(tmp_path, max_repeats=2, cooldown_minutes=240)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    kwargs = dict(
        symbol="EURUSD",
        strategy="delta",
        session="ny",
        direction="sell",
        reason="delta,sweep",
        pnl=-8.0,
        r_multiple=-0.8,
    )
    fp = mem.fingerprint(
        symbol=kwargs["symbol"],
        strategy=kwargs["strategy"],
        session=kwargs["session"],
        direction=kwargs["direction"],
        reason=kwargs["reason"],
    )
    mem.record_loss(**kwargs, at=now)
    assert not mem.blocks(fp, now + timedelta(minutes=5))
    mem.record_loss(**kwargs, at=now + timedelta(minutes=10))
    assert mem.blocks(fp, now + timedelta(minutes=15))


def test_session_match_isolation(tmp_path: Path) -> None:
    mem = _memory(tmp_path, match_session=True, max_repeats=1)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    mem.record_loss(
        symbol="XAUUSD",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
        pnl=-20.0,
        r_multiple=-1.0,
        at=now,
    )
    fp_london = mem.fingerprint(
        symbol="XAUUSD",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
    )
    fp_ny = mem.fingerprint(
        symbol="XAUUSD",
        strategy="ultra_scalp",
        session="ny",
        direction="buy",
        reason="ultra_scalp,pullback",
    )
    assert mem.blocks(fp_london, now)
    assert not mem.blocks(fp_ny, now)


def test_persistence_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "lessons_paper.json"
    cfg = MistakeMemoryConfig(persist=True, max_repeats=1, cooldown_minutes=240)
    mem = MistakeMemory(config=cfg, path=path, mode="paper")
    now = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)
    mem.record_loss(
        symbol="XAUUSD_o",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
        pnl=-15.5,
        r_multiple=-1.0,
        at=now,
    )
    assert path.exists()

    reloaded = MistakeMemory(config=cfg, path=path, mode="paper")
    assert len(reloaded.lessons) == 1
    fp = reloaded.fingerprint(
        symbol="XAUUSD_o",
        strategy="ultra_scalp",
        session="london",
        direction="buy",
        reason="ultra_scalp,pullback",
    )
    assert reloaded.lessons[0].fingerprint == fp
    assert reloaded.blocks(fp, now + timedelta(minutes=10))
