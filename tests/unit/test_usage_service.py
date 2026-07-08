"""Unit tests for UsageService aggregations."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    import src.database.models  # noqa: F401 - register all models

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()


def _seed(db, *, events=(), sessions=(), decks=(), identities=(), request_logs=()):
    from src.database.models import (
        AppIdentity,
        RequestLog,
        SessionSlideDeck,
        UsageEvent,
        UserSession,
    )

    for username, event_type, ts, session_id in events:
        db.add(
            UsageEvent(
                username=username, event_type=event_type, ts=ts, session_id=session_id
            )
        )
    for sid, created_by, created_at in sessions:
        db.add(
            UserSession(
                session_id=sid,
                created_by=created_by,
                created_at=created_at,
                last_activity=created_at,
            )
        )
    db.flush()
    for sid, created_at in decks:
        us = (
            db.query(UserSession).filter(UserSession.session_id == sid).one()
        )
        db.add(
            SessionSlideDeck(
                session_id=us.id,
                title="t",
                html_content="<html></html>",
                created_at=created_at,
            )
        )
    for name, first_seen in identities:
        db.add(
            AppIdentity(
                identity_id=name,
                identity_type="USER",
                identity_name=name,
                first_seen_at=first_seen,
                last_seen_at=first_seen,
            )
        )
    for path, ts, status in request_logs:
        db.add(
            RequestLog(
                method="GET", path=path, status_code=status, duration_ms=1.0, timestamp=ts
            )
        )
    db.commit()


NOW = datetime.utcnow()
TODAY = NOW.replace(hour=12, minute=0, second=0, microsecond=0)
D = timedelta(days=1)


class TestSummary:
    def test_totals_union_identities_and_sessions(self, db_session):
        from src.api.services.usage_service import UsageService

        _seed(
            db_session,
            identities=[("alice@x.com", TODAY - 40 * D), ("carol@x.com", TODAY - 40 * D)],
            sessions=[("s1", "alice@x.com", TODAY - 40 * D), ("s2", "bob@x.com", TODAY)],
            decks=[("s1", TODAY - 40 * D), ("s2", TODAY)],
        )
        result = UsageService().get_summary(db_session, days=7)
        # alice (both), carol (identity only), bob (session only) = 3
        assert result["total_users_ever"] == 3
        assert result["total_decks_ever"] == 2
        assert result["window"]["days"] == 7
        assert result["window"]["decks_created"] == 1  # only s2's deck in window

    def test_deleted_session_decks_counted_via_events(self, db_session):
        from src.api.services.usage_service import UsageService

        # deck_created event for a session that no longer exists (id 999)
        _seed(
            db_session,
            events=[("alice@x.com", "deck_created", TODAY - 40 * D, 999)],
            sessions=[("s1", "alice@x.com", TODAY)],
            decks=[("s1", TODAY)],
        )
        result = UsageService().get_summary(db_session, days=7)
        assert result["total_decks_ever"] == 2  # 1 live deck + 1 orphaned event

    def test_avg_decks_per_active_user(self, db_session):
        from src.api.services.usage_service import UsageService

        _seed(
            db_session,
            sessions=[("s1", "alice@x.com", TODAY), ("s2", "bob@x.com", TODAY)],
            decks=[("s1", TODAY), ("s2", TODAY)],
        )
        result = UsageService().get_summary(db_session, days=7)
        assert result["window"]["active_users"] == 2
        assert result["window"]["avg_decks_per_active_user"] == 1.0


class TestDaily:
    def test_event_days_use_real_logins(self, db_session):
        from src.api.services.usage_service import UsageService

        _seed(
            db_session,
            events=[
                ("alice@x.com", "login", TODAY, None),
                ("alice@x.com", "login", TODAY - timedelta(hours=2), None),
                ("bob@x.com", "login", TODAY, None),
            ],
        )
        result = UsageService().get_daily(db_session, days=7)
        today_row = result["days"][-1]
        assert today_row["date"] == TODAY.strftime("%Y-%m-%d")
        assert today_row["logins"] == 3
        assert today_row["logins_proxy"] is False
        assert today_row["distinct_users"] == 2
        assert result["history_boundary"] is not None

    def test_pre_boundary_days_fall_back_to_sessions(self, db_session):
        from src.api.services.usage_service import UsageService

        _seed(
            db_session,
            events=[("alice@x.com", "login", TODAY, None)],  # boundary = today
            sessions=[
                ("s1", "bob@x.com", TODAY - 2 * D),
                ("s2", "bob@x.com", TODAY - 2 * D),
            ],
        )
        result = UsageService().get_daily(db_session, days=7)
        two_days_ago = next(
            r for r in result["days"] if r["date"] == (TODAY - 2 * D).strftime("%Y-%m-%d")
        )
        assert two_days_ago["logins"] == 2  # sessions-created proxy
        assert two_days_ago["logins_proxy"] is True
        assert two_days_ago["distinct_users"] == 1

    def test_new_vs_returning_split(self, db_session):
        from src.api.services.usage_service import UsageService

        _seed(
            db_session,
            identities=[("alice@x.com", TODAY - 40 * D)],  # long-time user
            events=[
                ("alice@x.com", "login", TODAY, None),
                ("newbie@x.com", "login", TODAY, None),
            ],
        )
        result = UsageService().get_daily(db_session, days=7)
        today_row = result["days"][-1]
        assert today_row["new_users"] == 1       # newbie first seen today
        assert today_row["returning_users"] == 1  # alice seen 40 days ago

    def test_no_events_boundary_none(self, db_session):
        from src.api.services.usage_service import UsageService

        result = UsageService().get_daily(db_session, days=7)
        assert result["history_boundary"] is None
        assert len(result["days"]) == 7


class TestTopUsers:
    def test_ranked_by_logins_then_sessions(self, db_session):
        from src.api.services.usage_service import UsageService

        _seed(
            db_session,
            events=[
                ("alice@x.com", "login", TODAY, None),
                ("alice@x.com", "login", TODAY - D, None),
                ("bob@x.com", "login", TODAY, None),
            ],
            sessions=[("s1", "bob@x.com", TODAY), ("s2", "bob@x.com", TODAY)],
        )
        result = UsageService().get_top_users(db_session, days=7)
        assert result[0]["username"] == "alice@x.com"
        assert result[0]["logins"] == 2
        assert result[1]["username"] == "bob@x.com"
        assert result[1]["sessions_created"] == 2


class TestFunnel:
    def test_funnel_counts(self, db_session):
        from src.api.services.usage_service import UsageService

        _seed(
            db_session,
            events=[
                ("alice@x.com", "login", TODAY, None),
                ("bob@x.com", "login", TODAY, None),
            ],
            sessions=[("s1", "alice@x.com", TODAY)],
            decks=[("s1", TODAY)],
        )
        result = UsageService().get_funnel(db_session, days=7)
        assert result["logins"] == 2
        assert result["users_who_logged_in"] == 2
        assert result["users_who_created_deck"] == 1
        assert result["decks_created"] == 1
        assert result["proxy"] is False


class TestRetention:
    def test_retained_users_counted(self, db_session):
        from src.api.services.usage_service import UsageService

        # alice active last week and this week; bob only last week
        this_week_day = TODAY
        last_week_day = TODAY - 7 * D
        _seed(
            db_session,
            events=[
                ("alice@x.com", "login", last_week_day, None),
                ("bob@x.com", "login", last_week_day, None),
                ("alice@x.com", "login", this_week_day, None),
            ],
        )
        result = UsageService().get_retention(db_session)
        assert len(result) == 8
        current = result[-1]
        assert current["active_users"] == 1
        assert current["retained_from_prev"] == 1
        assert current["retention_pct"] == 50.0


class TestHeatmap:
    def test_matrix_shape_and_counts(self, db_session):
        from src.api.services.usage_service import UsageService

        ts = TODAY  # hour=12
        _seed(db_session, events=[("alice@x.com", "login", ts, None)])
        result = UsageService().get_heatmap(db_session, days=7)
        assert len(result["matrix"]) == 7
        assert all(len(row) == 24 for row in result["matrix"])
        assert result["matrix"][ts.weekday()][12] >= 1
        assert result["max"] >= 1
