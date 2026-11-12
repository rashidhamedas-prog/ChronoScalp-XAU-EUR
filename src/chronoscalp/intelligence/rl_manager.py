"""Phase 4 RL position manager — shadow by default, kill-path to rules.

Does **not** choose direction/entries. Actions only adjust management within
risk ceilings. Stable-Baselines3 is optional; without it the manager stays in
``rule_based`` mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from chronoscalp.logging_setup import logger


class RlAction(StrEnum):
    HOLD = "hold"
    PARTIAL_TP = "partial_tp"
    TRAIL_TIGHTER = "trail_tighter"
    BREAKEVEN = "breakeven"
    REDUCE_SIZE = "reduce_size"


@dataclass(frozen=True)
class RlDecision:
    action: RlAction
    size_multiplier: float
    source: str  # rl | rule_based | kill_revert
    reason: str


class RlPositionManager:
    """Shadow-capable RL wrapper with instant revert on anomaly."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        shadow: bool = True,
        max_size_multiplier: float = 1.0,
    ) -> None:
        if float(max_size_multiplier) > 1.0:
            raise ValueError("RL size multiplier cannot exceed 1.0 (risk ceiling)")
        self.enabled = bool(enabled)
        self.shadow = bool(shadow)
        self.max_size_multiplier = float(max_size_multiplier)
        self._policy: Any = None
        self._killed = False
        self._anomaly_count = 0

    @property
    def is_live_effective(self) -> bool:
        return self.enabled and not self.shadow and not self._killed and self._policy is not None

    def load_policy(self, path: str) -> None:
        """Load an optional SB3 policy; missing file keeps rule-based mode."""
        try:
            from pathlib import Path

            if not Path(path).exists():
                logger.warning("RL policy missing at {} — rule-based only", path)
                self._policy = None
                return
            # Optional heavy dependency — import only when a file exists.
            from stable_baselines3 import PPO  # type: ignore

            self._policy = PPO.load(path)
            logger.info("Loaded RL policy from {}", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RL policy load failed ({}): staying rule-based", exc)
            self._policy = None

    def decide(
        self,
        *,
        regime_label: str,
        r_multiple: float,
        spread_pips: float,
        bars_in_trade: int,
    ) -> RlDecision:
        """Return a management decision; shadow mode still computes but flags source."""
        if self._killed or not self.enabled or self._policy is None:
            return self._rule_based(r_multiple=r_multiple)

        try:
            action = self._infer_action(
                regime_label=regime_label,
                r_multiple=r_multiple,
                spread_pips=spread_pips,
                bars_in_trade=bars_in_trade,
            )
            if self._is_anomalous(action, spread_pips=spread_pips):
                self.trip_kill("anomalous_action")
                return RlDecision(
                    action=RlAction.HOLD,
                    size_multiplier=1.0,
                    source="kill_revert",
                    reason="anomaly",
                )
            source = "rl_shadow" if self.shadow else "rl"
            return RlDecision(
                action=action,
                size_multiplier=self.max_size_multiplier,
                source=source,
                reason="policy",
            )
        except Exception as exc:  # noqa: BLE001
            self.trip_kill(f"infer_error:{exc}")
            return RlDecision(
                action=RlAction.HOLD,
                size_multiplier=1.0,
                source="kill_revert",
                reason=str(exc),
            )

    def trip_kill(self, reason: str) -> None:
        self._killed = True
        self._anomaly_count += 1
        logger.error("RL kill-path engaged: {} — reverted to rule-based", reason)

    def reset_kill(self) -> None:
        self._killed = False

    def _rule_based(self, *, r_multiple: float) -> RlDecision:
        if r_multiple >= 1.0:
            return RlDecision(
                action=RlAction.BREAKEVEN,
                size_multiplier=1.0,
                source="rule_based",
                reason="r>=1",
            )
        return RlDecision(
            action=RlAction.HOLD,
            size_multiplier=1.0,
            source="rule_based",
            reason="default",
        )

    def _infer_action(
        self,
        *,
        regime_label: str,
        r_multiple: float,
        spread_pips: float,
        bars_in_trade: int,
    ) -> RlAction:
        # Without a real SB3 forward pass wired to observation space, use a
        # deterministic stub so shadow mode is testable offline.
        if self._policy is None:
            return RlAction.HOLD
        if spread_pips > 50:
            return RlAction.HOLD
        if r_multiple >= 1.5:
            return RlAction.TRAIL_TIGHTER
        if r_multiple >= 1.0:
            return RlAction.BREAKEVEN
        if bars_in_trade > 50 and regime_label == "chop":
            return RlAction.PARTIAL_TP
        return RlAction.HOLD

    def _is_anomalous(self, action: RlAction, *, spread_pips: float) -> bool:
        if action == RlAction.REDUCE_SIZE and self.max_size_multiplier > 1.0:
            return True
        return spread_pips < 0
