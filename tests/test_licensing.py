from __future__ import annotations

from pathlib import Path

from chronoscalp.licensing import (
    ActivationStore,
    LicenseStore,
    LicenseTier,
    activate_license,
    check_license,
    issue_license,
)
from chronoscalp.licensing.keys import verify_key_checksum

SECRET = "test-admin-secret-for-unit-tests"


def test_issue_and_verify_checksum():
    rec = issue_license(SECRET, LicenseTier.MONTHLY, customer_email="a@b.com")
    assert rec.key.startswith("CS-MONTHLY-")
    assert verify_key_checksum(SECRET, rec.key)


def test_activate_and_check(tmp_path: Path):
    store = LicenseStore(tmp_path / "licenses.json")
    activation = ActivationStore(tmp_path / "activation.json")
    rec = issue_license(SECRET, LicenseTier.TRIAL, customer_email="u@test.com")
    store.add(rec)

    status = activate_license(rec.key, SECRET, store, activation)
    assert status.valid is True
    assert status.tier == "trial"

    checked = check_license(SECRET, store, activation, require_license=True)
    assert checked.valid is True


def test_check_fails_without_activation(tmp_path: Path):
    store = LicenseStore(tmp_path / "licenses.json")
    activation = ActivationStore(tmp_path / "activation.json")
    status = check_license(SECRET, store, activation, require_license=True)
    assert status.valid is False


def test_require_license_false_allows_run(tmp_path: Path):
    status = check_license(SECRET, require_license=False)
    assert status.valid is True


def test_revoke_blocks_activation(tmp_path: Path):
    store = LicenseStore(tmp_path / "licenses.json")
    activation = ActivationStore(tmp_path / "activation.json")
    rec = issue_license(SECRET, LicenseTier.YEARLY)
    store.add(rec)
    store.revoke(rec.key)
    status = activate_license(rec.key, SECRET, store, activation)
    assert status.valid is False
