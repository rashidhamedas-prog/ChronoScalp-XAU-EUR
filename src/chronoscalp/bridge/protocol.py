"""Python ↔ MT5 bridge protocol (Phase 3 hybrid architecture).

Transport: TCP ``127.0.0.1`` + shared token (named pipe optional later).
EA owns SL/TP/trail for open positions but never opens without Python.
Heartbeat loss >10s → ``BRIDGE_DEGRADED``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18999
HEARTBEAT_DEGRADED_SECONDS = 10.0


class BridgeMsgType(StrEnum):
    OPEN = "OPEN"
    MODIFY = "MODIFY"
    CLOSE = "CLOSE"
    CANCEL = "CANCEL"
    ACK = "ACK"
    FILL = "FILL"
    REJECT = "REJECT"
    POSITION_UPDATE = "POSITION_UPDATE"
    TICK = "TICK"
    HEARTBEAT = "HEARTBEAT"
    BRIDGE_DEGRADED = "BRIDGE_DEGRADED"


def make_envelope(
    msg_type: BridgeMsgType,
    *,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Build a versioned JSON bridge message."""
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": str(msg_type),
        "payload": dict(payload),
    }
    if idempotency_key:
        body["idempotency_key"] = str(idempotency_key)
    if token:
        body["token"] = str(token)
    return body


def validate_envelope(message: dict[str, Any], *, expected_token: str | None = None) -> None:
    """Fail-closed validation of an inbound bridge message."""
    if not isinstance(message, dict):
        raise ValueError("bridge message must be an object")
    if int(message.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError("unsupported bridge schema_version")
    if "type" not in message or "payload" not in message:
        raise ValueError("bridge message missing type/payload")
    if expected_token and str(message.get("token", "")) != str(expected_token):
        raise PermissionError("bridge token mismatch")
