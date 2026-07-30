"""Lightweight FastAPI control plane for remote desktop/mobile clients.

Replaces slow Streamlit-over-WAN for day-to-day monitoring. Auth via
``CHRONOSCALP_API_TOKEN`` (Bearer). Bind to localhost or LAN as needed.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chronoscalp.config import get_settings
from chronoscalp.logging_setup import logger
from chronoscalp.orchestration.kill_switch import KillSwitch
from chronoscalp.orchestration.trade_journal import (
    load_journal_snapshot,
    write_daily_reset_marker,
)
from chronoscalp.saas import bot_is_running, start_bot, stop_bot
from chronoscalp.saas.broker_wizard import (
    KNOWN_STRATEGIES,
    apply_active_symbols,
    apply_daily_loss_limit_enabled,
    apply_enabled_strategies,
    apply_risk_preset,
    apply_trading_hours_mode,
    disable_live_confirm,
    enable_live_confirm,
)
from chronoscalp.saas.user_config import UserConfigStore

ROOT = Path(__file__).resolve().parents[3]
PID_FILE = Path("data/user/bot.pid")
STATE_DIR = Path("data/state")
load_dotenv(ROOT / ".env")


def _require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("CHRONOSCALP_API_TOKEN", "").strip()
    if not expected:
        # Dev convenience: allow open API only when token unset AND env=development.
        if os.getenv("CHRONOSCALP_ENV", "development").lower() == "development":
            return
        raise HTTPException(status_code=503, detail="CHRONOSCALP_API_TOKEN not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    got = authorization.split(" ", 1)[1].strip()
    if got != expected:
        raise HTTPException(status_code=403, detail="Invalid token")


class StartRequest(BaseModel):
    mode: str = Field(default="paper", pattern="^(paper|live)$")


class KillRequest(BaseModel):
    active: bool = True
    reason: str = "desktop"


class SymbolsRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class StrategiesRequest(BaseModel):
    strategies: list[str] = Field(default_factory=list)


class HoursRequest(BaseModel):
    mode: str = Field(default="london_ny")


class RiskPresetRequest(BaseModel):
    preset: float = Field(description="0.5 | 1.0 | 1.5 (capped at 1%)")


class DailyLossRequest(BaseModel):
    enabled: bool = True


class LiveConfirmRequest(BaseModel):
    enabled: bool = False


class UnlockDailyRequest(BaseModel):
    mode: str | None = Field(default=None, pattern="^(paper|live)$")
    restart: bool = True


def _detect_mode() -> str:
    user = UserConfigStore().config
    mode = str(user.broker.mode or "paper").lower()
    return mode if mode in {"paper", "live"} else "paper"


def _kill_switch() -> KillSwitch:
    settings = get_settings()
    state_dir = Path(settings.execution.get("state_dir", STATE_DIR))
    env_stop = os.getenv("CHRONOSCALP_STOP_TRADING", "no")
    return KillSwitch(state_dir=state_dir, env_stop=env_stop)


def _state_dir() -> Path:
    settings = get_settings()
    return Path(settings.execution.get("state_dir", STATE_DIR))


def _read_positions_snapshot(mode: str) -> dict[str, Any]:
    path = _state_dir() / f"broker_positions_{mode}.json"
    if not path.exists():
        return {"mode": mode, "updated_at": None, "account": {}, "positions": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mode": mode, "updated_at": None, "account": {}, "positions": []}
    if not isinstance(payload, dict):
        return {"mode": mode, "updated_at": None, "account": {}, "positions": []}
    return {
        "mode": str(payload.get("mode") or mode),
        "updated_at": payload.get("updated_at"),
        "account": payload.get("account") or {},
        "positions": list(payload.get("positions") or []),
    }


def create_app() -> FastAPI:
    app = FastAPI(title="ChronoScalp Control API", version="1.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "ts": datetime.now(tz=UTC).isoformat()}

    @app.get("/status", dependencies=[Depends(_require_token)])
    def status() -> dict[str, Any]:
        settings = get_settings()
        user = UserConfigStore().config
        running = bot_is_running(PID_FILE)
        pid = None
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            except ValueError:
                pid = None
        ks = _kill_switch()
        mode = _detect_mode()
        snap = load_journal_snapshot(_state_dir(), mode)
        positions = _read_positions_snapshot(mode)
        log_tail = _tail_log(40)
        return {
            "running": running,
            "pid": pid,
            "mode": mode,
            "broker": settings.execution.get("broker"),
            "symbols": settings.symbols,
            "strategies": settings.strategy.get("enabled_strategies"),
            "known_strategies": list(KNOWN_STRATEGIES),
            "trading_hours_mode": (settings.sessions or {}).get("trading_hours_mode"),
            "daily_loss_limit_enabled": bool(
                settings.risk.get("daily_loss_limit_enabled", True)
            ),
            "max_daily_loss_pct": float(settings.risk.get("max_daily_loss_pct", 3.0)),
            "risk_per_trade_pct": float(settings.risk.get("risk_per_trade_pct", 1.0)),
            "live_confirmed": settings.secrets.live_trading_confirmed,
            "kill_switch": ks.is_active(),
            "kill_reason": ks.reason(),
            "stats": snap.stats.to_dict(),
            "strategy_stats": [s.to_dict() for s in snap.strategy_stats],
            "open_count": len(snap.open_trades),
            "account": positions.get("account") or {},
            "positions_updated_at": positions.get("updated_at"),
            "log_tail": log_tail,
            "server_time": datetime.now(tz=UTC).isoformat(),
            "user_broker": {
                "provider": user.broker.provider,
                "mode": user.broker.mode,
            },
        }

    @app.get("/journal", dependencies=[Depends(_require_token)])
    def journal(mode: str | None = None, closed_limit: int = 200) -> dict[str, Any]:
        resolved = (mode or _detect_mode()).lower()
        if resolved not in {"paper", "live"}:
            raise HTTPException(status_code=400, detail="mode must be paper|live")
        limit = max(1, min(int(closed_limit), 2000))
        snap = load_journal_snapshot(_state_dir(), resolved)
        closed = list(reversed(snap.closed_trades))[:limit]
        return {
            "mode": resolved,
            "open_trades": [t.to_dict() for t in snap.open_trades],
            "closed_trades": [t.to_dict() for t in closed],
            "stats": snap.stats.to_dict(),
            "strategy_stats": [s.to_dict() for s in snap.strategy_stats],
        }

    @app.get("/positions", dependencies=[Depends(_require_token)])
    def positions(mode: str | None = None) -> dict[str, Any]:
        resolved = (mode or _detect_mode()).lower()
        if resolved not in {"paper", "live"}:
            raise HTTPException(status_code=400, detail="mode must be paper|live")
        snap = _read_positions_snapshot(resolved)
        journal = load_journal_snapshot(_state_dir(), resolved)
        by_ticket = {t.ticket: t for t in journal.open_trades}
        enriched = []
        for row in snap.get("positions") or []:
            item = dict(row)
            ticket = int(item.get("ticket") or 0)
            j = by_ticket.get(ticket)
            if j is not None:
                item.setdefault("strategy", j.strategy)
                item["journal_strategy"] = j.strategy
                item["reason"] = j.reason
            enriched.append(item)
        return {
            "mode": resolved,
            "updated_at": snap.get("updated_at"),
            "account": snap.get("account") or {},
            "positions": enriched,
            "journal_open": [t.to_dict() for t in journal.open_trades],
        }

    @app.get("/strategy-stats", dependencies=[Depends(_require_token)])
    def strategy_stats(mode: str | None = None) -> dict[str, Any]:
        resolved = (mode or _detect_mode()).lower()
        if resolved not in {"paper", "live"}:
            raise HTTPException(status_code=400, detail="mode must be paper|live")
        snap = load_journal_snapshot(_state_dir(), resolved)
        return {
            "mode": resolved,
            "stats": snap.stats.to_dict(),
            "by_strategy": [s.to_dict() for s in snap.strategy_stats],
        }

    @app.post("/bot/start", dependencies=[Depends(_require_token)])
    def bot_start(body: StartRequest) -> dict[str, Any]:
        ok, msg = start_bot(mode=body.mode, pid_file=PID_FILE)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"ok": True, "message": msg}

    @app.post("/bot/stop", dependencies=[Depends(_require_token)])
    def bot_stop() -> dict[str, Any]:
        ok, msg = stop_bot(pid_file=PID_FILE)
        return {"ok": ok, "message": msg}

    @app.post("/kill", dependencies=[Depends(_require_token)])
    def kill(body: KillRequest) -> dict[str, Any]:
        ks = _kill_switch()
        if body.active:
            ks.activate(reason=body.reason or "desktop")
        else:
            ks.deactivate()
        return {
            "ok": True,
            "active": ks.is_active(),
            "reason": ks.reason(),
        }

    @app.post("/settings/symbols", dependencies=[Depends(_require_token)])
    def set_symbols(body: SymbolsRequest) -> dict[str, Any]:
        try:
            saved = apply_active_symbols(body.symbols)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "symbols": saved}

    @app.post("/settings/strategies", dependencies=[Depends(_require_token)])
    def set_strategies(body: StrategiesRequest) -> dict[str, Any]:
        saved = apply_enabled_strategies(body.strategies)
        return {"ok": True, "strategies": saved, "known": list(KNOWN_STRATEGIES)}

    @app.post("/settings/hours", dependencies=[Depends(_require_token)])
    def set_hours(body: HoursRequest) -> dict[str, Any]:
        saved = apply_trading_hours_mode(body.mode)
        return {"ok": True, "mode": saved}

    @app.post("/settings/risk-preset", dependencies=[Depends(_require_token)])
    def set_risk_preset(body: RiskPresetRequest) -> dict[str, Any]:
        try:
            saved = apply_risk_preset(float(body.preset))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "risk_per_trade_pct": saved}

    @app.post("/settings/daily-loss", dependencies=[Depends(_require_token)])
    def set_daily_loss(body: DailyLossRequest) -> dict[str, Any]:
        enabled = apply_daily_loss_limit_enabled(body.enabled)
        return {"ok": True, "daily_loss_limit_enabled": enabled}

    @app.post("/settings/live-confirm", dependencies=[Depends(_require_token)])
    def set_live_confirm(body: LiveConfirmRequest) -> dict[str, Any]:
        if body.enabled:
            enable_live_confirm()
        else:
            disable_live_confirm()
        settings = get_settings()
        return {"ok": True, "live_confirmed": settings.secrets.live_trading_confirmed}

    @app.post("/daily-loss/unlock", dependencies=[Depends(_require_token)])
    def unlock_daily(body: UnlockDailyRequest) -> dict[str, Any]:
        mode = (body.mode or _detect_mode()).lower()
        if mode not in {"paper", "live"}:
            raise HTTPException(status_code=400, detail="mode must be paper|live")
        reset_at = write_daily_reset_marker(_state_dir(), mode)
        other = "paper" if mode == "live" else "live"
        write_daily_reset_marker(_state_dir(), other)
        restarted = False
        message = f"Daily loss tracker unlocked for {mode} at {reset_at.isoformat()}"
        if body.restart and bot_is_running(PID_FILE):
            stop_bot(pid_file=PID_FILE)
            ok, msg = start_bot(mode=mode, pid_file=PID_FILE)
            restarted = ok
            message = f"{message}; restart={'ok' if ok else msg}"
        return {
            "ok": True,
            "mode": mode,
            "reset_at": reset_at.isoformat(),
            "restarted": restarted,
            "message": message,
        }

    @app.get("/logs", dependencies=[Depends(_require_token)])
    def logs(lines: int = 80) -> dict[str, Any]:
        return {"lines": _tail_log(max(1, min(lines, 500)))}

    logger.info("ChronoScalp Control API ready")
    return app


def _tail_log(n: int) -> list[str]:
    logs = sorted((ROOT / "logs").glob("chronoscalp_*.log"))
    if not logs:
        return []
    path = logs[-1]
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return text[-n:]


app = create_app()
