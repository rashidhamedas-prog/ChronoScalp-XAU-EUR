"""MT5 bridge protocol package (Phase 3)."""

from __future__ import annotations

from chronoscalp.bridge.protocol import (
    HEARTBEAT_DEGRADED_SECONDS,
    SCHEMA_VERSION,
    BridgeMsgType,
    make_envelope,
    validate_envelope,
)

__all__ = [
    "HEARTBEAT_DEGRADED_SECONDS",
    "SCHEMA_VERSION",
    "BridgeMsgType",
    "make_envelope",
    "validate_envelope",
]
