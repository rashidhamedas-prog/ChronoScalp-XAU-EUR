"""Public licensing API and bot startup gate."""

from __future__ import annotations

from chronoscalp.licensing.keys import issue_license
from chronoscalp.licensing.models import LicenseStatus, LicenseTier
from chronoscalp.licensing.store import (
    ActivationStore,
    LicenseStore,
    activate_license,
    check_license,
)
from chronoscalp.logging_setup import logger


def require_valid_license(settings) -> LicenseStatus:
    """Raise RuntimeError if licensing is enabled and the key is invalid.

    Call from ``run_live`` / ``TradingBot`` before connecting to a broker.
    """
    lic_cfg = settings.raw.get("licensing", {}) if hasattr(settings, "raw") else {}
    require = bool(lic_cfg.get("require_license", True))
    admin_secret = getattr(settings.secrets, "license_admin_secret", "") or ""

    status = check_license(
        admin_secret=admin_secret,
        require_license=require,
    )
    if not status.valid:
        logger.error("License check failed: {}", status.reason)
        raise RuntimeError(
            f"لایسنس نامعتبر: {status.reason}. "
            "از پنل کاربری (scripts/app.py) کلید اشتراک را فعال کنید."
        )
    logger.info(
        "License OK tier={} days_remaining={}",
        status.tier,
        status.days_remaining,
    )
    return status


__all__ = [
    "ActivationStore",
    "LicenseStore",
    "LicenseStatus",
    "LicenseTier",
    "activate_license",
    "check_license",
    "issue_license",
    "require_valid_license",
]
