"""Broker connection helpers — test credentials and write .env / overrides safely."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from chronoscalp.logging_setup import logger

ENV_PATH = Path(".env")
OVERRIDES_PATH = Path("config/runtime_overrides.yaml")


@dataclass
class ConnectionTestResult:
    ok: bool
    message: str
    balance: float | None = None


def _upsert_env(path: Path, updates: dict[str, str]) -> None:
    """Create or update keys in a ``.env`` file without wiping other values."""
    existing: dict[str, str] = {}
    order: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                order.append(line)
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            existing[key] = value
            order.append(f"__KEY__{key}")

    for key, value in updates.items():
        if f"__KEY__{key}" not in order and key not in existing:
            order.append(f"__KEY__{key}")
        existing[key] = value

    lines: list[str] = []
    seen: set[str] = set()
    for item in order:
        if item.startswith("__KEY__"):
            key = item[len("__KEY__") :]
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"{key}={existing[key]}")
        else:
            lines.append(item)

    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_oanda_credentials(
    api_token: str,
    account_id: str,
    env_path: Path = ENV_PATH,
) -> None:
    _upsert_env(
        env_path,
        {
            "OANDA_API_TOKEN": api_token.strip(),
            "OANDA_ACCOUNT_ID": account_id.strip(),
        },
    )
    logger.info("OANDA credentials saved to {}", env_path)


def save_mt5_credentials(
    login: str,
    password: str,
    server: str,
    terminal_path: str = "",
    env_path: Path = ENV_PATH,
) -> None:
    _upsert_env(
        env_path,
        {
            "MT5_LOGIN": str(login).strip(),
            "MT5_PASSWORD": password,
            "MT5_SERVER": server.strip(),
            "MT5_TERMINAL_PATH": terminal_path.strip(),
        },
    )
    logger.info("MT5 credentials saved to {}", env_path)


def save_telegram_credentials(
    bot_token: str,
    chat_id: str,
    env_path: Path = ENV_PATH,
) -> None:
    _upsert_env(
        env_path,
        {
            "TELEGRAM_BOT_TOKEN": bot_token.strip(),
            "TELEGRAM_CHAT_ID": chat_id.strip(),
        },
    )


def apply_broker_to_settings_yaml(
    provider: str,
    mode: str,
    oanda_environment: str = "practice",
    overrides_path: Path = OVERRIDES_PATH,
) -> None:
    """Write broker mode into ``config/runtime_overrides.yaml`` (keeps settings.yaml intact)."""
    if mode == "paper":
        broker = "paper"
        data_source = "oanda" if provider == "oanda" else ("mt5" if provider == "mt5" else "auto")
    else:
        broker = provider
        data_source = provider if provider in ("oanda", "mt5") else "auto"

    payload = {
        "execution": {
            "broker": broker,
            "data_source": data_source,
        },
        "oanda": {
            "environment": oanda_environment,
        },
        "alerting": {},
    }
    # Preserve existing override keys (e.g. alerting.enabled)
    if overrides_path.exists():
        existing = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}
        if isinstance(existing, dict):
            for section, values in payload.items():
                if isinstance(values, dict) and isinstance(existing.get(section), dict):
                    merged = dict(existing[section])
                    merged.update(values)
                    existing[section] = merged
                else:
                    existing[section] = values
            payload = existing

    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("Broker overrides written to {}", overrides_path)


def enable_alerting_override(overrides_path: Path = OVERRIDES_PATH) -> None:
    payload: dict = {}
    if overrides_path.exists():
        payload = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}
    alerting = dict(payload.get("alerting") or {})
    alerting["enabled"] = True
    payload["alerting"] = alerting
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def apply_risk_preset(
    selected_pct: float,
    *,
    overrides_path: Path = OVERRIDES_PATH,
    hard_ceiling_pct: float = 1.0,
) -> float:
    """Persist the selected risk preset; return the effective (capped) percent."""
    from chronoscalp.risk.position_sizing import HARD_MAX_RISK_PCT, resolve_active_risk_pct

    ceiling = min(float(hard_ceiling_pct), HARD_MAX_RISK_PCT)
    payload: dict = {}
    if overrides_path.exists():
        payload = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            payload = {}
    risk = dict(payload.get("risk") or {})
    risk["active_risk_per_trade_pct"] = float(selected_pct)
    risk["max_risk_per_trade_pct"] = ceiling
    payload["risk"] = risk
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    effective = resolve_active_risk_pct(risk)
    logger.info(
        "Risk preset saved: selected={:.2f}% effective={:.2f}% (ceiling={:.2f}%)",
        selected_pct,
        effective,
        ceiling,
    )
    return effective


KNOWN_STRATEGIES: tuple[str, ...] = (
    "smc_confluence",
    "liquidity_volume",
    "ultra_scalp",
)


def _load_overrides(overrides_path: Path) -> dict:
    payload: dict = {}
    if overrides_path.exists():
        payload = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            payload = {}
    return payload


def _write_overrides(overrides_path: Path, payload: dict) -> None:
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def apply_active_symbols(
    symbols: list[str],
    *,
    overrides_path: Path = OVERRIDES_PATH,
    allowed: list[str] | None = None,
) -> list[str]:
    """Persist the active symbol list into runtime overrides. Returns cleaned list."""
    cleaned = [str(s).strip().upper() for s in symbols if str(s).strip()]
    # Preserve order, drop dupes
    seen: set[str] = set()
    ordered: list[str] = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    if allowed is not None:
        allowed_set = {str(a).strip().upper() for a in allowed}
        ordered = [s for s in ordered if s in allowed_set]
    if not ordered:
        raise ValueError("At least one symbol must remain selected")

    payload = _load_overrides(overrides_path)
    payload["symbols"] = ordered
    _write_overrides(overrides_path, payload)
    logger.info("Active symbols saved: {}", ",".join(ordered))
    return ordered


def apply_enabled_strategies(
    strategies: list[str],
    *,
    overrides_path: Path = OVERRIDES_PATH,
) -> list[str]:
    """Persist enabled strategy modes; sync boolean flags. Empty = MACD/trend only."""
    known = set(KNOWN_STRATEGIES)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in strategies:
        name = str(raw).strip().lower()
        if name in known and name not in seen:
            seen.add(name)
            cleaned.append(name)

    payload = _load_overrides(overrides_path)
    strategy = dict(payload.get("strategy") or {})
    strategy["enabled_strategies"] = cleaned
    strategy["use_smc_confluence"] = "smc_confluence" in seen
    strategy["use_liquidity_volume"] = "liquidity_volume" in seen
    strategy["use_ultra_scalp"] = "ultra_scalp" in seen
    payload["strategy"] = strategy
    _write_overrides(overrides_path, payload)
    logger.info("Enabled strategies saved: {}", ",".join(cleaned) or "(none)")
    return cleaned


def enable_live_confirm(*, overrides_env: Path | None = None) -> None:
    """Write CHRONOSCALP_CONFIRM_LIVE=yes into ``.env`` (explicit user action only)."""
    path = overrides_env or ENV_PATH
    _upsert_env(path, {"CHRONOSCALP_CONFIRM_LIVE": "yes"})
    logger.warning("CHRONOSCALP_CONFIRM_LIVE=yes written to {} by panel action", path)


def disable_live_confirm(*, overrides_env: Path | None = None) -> None:
    """Write CHRONOSCALP_CONFIRM_LIVE=no into ``.env``."""
    path = overrides_env or ENV_PATH
    _upsert_env(path, {"CHRONOSCALP_CONFIRM_LIVE": "no"})
    logger.info("CHRONOSCALP_CONFIRM_LIVE=no written to {}", path)


def test_oanda_connection(
    api_token: str,
    account_id: str,
    environment: str = "practice",
) -> ConnectionTestResult:
    """Live HTTPS check against OANDA account summary."""
    from chronoscalp.data.oanda_connector import OANDAConnector
    from chronoscalp.execution.oanda_broker import OANDABroker

    if not api_token.strip() or not account_id.strip():
        return ConnectionTestResult(ok=False, message="توکن و Account ID را وارد کنید")

    connector = OANDAConnector(
        api_token=api_token,
        account_id=account_id,
        environment=environment,
    )
    if not connector.connect():
        return ConnectionTestResult(
            ok=False,
            message="اتصال ناموفق — توکن، Account ID یا محیط (practice/live) را بررسی کنید",
        )
    try:
        broker = OANDABroker(
            api_token=api_token,
            account_id=account_id,
            environment=environment,
        )
        if not broker.connect():
            return ConnectionTestResult(ok=False, message="اتصال بروکر ناموفق بود")
        balance = broker.get_balance()
        connector.shutdown()
        return ConnectionTestResult(
            ok=True,
            message=f"اتصال موفق — موجودی/NAV ≈ {balance:.2f}",
            balance=balance,
        )
    except Exception as exc:  # noqa: BLE001
        return ConnectionTestResult(ok=False, message=f"خطا: {exc}")


def test_mt5_connection(
    login: int,
    password: str,
    server: str,
    terminal_path: str = "",
) -> ConnectionTestResult:
    """Windows-only MT5 terminal login check."""
    try:
        from chronoscalp.data.mt5_connector import MT5Connector

        connector = MT5Connector(
            login=int(login),
            password=password,
            server=server,
            terminal_path=terminal_path,
        )
        if not connector.connect():
            return ConnectionTestResult(
                ok=False,
                message="اتصال MT5 ناموفق — ترمینال را باز و لاگین کنید، سپس دوباره تلاش کنید",
            )
        connector.shutdown()
        return ConnectionTestResult(ok=True, message="اتصال MT5 موفق بود")
    except RuntimeError as exc:
        return ConnectionTestResult(ok=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001
        return ConnectionTestResult(ok=False, message=f"خطا: {exc}")
