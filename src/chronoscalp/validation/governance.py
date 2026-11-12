"""Parameter governance: geometry changes require a DSR>0 attached report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GEOMETRY_PATHS = (
    "strategy.delta.reward_risk_ratio",
    "strategy.delta.stop_atr_multiple",
    "strategy.operator_style.reward_risk_ratio",
    "risk.min_reward_risk_ratio",
    "risk.max_risk_per_trade_pct",
)


class GeometryGovernanceError(ValueError):
    """Raised when a geometry change lacks a qualifying validation report."""


def load_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GeometryGovernanceError(f"Report is not an object: {path}")
    return payload


def assert_geometry_change_allowed(
    *,
    report_path: Path | None,
    changed_paths: list[str],
) -> None:
    """Fail closed when entry/exit geometry keys change without DSR>0 report."""
    touched = [p for p in changed_paths if p in GEOMETRY_PATHS]
    if not touched:
        return
    if report_path is None or not report_path.exists():
        raise GeometryGovernanceError(
            "Geometry change requires an attached validation report with DSR>0; "
            f"touched={touched}"
        )
    report = load_report(report_path)
    if not bool(report.get("costs_net", False)):
        raise GeometryGovernanceError("Validation report must be costs_net=true")
    try:
        dsr = float(report.get("dsr", 0.0))
    except (TypeError, ValueError) as exc:
        raise GeometryGovernanceError("Report missing numeric dsr") from exc
    if dsr <= 0.0:
        raise GeometryGovernanceError(f"Geometry change rejected: report DSR={dsr} is not > 0")
    if str(report.get("verdict", "reject")) == "reject":
        raise GeometryGovernanceError(f"Geometry change rejected: verdict={report.get('verdict')}")
