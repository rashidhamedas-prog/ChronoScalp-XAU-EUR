"""Validation for ``config/runtime_overrides.yaml`` Demo/Shadow overlays.

Hard ceilings from CLAUDE.md are enforced here so a bad override cannot
weaken risk/R:R. Unknown forward-looking keys are allowed (ignored by older
code paths) but typed when present.
"""

from __future__ import annotations

from typing import Any

from chronoscalp.risk.position_sizing import HARD_MAX_RISK_PCT

HARD_MIN_GROSS_RR = 1.5
KNOWN_STRATEGIES = frozenset(
    {"smc_confluence", "liquidity_volume", "ultra_scalp", "news_straddle", "delta"}
)
KNOWN_BROKERS = frozenset({"paper", "mt5", "oanda"})
KNOWN_HOURS = frozenset({"london_ny", "always_on_24h"})


class RuntimeOverridesValidationError(ValueError):
    """Raised when runtime overrides violate schema or hard invariants."""


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeOverridesValidationError(f"{path} must be a mapping")
    return value


def _as_float(value: Any, path: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeOverridesValidationError(f"{path} must be a number") from exc


def _as_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeOverridesValidationError(f"{path} must be a boolean")
    return value


def _as_int(value: Any, path: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeOverridesValidationError(f"{path} must be an integer") from exc


def validate_runtime_overrides(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and return a normalized copy of runtime overrides.

    Does not strip Telegram capabilities. Rejects overlays that weaken hard
    ceilings (risk > 1%, gross R:R < 1.5).
    """
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise RuntimeOverridesValidationError("runtime overrides root must be a mapping")

    out = dict(payload)

    if "symbols" in out:
        symbols = out["symbols"]
        if not isinstance(symbols, list) or not symbols:
            raise RuntimeOverridesValidationError("symbols must be a non-empty list")
        if not all(isinstance(s, str) and s.strip() for s in symbols):
            raise RuntimeOverridesValidationError("symbols entries must be non-empty strings")
        out["symbols"] = [str(s).strip() for s in symbols]

    strategy = _require_mapping(out.get("strategy"), "strategy")
    if strategy:
        enabled = strategy.get("enabled_strategies")
        if enabled is not None:
            if not isinstance(enabled, list):
                raise RuntimeOverridesValidationError("strategy.enabled_strategies must be a list")
            cleaned: list[str] = []
            for raw in enabled:
                name = str(raw).strip().lower()
                if name not in KNOWN_STRATEGIES:
                    raise RuntimeOverridesValidationError(
                        f"unknown strategy in enabled_strategies: {raw!r}"
                    )
                if name not in cleaned:
                    cleaned.append(name)
            strategy["enabled_strategies"] = cleaned
        for flag in (
            "use_smc_confluence",
            "use_liquidity_volume",
            "use_ultra_scalp",
            "use_news_straddle",
            "use_delta",
        ):
            if flag in strategy:
                strategy[flag] = _as_bool(strategy[flag], f"strategy.{flag}")
        if "min_reward_risk_ratio" in strategy:
            rr = _as_float(strategy["min_reward_risk_ratio"], "strategy.min_reward_risk_ratio")
            if rr + 1e-12 < HARD_MIN_GROSS_RR:
                raise RuntimeOverridesValidationError(
                    f"strategy.min_reward_risk_ratio {rr} < hard floor {HARD_MIN_GROSS_RR}"
                )
            strategy["min_reward_risk_ratio"] = rr
        ultra = _require_mapping(strategy.get("ultra_scalp"), "strategy.ultra_scalp")
        if "min_reward_risk_ratio" in ultra:
            urr = _as_float(
                ultra["min_reward_risk_ratio"], "strategy.ultra_scalp.min_reward_risk_ratio"
            )
            if urr + 1e-12 < HARD_MIN_GROSS_RR:
                raise RuntimeOverridesValidationError(
                    "strategy.ultra_scalp.min_reward_risk_ratio below hard 1.5 floor"
                )
            ultra["min_reward_risk_ratio"] = urr
        if "net_rr_after_costs" in ultra:
            ultra["net_rr_after_costs"] = _as_float(
                ultra["net_rr_after_costs"], "strategy.ultra_scalp.net_rr_after_costs"
            )
        if ultra:
            strategy["ultra_scalp"] = ultra
        out["strategy"] = strategy

    sessions = _require_mapping(out.get("sessions"), "sessions")
    if sessions:
        mode = sessions.get("trading_hours_mode")
        if mode is not None:
            mode_s = str(mode).strip().lower()
            if mode_s not in KNOWN_HOURS:
                raise RuntimeOverridesValidationError(
                    f"sessions.trading_hours_mode must be one of {sorted(KNOWN_HOURS)}"
                )
            sessions["trading_hours_mode"] = mode_s
        if "trade_outside_sessions" in sessions:
            sessions["trade_outside_sessions"] = _as_bool(
                sessions["trade_outside_sessions"], "sessions.trade_outside_sessions"
            )
        out["sessions"] = sessions

    news = _require_mapping(out.get("news_filter"), "news_filter")
    if news:
        for flag in ("enabled", "high_impact_only", "fail_closed_when_stale"):
            if flag in news:
                news[flag] = _as_bool(news[flag], f"news_filter.{flag}")
        for key in (
            "blackout_minutes_before",
            "blackout_minutes_after",
            "max_calendar_age_minutes",
        ):
            if key in news:
                news[key] = _as_float(news[key], f"news_filter.{key}")
                if news[key] < 0:
                    raise RuntimeOverridesValidationError(f"news_filter.{key} must be >= 0")
        out["news_filter"] = news

    risk = _require_mapping(out.get("risk"), "risk")
    if risk:
        if "max_risk_per_trade_pct" in risk:
            ceiling = _as_float(risk["max_risk_per_trade_pct"], "risk.max_risk_per_trade_pct")
            if ceiling > HARD_MAX_RISK_PCT + 1e-12:
                raise RuntimeOverridesValidationError(
                    f"risk.max_risk_per_trade_pct {ceiling} exceeds hard ceiling "
                    f"{HARD_MAX_RISK_PCT}"
                )
            if ceiling <= 0:
                raise RuntimeOverridesValidationError("risk.max_risk_per_trade_pct must be > 0")
            risk["max_risk_per_trade_pct"] = ceiling
        if "active_risk_per_trade_pct" in risk:
            active = _as_float(risk["active_risk_per_trade_pct"], "risk.active_risk_per_trade_pct")
            if active <= 0:
                raise RuntimeOverridesValidationError("risk.active_risk_per_trade_pct must be > 0")
            ceiling = float(risk.get("max_risk_per_trade_pct", HARD_MAX_RISK_PCT))
            ceiling = min(ceiling, HARD_MAX_RISK_PCT)
            if active > ceiling + 1e-12:
                raise RuntimeOverridesValidationError(
                    f"risk.active_risk_per_trade_pct {active} exceeds ceiling {ceiling}"
                )
            risk["active_risk_per_trade_pct"] = active
        if "min_reward_risk_ratio" in risk:
            rr = _as_float(risk["min_reward_risk_ratio"], "risk.min_reward_risk_ratio")
            if rr + 1e-12 < HARD_MIN_GROSS_RR:
                raise RuntimeOverridesValidationError(
                    f"risk.min_reward_risk_ratio {rr} < hard floor {HARD_MIN_GROSS_RR}"
                )
            risk["min_reward_risk_ratio"] = rr
        if "risk_presets_pct" in risk:
            presets = risk["risk_presets_pct"]
            if not isinstance(presets, list) or not presets:
                raise RuntimeOverridesValidationError(
                    "risk.risk_presets_pct must be a non-empty list"
                )
            cleaned_presets = [_as_float(p, "risk.risk_presets_pct[]") for p in presets]
            if any(p <= 0 for p in cleaned_presets):
                raise RuntimeOverridesValidationError("risk.risk_presets_pct entries must be > 0")
            risk["risk_presets_pct"] = cleaned_presets
        for key in (
            "max_portfolio_heat_pct",
            "max_daily_loss_pct",
            "max_weekly_loss_pct",
            "max_monthly_loss_pct",
            "cooldown_after_loss_minutes",
        ):
            if key in risk:
                risk[key] = _as_float(risk[key], f"risk.{key}")
                if risk[key] < 0:
                    raise RuntimeOverridesValidationError(f"risk.{key} must be >= 0")
        if (
            "max_portfolio_heat_pct" in risk
            and risk["max_portfolio_heat_pct"] > HARD_MAX_RISK_PCT + 1e-12
        ):
            raise RuntimeOverridesValidationError(
                "risk.max_portfolio_heat_pct cannot exceed hard 1% portfolio heat ceiling"
            )
        for key in (
            "max_concurrent_positions",
            "max_trades_per_symbol_day",
            "max_trades_portfolio_day",
        ):
            if key in risk:
                risk[key] = _as_int(risk[key], f"risk.{key}")
                if risk[key] < 1:
                    raise RuntimeOverridesValidationError(f"risk.{key} must be >= 1")
        for flag in (
            "independent_symbol_entries",
            "daily_loss_limit_enabled",
            "daily_drawdown_close_all",
        ):
            if flag in risk:
                risk[flag] = _as_bool(risk[flag], f"risk.{flag}")
        mm = _require_mapping(risk.get("mistake_memory"), "risk.mistake_memory")
        if mm:
            if "enabled" in mm:
                mm["enabled"] = _as_bool(mm["enabled"], "risk.mistake_memory.enabled")
            for key in ("cooldown_minutes", "max_repeats"):
                if key in mm:
                    mm[key] = _as_int(mm[key], f"risk.mistake_memory.{key}")
                    if mm[key] < 1:
                        raise RuntimeOverridesValidationError(
                            f"risk.mistake_memory.{key} must be >= 1"
                        )
            if "min_loss_r" in mm:
                mm["min_loss_r"] = _as_float(mm["min_loss_r"], "risk.mistake_memory.min_loss_r")
            for flag in ("match_session", "match_exit_type", "persist"):
                if flag in mm:
                    mm[flag] = _as_bool(mm[flag], f"risk.mistake_memory.{flag}")
            risk["mistake_memory"] = mm
        out["risk"] = risk

    ml = _require_mapping(out.get("ml"), "ml")
    if ml and "enabled" in ml:
        ml["enabled"] = _as_bool(ml["enabled"], "ml.enabled")
        out["ml"] = ml

    execution = _require_mapping(out.get("execution"), "execution")
    if execution:
        broker = execution.get("broker")
        if broker is not None:
            broker_s = str(broker).strip().lower()
            if broker_s not in KNOWN_BROKERS:
                raise RuntimeOverridesValidationError(
                    f"execution.broker must be one of {sorted(KNOWN_BROKERS)}"
                )
            execution["broker"] = broker_s
        if "trade_on_bar_close_only" in execution:
            execution["trade_on_bar_close_only"] = _as_bool(
                execution["trade_on_bar_close_only"], "execution.trade_on_bar_close_only"
            )
        if "single_instance" in execution:
            execution["single_instance"] = _as_bool(
                execution["single_instance"], "execution.single_instance"
            )
        for key in ("max_entry_slippage_r_fraction", "max_risk_overrun_pct"):
            if key in execution:
                execution[key] = _as_float(execution[key], f"execution.{key}")
                if execution[key] < 0:
                    raise RuntimeOverridesValidationError(f"execution.{key} must be >= 0")
        out["execution"] = execution

    # Explicitly refuse Telegram-disabling remote gates if someone adds them later.
    control = out.get("control")
    if isinstance(control, dict):
        for key, value in control.items():
            if str(key).startswith("remote_can_") and value is False:
                raise RuntimeOverridesValidationError(
                    f"control.{key}=false is refused — Telegram capabilities must remain available"
                )

    return out
