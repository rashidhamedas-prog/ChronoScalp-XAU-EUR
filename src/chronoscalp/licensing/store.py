"""Persistent license catalog and local activation state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from chronoscalp.licensing.keys import verify_key_checksum
from chronoscalp.licensing.models import ActivationState, LicenseRecord, LicenseStatus
from chronoscalp.logging_setup import logger

DEFAULT_LICENSES_PATH = Path("data/licenses/licenses.json")
DEFAULT_ACTIVATION_PATH = Path("data/user/activation.json")


class LicenseStore:
    """JSON-backed registry of issued licenses (seller / admin side)."""

    def __init__(self, path: str | Path = DEFAULT_LICENSES_PATH) -> None:
        self.path = Path(path)
        self._licenses: dict[str, LicenseRecord] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._licenses = {}
            return
        with self.path.open(encoding="utf-8") as f:
            raw = json.load(f)
        records = raw.get("licenses") if isinstance(raw, dict) else raw
        self._licenses = {
            str(item["key"]).upper(): LicenseRecord.from_dict(item)
            for item in (records or [])
            if item.get("key")
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "licenses": [rec.to_dict() for rec in self._licenses.values()],
        }
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def add(self, record: LicenseRecord) -> None:
        self._licenses[record.key.upper()] = record
        self.save()

    def get(self, key: str) -> LicenseRecord | None:
        return self._licenses.get(key.strip().upper())

    def list_all(self) -> list[LicenseRecord]:
        return list(self._licenses.values())

    def revoke(self, key: str) -> bool:
        rec = self.get(key)
        if rec is None:
            return False
        rec.active = False
        self.save()
        return True


class ActivationStore:
    """Local activation file on the customer's machine."""

    def __init__(self, path: str | Path = DEFAULT_ACTIVATION_PATH) -> None:
        self.path = Path(path)
        self.state = ActivationState()
        self.load()

    def load(self) -> ActivationState:
        if not self.path.exists():
            self.state = ActivationState()
            return self.state
        with self.path.open(encoding="utf-8") as f:
            self.state = ActivationState.from_dict(json.load(f))
        return self.state

    def save(self, state: ActivationState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = state
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self.state = ActivationState()


def activate_license(
    key: str,
    admin_secret: str,
    license_store: LicenseStore,
    activation_store: ActivationStore,
) -> LicenseStatus:
    """Validate and activate ``key`` on this machine."""
    key = key.strip().upper()
    if not key:
        return LicenseStatus(valid=False, reason="کلید لایسنس خالی است")

    if not verify_key_checksum(admin_secret, key):
        return LicenseStatus(valid=False, reason="فرمت یا امضای کلید نامعتبر است")

    record = license_store.get(key)
    if record is None:
        return LicenseStatus(valid=False, reason="این کلید در سیستم ثبت نشده است")

    if not record.active:
        return LicenseStatus(valid=False, reason="این لایسنس لغو شده است")

    if record.is_expired():
        return LicenseStatus(valid=False, reason="این لایسنس منقضی شده است")

    if (
        record.activation_count >= record.max_activations
        and activation_store.state.license_key.upper() != key
    ):
        return LicenseStatus(
            valid=False,
            reason=f"حداکثر تعداد فعال‌سازی ({record.max_activations}) پر شده است",
        )

    if activation_store.state.license_key.upper() != key:
        record.activation_count += 1
        license_store.save()

    state = ActivationState(
        license_key=key,
        activated_at=datetime.now(tz=UTC).isoformat(),
        customer_email=record.customer_email,
        tier=record.tier.value,
        expires_at=record.expires_at,
    )
    activation_store.save(state)
    logger.info("License activated: tier={} email={}", record.tier.value, record.customer_email)
    return LicenseStatus(
        valid=True,
        reason="فعال شد",
        tier=record.tier.value,
        expires_at=record.expires_at,
        days_remaining=record.days_remaining(),
        customer_email=record.customer_email,
    )


def check_license(
    admin_secret: str,
    license_store: LicenseStore | None = None,
    activation_store: ActivationStore | None = None,
    *,
    require_license: bool = True,
) -> LicenseStatus:
    """Check whether this installation is allowed to run the bot."""
    if not require_license:
        return LicenseStatus(valid=True, reason="licensing disabled", tier="dev")

    licenses = license_store or LicenseStore()
    activation = activation_store or ActivationStore()
    activation.load()

    key = activation.state.license_key.strip().upper()
    if not key:
        return LicenseStatus(
            valid=False, reason="لایسنس فعال نشده — از پنل کاربری کلید را وارد کنید"
        )

    if not verify_key_checksum(admin_secret, key):
        return LicenseStatus(valid=False, reason="کلید فعال‌سازی نامعتبر است")

    record = licenses.get(key)
    if record is None:
        return LicenseStatus(valid=False, reason="کلید در کاتالوگ لایسنس پیدا نشد")

    if not record.active:
        return LicenseStatus(valid=False, reason="لایسنس لغو شده است")

    if record.is_expired():
        return LicenseStatus(valid=False, reason="لایسنس منقضی شده است — اشتراک را تمدید کنید")

    return LicenseStatus(
        valid=True,
        reason="OK",
        tier=record.tier.value,
        expires_at=record.expires_at,
        days_remaining=record.days_remaining(),
        customer_email=record.customer_email,
    )
