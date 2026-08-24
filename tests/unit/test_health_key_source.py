"""The DELETE gate in the deploy tool reads this field; it must never leak the key."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    return TestClient(app)


def test_health_reports_lakebase_by_default(client, monkeypatch):
    monkeypatch.delenv("TELLR_ENCRYPTION_KEY", raising=False)
    body = client.get("/api/health").json()
    assert body["encryption_key_source"] == "lakebase"


def test_health_reports_secret_when_injected(client, monkeypatch):
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", Fernet.generate_key().decode())
    body = client.get("/api/health").json()
    assert body["encryption_key_source"] == "secret"


def test_health_never_exposes_the_key(client, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", key)
    raw = client.get("/api/health").text
    assert key not in raw
