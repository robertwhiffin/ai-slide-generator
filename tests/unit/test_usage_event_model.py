"""Unit tests for the UsageEvent model."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """In-memory SQLite for testing."""
    engine = create_engine("sqlite:///:memory:")
    import src.database.models.usage_event  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


class TestUsageEventModel:
    def test_create_login_event(self, db_session):
        from src.database.models.usage_event import EVENT_LOGIN, UsageEvent

        event = UsageEvent(username="alice@corp.com", event_type=EVENT_LOGIN)
        db_session.add(event)
        db_session.commit()

        row = db_session.query(UsageEvent).one()
        assert row.username == "alice@corp.com"
        assert row.event_type == "login"
        assert row.session_id is None
        assert isinstance(row.ts, datetime)

    def test_deck_event_with_session_id(self, db_session):
        from src.database.models.usage_event import EVENT_DECK_CREATED, UsageEvent

        event = UsageEvent(
            username="bob@corp.com", event_type=EVENT_DECK_CREATED, session_id=42
        )
        db_session.add(event)
        db_session.commit()
        assert db_session.query(UsageEvent).one().session_id == 42

    def test_indexes_exist(self, db_session):
        inspector = inspect(db_session.get_bind())
        index_names = {ix["name"] for ix in inspector.get_indexes("usage_events")}
        assert "ix_usage_events_type_ts" in index_names
        assert "ix_usage_events_username_ts" in index_names

    def test_registered_in_models_package(self):
        from src.database.models import UsageEvent  # noqa: F401
