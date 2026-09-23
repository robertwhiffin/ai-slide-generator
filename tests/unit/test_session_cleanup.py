from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.services import session_manager as session_manager_module
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import UserSession


def test_cleanup_isolates_candidates_and_counts_only_committed_deletes(monkeypatch, caplog):
    """Break caught: one failed expiry rolls back or stops later candidate deletes."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    old = datetime.utcnow() - timedelta(hours=48)
    fresh = datetime.utcnow()

    with factory.begin() as db:
        failing = UserSession(
            session_id="public-failing-session-secret",
            created_by="private-failing-user@example.com",
            last_activity=old,
        )
        first_success = UserSession(session_id="old-first", last_activity=old)
        later_success = UserSession(session_id="old-later", last_activity=old)
        fresh_session = UserSession(session_id="fresh", last_activity=fresh)
        db.add_all((failing, first_success, later_success, fresh_session))
        db.flush()
        failing_internal_id = failing.id

    @contextmanager
    def database_session():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def reject_one_candidate(_mapper, _connection, target):
        if target.id == failing_internal_id:
            raise OperationalError("DELETE", {}, RuntimeError("deliberate failure"))

    event.listen(UserSession, "before_delete", reject_one_candidate)
    monkeypatch.setattr(session_manager_module, "get_db_session", database_session)

    try:
        with caplog.at_level(logging.ERROR, logger=session_manager_module.logger.name):
            deleted_count = SessionManager(session_ttl_hours=24).cleanup_expired_sessions()
    finally:
        event.remove(UserSession, "before_delete", reject_one_candidate)

    assert deleted_count == 2
    with factory() as db:
        remaining = set(db.scalars(select(UserSession.session_id)))
    assert remaining == {"public-failing-session-secret", "fresh"}

    failure_records = [
        record
        for record in caplog.records
        if record.getMessage() == "Failed to delete expired session"
    ]
    assert len(failure_records) == 1
    assert failure_records[0].session_id == failing_internal_id
    assert failure_records[0].exception_class == "OperationalError"
    assert "public-failing-session-secret" not in caplog.text
    assert "private-failing-user@example.com" not in caplog.text

    engine.dispose()
