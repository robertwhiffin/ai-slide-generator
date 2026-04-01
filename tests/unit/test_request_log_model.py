"""Unit tests for the RequestLog model."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """In-memory SQLite for testing."""
    engine = create_engine("sqlite:///:memory:")
    import src.database.models.request_log  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


class TestRequestLogModel:
    def test_create_request_log(self, db_session):
        from src.database.models.request_log import RequestLog

        log = RequestLog(
            timestamp=datetime.now(timezone.utc),
            method="GET",
            path="/api/sessions/{session_id}",
            status_code=200,
            duration_ms=123.45,
            request_id="550e8400-e29b-41d4-a716-446655440000",
        )
        db_session.add(log)
        db_session.commit()

        result = db_session.query(RequestLog).first()
        assert result.id is not None
        assert result.method == "GET"
        assert result.path == "/api/sessions/{session_id}"
        assert result.status_code == 200
        assert result.duration_ms == 123.45
        assert result.request_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_timestamp_index_exists(self, db_session):
        """Verify the timestamp column has an index."""
        from src.database.models.request_log import RequestLog

        indexes = RequestLog.__table__.indexes
        timestamp_indexes = [
            idx for idx in indexes if "timestamp" in [c.name for c in idx.columns]
        ]
        assert len(timestamp_indexes) == 1

    def test_repr(self, db_session):
        from src.database.models.request_log import RequestLog

        log = RequestLog(
            method="POST",
            path="/api/slides",
            status_code=201,
            duration_ms=50.0,
        )
        assert "POST" in repr(log)
        assert "/api/slides" in repr(log)
