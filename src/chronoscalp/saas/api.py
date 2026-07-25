"""Lightweight FastAPI control plane for remote desktop/mobile clients.

Replaces slow Streamlit-over-WAN for day-to-day monitoring. Auth via
``CHRONOSCALP_API_TOKEN`` (Bearer). Bind to localhost or LAN as needed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chronoscalp.config import get_settings
from chronoscalp.logging_setup import logger
from chronoscalp.saas import bot_is_running, start_bot, stop_bot
from chronoscalp.saas.user_config import UserConfigStore

ROOT = Path(__file__).resolve().parents[3]
PID_FILE = Path("data/user/bot.pid")


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


def create_app() -> FastAPI:
    app = FastAPI(title="ChronoScalp Control API", version="1.0.0")
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
        log_tail = _tail_log(40)
        return {
            "running": running,
            "pid": pid,
            "mode": user.broker.mode,
            "broker": settings.execution.get("broker"),
            "symbols": settings.symbols,
            "strategies": settings.strategy.get("enabled_strategies"),
            "live_confirmed": settings.secrets.live_trading_confirmed,
            "log_tail": log_tail,
            "server_time": datetime.now(tz=UTC).isoformat(),
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
