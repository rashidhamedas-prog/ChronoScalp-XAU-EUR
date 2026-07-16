"""License and subscription models for ChronoScalp SaaS packaging."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


class LicenseTier(StrEnum):
    TRIAL = "trial"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


TIER_DEFAULT_DAYS: dict[LicenseTier, int | None] = {
    LicenseTier.TRIAL: 7,
    LicenseTier.MONTHLY: 30,
    LicenseTier.YEARLY: 365,
    LicenseTier.LIFETIME: None,
}


@dataclass
class LicenseRecord:
    """A single issued license key and its metadata."""

    key: str
    tier: LicenseTier
    customer_email: str = ""
    customer_name: str = ""
    issued_at: str = ""
    expires_at: str | None = None  # ISO UTC; None = lifetime
    active: bool = True
    notes: str = ""
    max_activations: int = 1
    activation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tier"] = self.tier.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LicenseRecord:
        return cls(
            key=str(data["key"]),
            tier=LicenseTier(str(data.get("tier", "monthly"))),
            customer_email=str(data.get("customer_email") or ""),
            customer_name=str(data.get("customer_name") or ""),
            issued_at=str(data.get("issued_at") or ""),
            expires_at=data.get("expires_at"),
            active=bool(data.get("active", True)),
            notes=str(data.get("notes") or ""),
            max_activations=int(data.get("max_activations", 1)),
            activation_count=int(data.get("activation_count", 0)),
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        moment = now or datetime.now(tz=UTC)
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return moment >= expiry

    def days_remaining(self, now: datetime | None = None) -> int | None:
        if self.expires_at is None:
            return None
        moment = now or datetime.now(tz=UTC)
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return 0
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return max(0, (expiry - moment).days)


@dataclass
class ActivationState:
    """Local machine activation of a license key."""

    license_key: str = ""
    activated_at: str = ""
    customer_email: str = ""
    tier: str = ""
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActivationState:
        return cls(
            license_key=str(data.get("license_key") or ""),
            activated_at=str(data.get("activated_at") or ""),
            customer_email=str(data.get("customer_email") or ""),
            tier=str(data.get("tier") or ""),
            expires_at=data.get("expires_at"),
        )


@dataclass
class LicenseStatus:
    """Result of validating the local activation against the license store."""

    valid: bool
    reason: str = ""
    tier: str = ""
    expires_at: str | None = None
    days_remaining: int | None = None
    customer_email: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_expiry(tier: LicenseTier, from_dt: datetime | None = None) -> str | None:
    """Return ISO expiry for ``tier``, or None for lifetime."""
    days = TIER_DEFAULT_DAYS[tier]
    if days is None:
        return None
    start = from_dt or datetime.now(tz=UTC)
    return (start + timedelta(days=days)).isoformat()
