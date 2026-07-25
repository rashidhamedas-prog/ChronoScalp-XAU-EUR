from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from chronoscalp.saas.api import create_app


def test_health_endpoint_open():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_status_requires_token_in_non_dev(monkeypatch):
    monkeypatch.setenv("CHRONOSCALP_ENV", "production")
    monkeypatch.setenv("CHRONOSCALP_API_TOKEN", "secret-token")
    client = TestClient(create_app())
    assert client.get("/status").status_code == 401
    ok = client.get("/status", headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200
    body = ok.json()
    assert "running" in body
    assert "symbols" in body
