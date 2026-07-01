"""Tests for PATCH /api/sessions/{session_id}/global workspace sharing."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base, get_db
from src.database.models.session import UserSession


@pytest.fixture(scope="function")
def db_session():
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


def _make_client(user_name: str, user_id: str = "uid-test"):
    from src.api.main import app

    os.environ["DEV_USER_ID"] = user_name
    os.environ["DEV_USER_DATABRICKS_ID"] = user_id
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(db_session):
    c = _make_client("owner@example.com", "uid-owner")
    yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


@pytest.fixture
def viewer_client(db_session):
    c = _make_client("viewer@example.com", "uid-viewer")
    yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


class TestDeckGlobalPermissionRoutes:
    def test_set_workspace_can_view(self, client, owner_session, db_session):
        resp = client.patch(
            f"/api/sessions/{owner_session.session_id}/global?permission=CAN_VIEW",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["global_permission"] == "CAN_VIEW"
        db_session.refresh(owner_session)
        assert owner_session.global_permission == "CAN_VIEW"

    def test_set_workspace_can_edit(self, client, owner_session):
        resp = client.patch(
            f"/api/sessions/{owner_session.session_id}/global?permission=CAN_EDIT",
        )
        assert resp.status_code == 200
        assert resp.json()["global_permission"] == "CAN_EDIT"

    def test_reject_workspace_can_manage(self, client, owner_session):
        resp = client.patch(
            f"/api/sessions/{owner_session.session_id}/global?permission=CAN_MANAGE",
        )
        assert resp.status_code == 400

    def test_clear_workspace_sharing(self, client, owner_session, db_session):
        owner_session.global_permission = "CAN_VIEW"
        db_session.commit()

        resp = client.patch(f"/api/sessions/{owner_session.session_id}/global")
        assert resp.status_code == 200
        assert resp.json()["global_permission"] is None

    def test_requires_can_manage(self, viewer_client, owner_session):
        resp = viewer_client.patch(
            f"/api/sessions/{owner_session.session_id}/global?permission=CAN_VIEW",
        )
        assert resp.status_code == 403

    def test_list_contributors_includes_global(self, client, owner_session, db_session):
        owner_session.global_permission = "CAN_EDIT"
        db_session.commit()

        resp = client.get(f"/api/sessions/{owner_session.session_id}/contributors")
        assert resp.status_code == 200
        assert resp.json()["global_permission"] == "CAN_EDIT"
