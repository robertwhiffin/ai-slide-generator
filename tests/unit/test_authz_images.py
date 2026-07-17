"""Authorization gating tests for images.py (SDR-4437 PR-2, HIGH-1)."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def caller(monkeypatch):
    monkeypatch.setattr(
        "src.api.routes.images._get_current_user", lambda: "alice@test.com"
    )
    return "alice@test.com"


def _fake_image(owner):
    img = MagicMock()
    img.id = 1
    img.uploaded_by = owner
    return img


@pytest.fixture
def db_returning(monkeypatch):
    """Override the get_db dependency to return a stub whose query yields *img*."""
    from src.api.main import app
    from src.core.database import get_db

    holder = {}

    def set_image(img):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = img
        app.dependency_overrides[get_db] = lambda: db
        holder["db"] = db
        return db

    yield set_image
    app.dependency_overrides.pop(get_db, None)


def test_update_image_other_owner_403(client, caller, db_returning):
    db_returning(_fake_image("bob@test.com"))
    resp = client.put("/api/images/1", json={"description": "mine now"})
    assert resp.status_code == 403


def test_update_image_own_image_allowed(client, caller, db_returning):
    db = db_returning(_fake_image("alice@test.com"))
    resp = client.put("/api/images/1", json={"description": "updated"})
    assert resp.status_code != 403
    db.commit.assert_called()


def test_delete_image_other_owner_403(client, caller, db_returning, monkeypatch):
    db_returning(_fake_image("bob@test.com"))
    svc_delete = MagicMock()
    monkeypatch.setattr("src.api.routes.images.image_service.delete_image", svc_delete)
    resp = client.delete("/api/images/1")
    assert resp.status_code == 403
    svc_delete.assert_not_called()


def test_delete_image_own_image_allowed(client, caller, db_returning, monkeypatch):
    db_returning(_fake_image("alice@test.com"))
    svc_delete = MagicMock()
    monkeypatch.setattr("src.api.routes.images.image_service.delete_image", svc_delete)
    resp = client.delete("/api/images/1")
    assert resp.status_code == 204
    svc_delete.assert_called_once()


def test_list_images_filters_by_caller(client, caller, db_returning, monkeypatch):
    db_returning(None)
    search = MagicMock(return_value=[])
    monkeypatch.setattr("src.api.routes.images.image_service.search_images", search)
    resp = client.get("/api/images")
    assert resp.status_code == 200
    assert search.call_args.kwargs["uploaded_by"] == "alice@test.com"


def test_get_image_data_stays_open(client, caller, monkeypatch, db_returning):
    """Accepted-risk open read: collaborator editor flow depends on it."""
    db_returning(None)
    monkeypatch.setattr(
        "src.api.routes.images.image_service.get_image_base64",
        MagicMock(return_value=("aGk=", "image/png")),
    )
    resp = client.get("/api/images/1/data")
    assert resp.status_code == 200
