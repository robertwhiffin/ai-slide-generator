"""Unit tests for deck contributor CRUD routes."""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base, get_db
from src.database.models.session import UserSession
from src.database.models.deck_contributor import DeckContributor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite with StaticPool so all sessions share one connection."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    import src.database.models.session  # noqa: F401
    import src.database.models.deck_contributor  # noqa: F401
    import src.database.models.profile_contributor  # noqa: F401

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()

    from src.api.main import app

    def _override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db

    yield session

    session.close()
    app.dependency_overrides.clear()


@pytest.fixture
def owner_session(db_session):
    us = UserSession(session_id="owner-session-1", created_by="owner@example.com")
    db_session.add(us)
    db_session.commit()
    return us


@pytest.fixture
def contributor_child_session(db_session, owner_session):
    us = UserSession(
        session_id="child-session-1",
        created_by="child@example.com",
        parent_session_id=owner_session.id,
    )
    db_session.add(us)
    db_session.commit()
    return us


def _make_client(user_name: str, user_id: str = "uid-test"):
    """Build a TestClient that sets DEV env vars so the middleware picks them up."""
    from src.api.main import app
    os.environ["DEV_USER_ID"] = user_name
    os.environ["DEV_USER_DATABRICKS_ID"] = user_id
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(db_session):
    """Client as session owner."""
    c = _make_client("owner@example.com", "uid-owner")
    yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


@pytest.fixture
def viewer_client(db_session):
    """Client as a non-owner viewer."""
    c = _make_client("viewer@example.com", "uid-viewer")
    yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


@pytest.fixture
def unknown_client(db_session):
    """Client with no identity."""
    from src.api.main import app
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)
    # Set empty dev user
    os.environ["DEV_USER_ID"] = ""
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    os.environ.pop("DEV_USER_ID", None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestListContributors:
    def test_list_empty(self, client, owner_session):
        resp = client.get(f"/api/sessions/{owner_session.session_id}/contributors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contributors"] == []
        assert data["total"] == 0

    def test_list_with_contributor(self, client, owner_session, db_session):
        c = DeckContributor(
            user_session_id=owner_session.id,
            identity_type="USER",
            identity_id="uid-collab",
            identity_name="collab@example.com",
            permission_level="CAN_EDIT",
            created_by="owner@example.com",
        )
        db_session.add(c)
        db_session.commit()

        resp = client.get(f"/api/sessions/{owner_session.session_id}/contributors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["contributors"][0]["identity_name"] == "collab@example.com"
        assert data["contributors"][0]["permission_level"] == "CAN_EDIT"


class TestAddContributor:
    def test_add_contributor_success(self, client, owner_session):
        payload = {
            "identity_id": "uid-new",
            "identity_type": "USER",
            "identity_name": "new@example.com",
            "permission_level": "CAN_EDIT",
        }
        resp = client.post(
            f"/api/sessions/{owner_session.session_id}/contributors",
            json=payload,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["identity_name"] == "new@example.com"
        assert data["permission_level"] == "CAN_EDIT"
        assert "id" in data

    def test_add_requires_can_manage(self, viewer_client, owner_session):
        payload = {
            "identity_id": "uid-new",
            "identity_type": "USER",
            "identity_name": "new@example.com",
            "permission_level": "CAN_VIEW",
        }
        resp = viewer_client.post(
            f"/api/sessions/{owner_session.session_id}/contributors",
            json=payload,
        )
        assert resp.status_code == 403

    def test_unknown_user_gets_403(self, unknown_client, owner_session):
        payload = {
            "identity_id": "uid-new",
            "identity_type": "USER",
            "identity_name": "new@example.com",
            "permission_level": "CAN_VIEW",
        }
        resp = unknown_client.post(
            f"/api/sessions/{owner_session.session_id}/contributors",
            json=payload,
        )
        assert resp.status_code == 403

    def test_cannot_add_session_creator(self, client, owner_session):
        payload = {
            "identity_id": "uid-owner",
            "identity_type": "USER",
            "identity_name": "owner@example.com",
            "permission_level": "CAN_EDIT",
        }
        resp = client.post(
            f"/api/sessions/{owner_session.session_id}/contributors",
            json=payload,
        )
        assert resp.status_code == 400

    def test_duplicate_contributor_409(self, client, owner_session, db_session):
        c = DeckContributor(
            user_session_id=owner_session.id,
            identity_type="USER",
            identity_id="uid-dup",
            identity_name="dup@example.com",
            permission_level="CAN_VIEW",
        )
        db_session.add(c)
        db_session.commit()

        payload = {
            "identity_id": "uid-dup",
            "identity_type": "USER",
            "identity_name": "dup@example.com",
            "permission_level": "CAN_EDIT",
        }
        resp = client.post(
            f"/api/sessions/{owner_session.session_id}/contributors",
            json=payload,
        )
        assert resp.status_code == 409

    def test_invalid_permission_can_use(self, client, owner_session):
        payload = {
            "identity_id": "uid-new",
            "identity_type": "USER",
            "identity_name": "new@example.com",
            "permission_level": "CAN_USE",
        }
        resp = client.post(
            f"/api/sessions/{owner_session.session_id}/contributors",
            json=payload,
        )
        assert resp.status_code == 400


class TestUpdateContributor:
    def test_update_permission_level(self, client, owner_session, db_session):
        c = DeckContributor(
            user_session_id=owner_session.id,
            identity_type="USER",
            identity_id="uid-collab",
            identity_name="collab@example.com",
            permission_level="CAN_VIEW",
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)

        resp = client.put(
            f"/api/sessions/{owner_session.session_id}/contributors/{c.id}",
            json={"permission_level": "CAN_EDIT"},
        )
        assert resp.status_code == 200
        assert resp.json()["permission_level"] == "CAN_EDIT"


class TestDeleteContributor:
    def test_delete_contributor(self, client, owner_session, db_session):
        c = DeckContributor(
            user_session_id=owner_session.id,
            identity_type="USER",
            identity_id="uid-collab",
            identity_name="collab@example.com",
            permission_level="CAN_VIEW",
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)

        resp = client.delete(
            f"/api/sessions/{owner_session.session_id}/contributors/{c.id}",
        )
        assert resp.status_code == 200

    def test_cannot_delete_session_creator(self, client, owner_session, db_session):
        c = DeckContributor(
            user_session_id=owner_session.id,
            identity_type="USER",
            identity_id="uid-owner-somehow",
            identity_name="owner@example.com",
            permission_level="CAN_MANAGE",
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)

        resp = client.delete(
            f"/api/sessions/{owner_session.session_id}/contributors/{c.id}",
        )
        assert resp.status_code == 400
