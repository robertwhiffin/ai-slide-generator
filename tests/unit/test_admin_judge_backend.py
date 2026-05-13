"""Tests for Admin LLM judge backend API and normalize_llm_judge_backend."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base, get_db
from src.core.settings_db import normalize_llm_judge_backend
from src.database.models import ConfigProfile


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="module")
def session_factory(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


@pytest.fixture
def db_session(session_factory, db_engine):
    session = session_factory()
    yield session
    session.rollback()
    session.close()
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM config_profiles"))
        conn.commit()


@pytest.fixture(scope="module")
def test_client(db_engine, session_factory):
    from src.api.main import app

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_normalize_llm_judge_backend():
    assert normalize_llm_judge_backend(None) == "mlflow"
    assert normalize_llm_judge_backend("") == "mlflow"
    assert normalize_llm_judge_backend("MLFLOW") == "mlflow"
    assert normalize_llm_judge_backend("direct") == "direct"
    assert normalize_llm_judge_backend(" DIRECT ") == "direct"
    assert normalize_llm_judge_backend("other") == "mlflow"


def test_get_judge_backend_default_profile_direct(db_session, test_client):
    p = ConfigProfile(
        name="def-judge",
        is_default=True,
        is_deleted=False,
        llm_judge_backend="direct",
    )
    db_session.add(p)
    db_session.commit()

    r = test_client.get("/api/admin/judge-backend")
    assert r.status_code == 200
    assert r.json() == {"backend": "direct"}


def test_get_judge_backend_no_profile_returns_mlflow_default(db_session, test_client):
    r = test_client.get("/api/admin/judge-backend")
    assert r.status_code == 200
    assert r.json() == {"backend": "mlflow"}


def test_put_judge_backend_rejects_invalid(test_client):
    r = test_client.put("/api/admin/judge-backend", json={"backend": "redis"})
    assert r.status_code == 400


def test_put_judge_backend_updates_profile(db_session, test_client):
    p = ConfigProfile(
        name="def-judge-2",
        is_default=True,
        is_deleted=False,
        llm_judge_backend="mlflow",
    )
    db_session.add(p)
    db_session.commit()

    with patch("src.api.routes.admin.reload_settings"):
        r = test_client.put("/api/admin/judge-backend", json={"backend": "direct"})
    assert r.status_code == 200
    assert r.json() == {"backend": "direct"}

    db_session.expire_all()
    row = db_session.query(ConfigProfile).filter_by(name="def-judge-2").first()
    assert row is not None
    assert row.llm_judge_backend == "direct"


def test_put_judge_backend_404_when_no_profiles(test_client):
    with patch("src.api.routes.admin.reload_settings"):
        r = test_client.put("/api/admin/judge-backend", json={"backend": "mlflow"})
    assert r.status_code == 404
    assert "No configuration profile found" in r.json()["detail"]


def test_judge_backend_single_non_default_profile(db_session, test_client):
    """Databricks-style DB: one active profile but is_default never set."""
    p = ConfigProfile(
        name="solo",
        is_default=False,
        is_deleted=False,
        llm_judge_backend="mlflow",
    )
    db_session.add(p)
    db_session.commit()

    r = test_client.get("/api/admin/judge-backend")
    assert r.status_code == 200
    assert r.json() == {"backend": "mlflow"}

    with patch("src.api.routes.admin.reload_settings"):
        r = test_client.put("/api/admin/judge-backend", json={"backend": "direct"})
    assert r.status_code == 200
    assert r.json() == {"backend": "direct"}

    db_session.expire_all()
    row = db_session.query(ConfigProfile).filter_by(name="solo").first()
    assert row is not None
    assert row.llm_judge_backend == "direct"
    assert row.is_default is False
