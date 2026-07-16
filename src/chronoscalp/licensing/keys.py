"""License key generation and HMAC verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from chronoscalp.licensing.models import LicenseRecord, LicenseTier, compute_expiry


def _normalize_secret(admin_secret: str) -> bytes:
    secret = (admin_secret or "").strip()
    if not secret:
        # Deterministic fallback for local/dev only — production must set LICENSE_ADMIN_SECRET
        secret = "chronoscalp-dev-only-change-me"
    return secret.encode("utf-8")


def generate_license_key(admin_secret: str, tier: LicenseTier) -> str:
    """Create a human-readable license key: CS-<TIER>-XXXX-XXXX-XXXX."""
    raw = secrets.token_hex(8).upper()
    parts = [raw[i : i + 4] for i in range(0, 12, 4)]
    prefix = f"CS-{tier.value.upper()}"
    body = "-".join(parts)
    sig = (
        hmac.new(_normalize_secret(admin_secret), f"{prefix}-{body}".encode(), hashlib.sha256)
        .hexdigest()[:4]
        .upper()
    )
    return f"{prefix}-{body}-{sig}"


def verify_key_checksum(admin_secret: str, key: str) -> bool:
    """Verify the trailing HMAC nibble of a generated key."""
    key = key.strip().upper()
    parts = key.split("-")
    if len(parts) < 6 or parts[0] != "CS":
        return False
    sig = parts[-1]
    body = "-".join(parts[:-1])
    expected = (
        hmac.new(_normalize_secret(admin_secret), body.encode(), hashlib.sha256)
        .hexdigest()[:4]
        .upper()
    )
    return hmac.compare_digest(sig, expected)


def issue_license(
    admin_secret: str,
    tier: LicenseTier,
    customer_email: str = "",
    customer_name: str = "",
    notes: str = "",
    max_activations: int = 1,
) -> LicenseRecord:
    """Issue a new signed license record."""
    now = datetime.now(tz=UTC)
    key = generate_license_key(admin_secret, tier)
    return LicenseRecord(
        key=key,
        tier=tier,
        customer_email=customer_email.strip().lower(),
        customer_name=customer_name.strip(),
        issued_at=now.isoformat(),
        expires_at=compute_expiry(tier, now),
        active=True,
        notes=notes,
        max_activations=max_activations,
        activation_count=0,
    )
