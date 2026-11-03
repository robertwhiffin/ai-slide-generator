"""The admin "Add Genie One to new decks" setting.

One workspace-wide boolean, off until an admin turns it on:
  - stored in ``workspace_settings`` (``src.services.workspace_settings``);
  - read and written by admins at ``/api/admin/genie-one-default``;
  - read by every user at ``/api/tools/genie-one-default``, so the browser can
    show the Genie One pill on a new deck before the first message.

Harness: an in-memory SQLite engine (``StaticPool``) with ``create_all``; a bare
``FastAPI()`` holding only ``admin.router`` and ``tools.router``, ``get_db``
overridden onto that engine, ``require_admin`` overridden to allow, and
``src.core.settings_db.get_db_session`` patched onto the same engine, so the
non-admin read takes its real path.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import admin, tools
from src.api.routes._authz import require_admin
from src.core.database import Base, get_db
from src.core.settings_db import get_genie_one_default
from src.core.user_context import set_current_user
from src.database.models import WorkspaceSetting
from src.services import workspace_settings

ADMIN = "admin@example.com"


@pytest.fixture
def session_factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


@pytest.fixture
def db(session_factory: sessionmaker) -> Iterator[Session]:
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def patched_db_session(session_factory: sessionmaker) -> Iterator[None]:
    @contextlib.contextmanager
    def fake_get_db_session():
        session = session_factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    with patch("src.core.settings_db.get_db_session", fake_get_db_session):
        yield


@pytest.fixture
def client(session_factory: sessionmaker, patched_db_session: None) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(tools.router)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: None
    set_current_user(ADMIN)
    try:
        with TestClient(app) as c:
            yield c
    finally:
        set_current_user(None)


# --- storage ----------------------------------------------------------------


def test_off_when_never_set(db: Session) -> None:
    assert workspace_settings.genie_one_default(db) is False


def test_set_on_then_off(db: Session) -> None:
    assert workspace_settings.set_genie_one_default(db, enabled=True, user=ADMIN) is True
    assert workspace_settings.genie_one_default(db) is True
    assert workspace_settings.set_genie_one_default(db, enabled=False, user=ADMIN) is False
    assert workspace_settings.genie_one_default(db) is False


def test_set_records_who_changed_it(db: Session) -> None:
    workspace_settings.set_genie_one_default(db, enabled=True, user=ADMIN)
    row = db.get(WorkspaceSetting, workspace_settings.GENIE_ONE_DEFAULT_KEY)
    assert row is not None
    assert row.updated_by == ADMIN


def test_settings_db_reader_follows_the_stored_value(
    db: Session, patched_db_session: None
) -> None:
    assert get_genie_one_default() is False
    workspace_settings.set_genie_one_default(db, enabled=True, user=ADMIN)
    assert get_genie_one_default() is True


def test_settings_db_reader_is_off_when_the_table_is_missing() -> None:
    """A database the startup ``create_all`` has not reached yet reads as off."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine)

    @contextlib.contextmanager
    def no_tables():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    with patch("src.core.settings_db.get_db_session", no_tables):
        assert get_genie_one_default() is False
    engine.dispose()


# --- routes -----------------------------------------------------------------


def test_admin_get_is_off_by_default(client: TestClient) -> None:
    response = client.get("/api/admin/genie-one-default")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_admin_put_turns_it_on_for_everyone(client: TestClient) -> None:
    response = client.put("/api/admin/genie-one-default", json={"enabled": True})
    assert response.status_code == 200
    assert response.json() == {"enabled": True}
    assert client.get("/api/admin/genie-one-default").json() == {"enabled": True}
    assert client.get("/api/tools/genie-one-default").json() == {"enabled": True}


def test_admin_put_turns_it_back_off(client: TestClient) -> None:
    client.put("/api/admin/genie-one-default", json={"enabled": True})
    response = client.put("/api/admin/genie-one-default", json={"enabled": False})
    assert response.json() == {"enabled": False}
    assert client.get("/api/tools/genie-one-default").json() == {"enabled": False}


def test_admin_put_rejects_a_missing_flag(client: TestClient) -> None:
    response = client.put("/api/admin/genie-one-default", json={})
    assert response.status_code == 422


def test_user_read_is_off_by_default(client: TestClient) -> None:
    response = client.get("/api/tools/genie-one-default")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}
