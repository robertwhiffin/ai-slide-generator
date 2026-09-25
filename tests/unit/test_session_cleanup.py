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


def test_cleanup_does_not_count_candidate_deleted_by_racer(monkeypatch, tmp_path):
    """Break caught: a zero-row stale delete is counted as a successful expiry."""
    engine = create_engine(f"sqlite:///{tmp_path / 'cleanup-race.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    old = datetime.utcnow() - timedelta(hours=48)

    with factory.begin() as db:
        candidate = UserSession(session_id="concurrently-deleted", last_activity=old)
        db.add(candidate)
        db.flush()
        candidate_id = candidate.id

    @contextmanager
    def database_session():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    racer_ran = False

    def delete_candidate_before_stale_delete(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal racer_ran
        if racer_ran or not statement.lstrip().upper().startswith("DELETE FROM USER_SESSIONS"):
            return
        racer_ran = True
        with engine.begin() as racing_connection:
            racing_connection.execute(
                UserSession.__table__.delete().where(UserSession.id == candidate_id)
            )

    event.listen(engine, "before_cursor_execute", delete_candidate_before_stale_delete)
    monkeypatch.setattr(session_manager_module, "get_db_session", database_session)
    try:
        deleted_count = SessionManager(session_ttl_hours=24).cleanup_expired_sessions()
    finally:
        event.remove(engine, "before_cursor_execute", delete_candidate_before_stale_delete)

    assert racer_ran is True
    assert deleted_count == 0
    with factory() as db:
        assert db.get(UserSession, candidate_id) is None

    engine.dispose()


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

    failure_raised = False

    def reject_one_candidate(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal failure_raised
        if failure_raised or not statement.lstrip().upper().startswith("DELETE FROM USER_SESSIONS"):
            return
        failure_raised = True
        raise OperationalError("DELETE", {}, RuntimeError("deliberate failure"))

    event.listen(engine, "before_cursor_execute", reject_one_candidate)
    monkeypatch.setattr(session_manager_module, "get_db_session", database_session)

    try:
        with caplog.at_level(logging.ERROR, logger=session_manager_module.logger.name):
            deleted_count = SessionManager(session_ttl_hours=24).cleanup_expired_sessions()
    finally:
        event.remove(engine, "before_cursor_execute", reject_one_candidate)

    assert failure_raised is True
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
