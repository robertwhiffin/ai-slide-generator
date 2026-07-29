# Admin Usage Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Usage tab to `/admin` (durable `usage_events` log + on-the-fly SQL analytics: daily logins, distinct/new/returning users, decks, top users, funnel, retention, heatmap) and revamp the Feedback tab into a raw feedback browser.

**Architecture:** New `usage_events` table captures `login` / `deck_created` / `deck_retrieved` events via fire-and-forget writes (mirroring the `request_logs` pattern). A new `UsageService` aggregates in Python over `usage_events`, `user_sessions`, `session_slide_decks`, `app_identities`, and `request_logs` (small data — no rollups), served by a new `/api/admin/usage/*` router. Frontend gets a `UsageDashboard` (recharts) tab and a reworked `FeedbackDashboard` with a paginated raw-feedback browser and a lazily-loaded, demoted AI summary.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL/Lakebase (SQLite in unit tests), React + TypeScript + Tailwind, recharts.

**Spec:** `docs/superpowers/specs/2026-07-03-admin-usage-dashboard-design.md` — read it first.

## Global Constraints

- Timestamps: naive UTC via `datetime.utcnow()` (matches existing models). Day bucketing = UTC calendar days.
- Event writes must NEVER block or fail a user request: fire-and-forget, exceptions swallowed and logged at `debug`.
- Windowed endpoints accept `?days=` in **{7, 14, 21, 28}**, default **7**; other values → 422.
- **No auth guards** on any new endpoint (decision: `/admin` stays ungated).
- Feedback stays **anonymous** — never add user columns to feedback tables.
- `usage_events.session_id` is deliberately **NOT a foreign key** (events must survive session deletion).
- Login/retrieval dedup window: **30 minutes**, in-process caches keyed on monotonic time.
- Aggregations are Python-side over filtered queries (dialect-proof for SQLite tests; small data).
- Do NOT schedule `POST /api/sessions/cleanup` — it would destroy `user_sessions` history.
- All new backend tests go under `tests/unit/`; run with `pytest tests/unit/<file> -v`. Frontend has no unit-test runner — verify with `cd frontend && npm run build`.

## Parallelization

- **Wave 1 (independent):** Task 1, Task 6, Task 7
- **Wave 2:** Task 2 (after 1), Task 4 (after 1)
- **Wave 3:** Task 3 (after 2), Task 5 (after 4), Task 9 (after 6+7)
- **Wave 4:** Task 8 (after 5+7 — needs endpoints' shapes and client)
- **Wave 5:** Task 10 (integration: suite + build + docs), then Task 11 (deploy + Playwright verification)

---

### Task 1: `UsageEvent` model

**Files:**
- Create: `src/database/models/usage_event.py`
- Modify: `src/database/models/__init__.py`
- Test: `tests/unit/test_usage_event_model.py`

**Interfaces:**
- Produces: `UsageEvent` model, table `usage_events`, columns `id, username(str,255,not null), event_type(str,30,not null), session_id(int,nullable), ts(datetime, default utcnow)`; constants `EVENT_LOGIN = "login"`, `EVENT_DECK_CREATED = "deck_created"`, `EVENT_DECK_RETRIEVED = "deck_retrieved"` importable from the module.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_usage_event_model.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_usage_event_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.database.models.usage_event'`

- [ ] **Step 3: Write the model**

```python
# src/database/models/usage_event.py
"""Durable usage-event log for admin analytics.

One row per event. Unlike ``user_sessions`` this table is never pruned;
it is the source of truth for login/deck activity history.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String

from src.core.database import Base

EVENT_LOGIN = "login"
EVENT_DECK_CREATED = "deck_created"
EVENT_DECK_RETRIEVED = "deck_retrieved"


class UsageEvent(Base):
    """A single usage event (login, deck created, deck retrieved)."""

    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    event_type = Column(String(30), nullable=False)
    # Intentionally NOT a ForeignKey: events must survive session deletion.
    session_id = Column(Integer, nullable=True)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_usage_events_type_ts", "event_type", "ts"),
        Index("ix_usage_events_username_ts", "username", "ts"),
    )

    def __repr__(self):
        return (
            f"<UsageEvent(id={self.id}, username='{self.username}', "
            f"event_type='{self.event_type}', ts={self.ts})>"
        )
```

In `src/database/models/__init__.py` add (alphabetical placement):

```python
from src.database.models.usage_event import UsageEvent
```

and add `"UsageEvent",` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_usage_event_model.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/database/models/usage_event.py src/database/models/__init__.py tests/unit/test_usage_event_model.py
git commit -m "feat: add UsageEvent model for durable usage analytics"
```

---

### Task 2: Usage-event writer helper (dedup + fire-and-forget)

**Files:**
- Create: `src/api/services/usage_events.py`
- Test: `tests/unit/test_usage_events_writer.py`

**Interfaces:**
- Consumes: `UsageEvent`, `EVENT_*` constants from Task 1.
- Produces module `src.api.services.usage_events` with:
  - `record_login(username: str) -> None`
  - `record_deck_created(username: str | None, session_id: int | None) -> None`
  - `record_deck_retrieved(username: str | None, session_id: int | None) -> None`
  - `reset_dedup_caches() -> None` (test helper)
  - internal `_write_event(username, event_type, session_id)` and `_submit(...)` (patch points for tests)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_usage_events_writer.py
"""Unit tests for the usage-event writer (dedup + non-blocking)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def clean_caches():
    from src.api.services import usage_events

    usage_events.reset_dedup_caches()
    yield
    usage_events.reset_dedup_caches()


class TestLoginDedup:
    @patch("src.api.services.usage_events._submit")
    def test_first_login_writes(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("alice@corp.com")
        mock_submit.assert_called_once_with("alice@corp.com", "login", None)

    @patch("src.api.services.usage_events._submit")
    def test_repeat_login_within_window_deduped(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("alice@corp.com")
        record_login("alice@corp.com")
        assert mock_submit.call_count == 1

    @patch("src.api.services.usage_events._submit")
    def test_login_after_window_writes_again(self, mock_submit):
        from src.api.services import usage_events

        usage_events.record_login("alice@corp.com")
        # Age the cache entry past the 30-minute window
        usage_events._login_cache["alice@corp.com"] -= usage_events._DEDUP_WINDOW_SECONDS + 1
        usage_events.record_login("alice@corp.com")
        assert mock_submit.call_count == 2

    @patch("src.api.services.usage_events._submit")
    def test_different_users_not_deduped(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("alice@corp.com")
        record_login("bob@corp.com")
        assert mock_submit.call_count == 2

    @patch("src.api.services.usage_events._submit")
    def test_empty_username_ignored(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("")
        record_login(None)
        mock_submit.assert_not_called()


class TestDeckEvents:
    @patch("src.api.services.usage_events._submit")
    def test_deck_created_always_writes(self, mock_submit):
        from src.api.services.usage_events import record_deck_created

        record_deck_created("alice@corp.com", 7)
        record_deck_created("alice@corp.com", 8)
        assert mock_submit.call_count == 2
        mock_submit.assert_any_call("alice@corp.com", "deck_created", 7)

    @patch("src.api.services.usage_events._submit")
    def test_deck_retrieved_deduped_per_user_session(self, mock_submit):
        from src.api.services.usage_events import record_deck_retrieved

        record_deck_retrieved("alice@corp.com", 7)
        record_deck_retrieved("alice@corp.com", 7)  # deduped
        record_deck_retrieved("alice@corp.com", 8)  # different deck -> writes
        record_deck_retrieved("bob@corp.com", 7)    # different user -> writes
        assert mock_submit.call_count == 3

    @patch("src.api.services.usage_events._submit")
    def test_deck_events_without_username_ignored(self, mock_submit):
        from src.api.services.usage_events import (
            record_deck_created,
            record_deck_retrieved,
        )

        record_deck_created(None, 7)
        record_deck_retrieved(None, 7)
        mock_submit.assert_not_called()


class TestWriteNeverRaises:
    def test_write_event_swallows_db_errors(self):
        from src.api.services.usage_events import _write_event

        with patch(
            "src.core.database.get_session_local",
            side_effect=RuntimeError("db down"),
        ):
            # Must not raise
            _write_event("alice@corp.com", "login", None)

    def test_write_event_persists_row(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from src.core.database import Base
        from src.database.models.usage_event import UsageEvent

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)

        with patch("src.core.database.get_session_local", return_value=factory):
            from src.api.services.usage_events import _write_event

            _write_event("alice@corp.com", "login", None)

        db = factory()
        row = db.query(UsageEvent).one()
        assert row.username == "alice@corp.com"
        assert row.event_type == "login"
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_usage_events_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.services.usage_events'`

- [ ] **Step 3: Write the helper**

```python
# src/api/services/usage_events.py
"""Fire-and-forget usage-event recording with in-process dedup.

Mirrors the request_logs middleware pattern: writes happen on an executor
thread (or inline when already off the event loop) and never raise.

Dedup semantics (per spec):
- ``login``: one event per username per 30-minute window ("visit").
- ``deck_retrieved``: one event per (username, session_id) per 30-minute window.
- ``deck_created``: never deduped.

Caches are per-process; a restart may produce occasional extra login
events, which is acceptable.
"""

import asyncio
import logging
import time

from src.database.models.usage_event import (
    EVENT_DECK_CREATED,
    EVENT_DECK_RETRIEVED,
    EVENT_LOGIN,
)

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_SECONDS = 30 * 60

_login_cache: dict[str, float] = {}
_retrieval_cache: dict[tuple[str, str], float] = {}


def reset_dedup_caches() -> None:
    """Clear dedup caches (test helper)."""
    _login_cache.clear()
    _retrieval_cache.clear()


def _write_event(username: str, event_type: str, session_id) -> None:
    """Synchronously insert one usage event. Never raises."""
    try:
        from src.core.database import get_session_local
        from src.database.models.usage_event import UsageEvent

        session_factory = get_session_local()
        db = session_factory()
        try:
            db.add(
                UsageEvent(
                    username=username,
                    event_type=event_type,
                    session_id=session_id,
                )
            )
            db.commit()
        except Exception:
            logger.debug("Failed to write usage event", exc_info=True)
            db.rollback()
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to write usage event", exc_info=True)


def _submit(username: str, event_type: str, session_id) -> None:
    """Dispatch a write without blocking the caller.

    On the event loop -> run_in_executor; in a worker thread (no running
    loop) -> write inline, which is already off the loop.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _write_event, username, event_type, session_id)
    except RuntimeError:
        _write_event(username, event_type, session_id)
    except Exception:
        logger.debug("Failed to submit usage event", exc_info=True)


def record_login(username) -> None:
    """Record a login "visit": first request after >=30 min of inactivity."""
    if not username:
        return
    now = time.monotonic()
    last = _login_cache.get(username)
    if last is not None and (now - last) < _DEDUP_WINDOW_SECONDS:
        return
    _login_cache[username] = now
    _submit(username, EVENT_LOGIN, None)


def record_deck_created(username, session_id) -> None:
    """Record a deck creation. Never deduped."""
    if not username:
        return
    _submit(username, EVENT_DECK_CREATED, session_id)


def record_deck_retrieved(username, session_id) -> None:
    """Record a deck open, deduped per (user, deck) per 30-minute window."""
    if not username:
        return
    key = (username, str(session_id))
    now = time.monotonic()
    last = _retrieval_cache.get(key)
    if last is not None and (now - last) < _DEDUP_WINDOW_SECONDS:
        return
    _retrieval_cache[key] = now
    _submit(username, EVENT_DECK_RETRIEVED, session_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_usage_events_writer.py -v`
Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/services/usage_events.py tests/unit/test_usage_events_writer.py
git commit -m "feat: usage-event writer with visit dedup and non-blocking writes"
```

---

### Task 3: Wire event capture into middleware, session manager, and deck-open route

**Files:**
- Modify: `src/api/main.py` (auth middleware, after `set_permission_context(permission_ctx)` around line 382)
- Modify: `src/api/services/session_manager.py` (deck create branch, around line 678-690; and `cleanup_expired_sessions` docstring around line 1781)
- Modify: `src/api/routes/sessions.py` (`get_session` route, around line 444-503)
- Test: `tests/unit/test_usage_event_capture.py`

**Interfaces:**
- Consumes: `record_login`, `record_deck_created`, `record_deck_retrieved` from Task 2 (exact signatures above).
- Produces: no new interfaces — behavioral wiring only.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_usage_event_capture.py
"""Tests that usage events are recorded from the request/deck code paths."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_caches():
    from src.api.services import usage_events

    usage_events.reset_dedup_caches()
    yield
    usage_events.reset_dedup_caches()


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app)


class TestLoginCapture:
    def test_authenticated_request_records_login(self, client):
        with patch("src.api.services.usage_events.record_login") as mock_login:
            client.get("/api/version")
        assert mock_login.called
        # Dev fallback identity is used when no OBO token header is present
        username = mock_login.call_args[0][0]
        assert username  # non-empty


class TestDeckRetrievedCapture:
    def test_get_session_records_retrieval(self, client):
        with patch(
            "src.api.routes.sessions.record_deck_retrieved"
        ) as mock_retrieved, patch(
            "src.api.routes.sessions.get_session_manager"
        ) as mock_mgr_factory, patch(
            "src.api.routes.sessions._require_session_access"
        ) as mock_access, patch(
            "src.api.routes.sessions.get_current_user",
            return_value="alice@corp.com",
        ):
            mock_mgr = mock_mgr_factory.return_value
            mock_mgr.get_session.return_value = {
                "id": 7,
                "session_id": "abc123",
                "created_by": "alice@corp.com",
            }
            mock_mgr.get_messages.return_value = []
            mock_mgr.get_slide_deck.return_value = None
            mock_access.return_value.value = "CAN_EDIT"

            resp = client.get("/api/sessions/abc123")

        assert resp.status_code == 200
        mock_retrieved.assert_called_once_with("alice@corp.com", 7)


class TestDeckCreatedCapture:
    def test_save_new_deck_records_creation(self):
        """save_slide_deck's create branch emits deck_created."""
        from src.api.services import session_manager as sm_module

        # Behavioral check via direct call with an in-memory DB:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from src.core.database import Base
        import src.database.models  # noqa: F401 - register all models

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)

        from src.database.models.session import UserSession

        db = factory()
        db.add(UserSession(session_id="s1", created_by="alice@corp.com"))
        db.commit()
        db.close()

        import contextlib

        @contextlib.contextmanager
        def fake_get_db_session():
            db = factory()
            try:
                yield db
                db.commit()
            finally:
                db.close()

        with patch(
            "src.api.services.session_manager.get_db_session", fake_get_db_session
        ), patch(
            "src.api.services.usage_events.record_deck_created"
        ) as mock_created:
            mgr = sm_module.SessionManager()
            mgr.save_slide_deck(
                session_id="s1",
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                modified_by="alice@corp.com",
            )

        assert mock_created.called
        assert mock_created.call_args[0][0] == "alice@corp.com"
```

Note for implementer: check `SessionManager.save_slide_deck`'s actual signature
(`src/api/services/session_manager.py`, method containing the `SessionSlideDeck(`
constructor near line 680) and adjust the test call's arguments to match required
parameters — the assertion logic must stay the same. If `SessionManager()` requires
constructor args, use the module's factory or minimal args.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_usage_event_capture.py -v`
Expected: FAIL — `record_deck_retrieved` not importable from `src.api.routes.sessions` (AttributeError on patch), and login capture assertion fails.

- [ ] **Step 3: Wire the three capture sites**

**(a) `src/api/main.py`** — in the auth middleware, immediately after
`set_permission_context(permission_ctx)` (before the existing
`# Record user login for local identity table` block), add:

```python
    # Record login usage-event (visit-deduped, non-blocking, all envs)
    if user_name:
        try:
            from src.api.services.usage_events import record_login
            record_login(user_name)
        except Exception as e:
            logger.debug(f"Failed to record login usage event: {e}")
```

**(b) `src/api/routes/sessions.py`** — add a module-level import near the other
service imports at the top of the file:

```python
from src.api.services.usage_events import record_deck_retrieved
```

Then in `get_session` (the `@router.get("/{session_id}")` handler), after the
permission check line
`permission = _require_session_access(session, db, PermissionLevel.CAN_VIEW)`, add:

```python
        # Record deck-open usage event (deduped per user+deck, non-blocking)
        if current_user:
            record_deck_retrieved(current_user, session.get("id"))
```

**(c) `src/api/services/session_manager.py`** — in `save_slide_deck`'s create
branch, right after `db.flush()` (the `else:` branch that constructs
`SessionSlideDeck(`), add:

```python
                # Record deck-created usage event (non-blocking)
                try:
                    from src.api.services.usage_events import record_deck_created
                    from src.core.user_context import get_current_user as _get_user

                    record_deck_created(
                        modified_by or _get_user(), deck_owner.id
                    )
                except Exception:
                    logger.debug("Failed to record deck_created event", exc_info=True)
```

**(d) `src/api/services/session_manager.py`** — extend the
`cleanup_expired_sessions` docstring:

```python
    def cleanup_expired_sessions(self) -> int:
        """Delete sessions that have exceeded TTL.

        WARNING: user_sessions is the app's durable usage history. This
        method is intentionally NOT scheduled anywhere — it is only
        reachable via the manual POST /api/sessions/cleanup endpoint.
        Do not wire it to a scheduler; doing so would destroy the
        history that the /admin usage dashboard's pre-event-log
        aggregations rely on.

        Returns:
            Number of sessions deleted
        """
```

- [ ] **Step 4: Run the new tests and the existing suites for touched files**

Run: `pytest tests/unit/test_usage_event_capture.py tests/unit/test_usage_events_writer.py -v && pytest tests/integration/test_api_routes.py -q`
Expected: all PASS (integration suite guards against middleware/route regressions)

- [ ] **Step 5: Commit**

```bash
git add src/api/main.py src/api/routes/sessions.py src/api/services/session_manager.py tests/unit/test_usage_event_capture.py
git commit -m "feat: capture login/deck usage events; warn against scheduling session cleanup"
```

---

### Task 4: `UsageService` aggregations

**Files:**
- Create: `src/api/services/usage_service.py`
- Test: `tests/unit/test_usage_service.py`

**Interfaces:**
- Consumes: `UsageEvent` + `EVENT_*` (Task 1), existing models `UserSession`, `SessionSlideDeck`, `AppIdentity`, `RequestLog`.
- Produces class `UsageService` with methods (all take `db: Session` first):
  - `get_summary(db, days: int) -> dict` → `{"total_users_ever": int, "total_decks_ever": int, "window": {"days": int, "active_users": int, "decks_created": int, "avg_decks_per_active_user": float | None, "logins": int}}`
  - `get_daily(db, days: int) -> dict` → `{"history_boundary": str | None, "days": [{"date": "YYYY-MM-DD", "logins": int, "logins_proxy": bool, "distinct_users": int, "new_users": int, "returning_users": int, "decks_created": int, "decks_retrieved": int, "retrievals_proxy": int | None}]}`
  - `get_top_users(db, days: int) -> list[dict]` → `[{"username": str, "logins": int, "sessions_created": int, "decks_created": int}]` (top 20, sorted by logins desc then sessions_created desc)
  - `get_funnel(db, days: int) -> dict` → `{"logins": int, "users_who_logged_in": int, "users_who_created_deck": int, "decks_created": int, "proxy": bool}`
  - `get_retention(db) -> list[dict]` → `[{"week_start": "YYYY-MM-DD", "active_users": int, "retained_from_prev": int | None, "retention_pct": float | None}]` (last 8 ISO weeks, oldest first)
  - `get_heatmap(db, days: int) -> dict` → `{"matrix": [[int]*24]*7, "max": int}` (row 0 = Monday)
- Module constant `ALLOWED_WINDOWS = {7, 14, 21, 28}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_usage_service.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_usage_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.services.usage_service'`

- [ ] **Step 3: Implement the service**

```python
# src/api/services/usage_service.py
"""On-the-fly usage analytics for the admin dashboard.

All aggregation happens in Python over time-filtered queries. This is a
deliberate choice (small data, SQLite-compatible tests) mirroring
FeedbackService.get_stats_report.

History semantics: `usage_events` provides literal login/retrieval events
from its first row onward (`history_boundary`). Days before the boundary
use `user_sessions` as a labeled proxy.
"""

from collections import defaultdict
from datetime import datetime, time as dt_time, timedelta

from sqlalchemy.orm import Session

from src.database.models import (
    AppIdentity,
    RequestLog,
    SessionSlideDeck,
    UsageEvent,
    UserSession,
)
from src.database.models.usage_event import (
    EVENT_DECK_CREATED,
    EVENT_DECK_RETRIEVED,
    EVENT_LOGIN,
)

ALLOWED_WINDOWS = {7, 14, 21, 28}

# Route template logged by the request-logging middleware for deck opens
_DECK_OPEN_ROUTE = "/api/sessions/{session_id}"


def _day_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _window_start(days: int) -> datetime:
    """Midnight UTC at the start of the window (last `days` calendar days incl. today)."""
    today = datetime.utcnow().date()
    return datetime.combine(today - timedelta(days=days - 1), dt_time.min)


def _day_list(days: int) -> list[str]:
    today = datetime.utcnow().date()
    return [
        (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(days - 1, -1, -1)
    ]


class UsageService:
    """Aggregates usage metrics for /api/admin/usage endpoints."""

    # ---------- shared helpers ----------

    def _events_in_window(self, db: Session, start: datetime) -> list[UsageEvent]:
        return db.query(UsageEvent).filter(UsageEvent.ts >= start).all()

    def _sessions_in_window(self, db: Session, start: datetime) -> list[UserSession]:
        return (
            db.query(UserSession)
            .filter(UserSession.created_at >= start)
            .all()
        )

    def _decks_in_window(self, db: Session, start: datetime) -> list[SessionSlideDeck]:
        return (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.created_at >= start)
            .all()
        )

    def _history_boundary(self, db: Session) -> datetime | None:
        first = (
            db.query(UsageEvent.ts)
            .filter(UsageEvent.event_type == EVENT_LOGIN)
            .order_by(UsageEvent.ts.asc())
            .first()
        )
        return first[0] if first else None

    def _first_seen_map(self, db: Session) -> dict[str, datetime]:
        """Earliest known appearance per username across all sources."""
        first_seen: dict[str, datetime] = {}

        def _merge(name, ts):
            if not name or ts is None:
                return
            if name not in first_seen or ts < first_seen[name]:
                first_seen[name] = ts

        for name, ts in db.query(
            AppIdentity.identity_name, AppIdentity.first_seen_at
        ).filter(AppIdentity.identity_type == "USER"):
            _merge(name, ts)
        for name, ts in db.query(UserSession.created_by, UserSession.created_at):
            _merge(name, ts)
        for name, ts in db.query(UsageEvent.username, UsageEvent.ts):
            _merge(name, ts)
        return first_seen

    # ---------- endpoints ----------

    def get_summary(self, db: Session, days: int) -> dict:
        start = _window_start(days)

        identity_users = {
            name
            for (name,) in db.query(AppIdentity.identity_name).filter(
                AppIdentity.identity_type == "USER"
            )
        }
        session_users = {
            name
            for (name,) in db.query(UserSession.created_by).filter(
                UserSession.created_by.isnot(None)
            )
        }
        total_users_ever = len(identity_users | session_users)

        live_deck_session_ids = {
            sid for (sid,) in db.query(SessionSlideDeck.session_id)
        }
        orphaned_deck_events = {
            sid
            for (sid,) in db.query(UsageEvent.session_id).filter(
                UsageEvent.event_type == EVENT_DECK_CREATED,
                UsageEvent.session_id.isnot(None),
            )
            if sid not in live_deck_session_ids
        }
        total_decks_ever = len(live_deck_session_ids) + len(orphaned_deck_events)

        events = self._events_in_window(db, start)
        sessions = self._sessions_in_window(db, start)
        active_from_last_activity = {
            name
            for (name,) in db.query(UserSession.created_by).filter(
                UserSession.last_activity >= start,
                UserSession.created_by.isnot(None),
            )
        }
        active_users = (
            {e.username for e in events}
            | {s.created_by for s in sessions if s.created_by}
            | active_from_last_activity
        )
        decks_created = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.created_at >= start)
            .count()
        )
        logins = sum(1 for e in events if e.event_type == EVENT_LOGIN)

        avg = round(decks_created / len(active_users), 1) if active_users else None
        return {
            "total_users_ever": total_users_ever,
            "total_decks_ever": total_decks_ever,
            "window": {
                "days": days,
                "active_users": len(active_users),
                "decks_created": decks_created,
                "avg_decks_per_active_user": avg,
                "logins": logins,
            },
        }

    def get_daily(self, db: Session, days: int) -> dict:
        start = _window_start(days)
        boundary = self._history_boundary(db)
        boundary_day = _day_key(boundary) if boundary else None

        events = self._events_in_window(db, start)
        sessions = self._sessions_in_window(db, start)
        decks = self._decks_in_window(db, start)
        first_seen = self._first_seen_map(db)

        logins_by_day: dict[str, int] = defaultdict(int)
        users_by_day: dict[str, set] = defaultdict(set)
        retrieved_by_day: dict[str, int] = defaultdict(int)
        for e in events:
            day = _day_key(e.ts)
            users_by_day[day].add(e.username)
            if e.event_type == EVENT_LOGIN:
                logins_by_day[day] += 1
            elif e.event_type == EVENT_DECK_RETRIEVED:
                retrieved_by_day[day] += 1

        sessions_by_day: dict[str, int] = defaultdict(int)
        session_users_by_day: dict[str, set] = defaultdict(set)
        for s in sessions:
            day = _day_key(s.created_at)
            sessions_by_day[day] += 1
            if s.created_by:
                session_users_by_day[day].add(s.created_by)

        decks_by_day: dict[str, int] = defaultdict(int)
        for d in decks:
            decks_by_day[_day_key(d.created_at)] += 1

        # Anonymous deck-open volume proxy from request_logs (30-day retention)
        proxy_retrievals_by_day: dict[str, int] = defaultdict(int)
        for (ts,) in db.query(RequestLog.timestamp).filter(
            RequestLog.timestamp >= start,
            RequestLog.method == "GET",
            RequestLog.path == _DECK_OPEN_ROUTE,
            RequestLog.status_code < 400,
        ):
            proxy_retrievals_by_day[_day_key(ts)] += 1

        rows = []
        for day in _day_list(days):
            pre_boundary = boundary_day is None or day < boundary_day
            if pre_boundary:
                logins = sessions_by_day.get(day, 0)
                day_users = session_users_by_day.get(day, set())
            else:
                logins = logins_by_day.get(day, 0)
                day_users = users_by_day.get(day, set())

            new_users = sum(
                1
                for u in day_users
                if u in first_seen and _day_key(first_seen[u]) == day
            )
            rows.append(
                {
                    "date": day,
                    "logins": logins,
                    "logins_proxy": pre_boundary,
                    "distinct_users": len(day_users),
                    "new_users": new_users,
                    "returning_users": len(day_users) - new_users,
                    "decks_created": decks_by_day.get(day, 0),
                    "decks_retrieved": retrieved_by_day.get(day, 0),
                    "retrievals_proxy": (
                        proxy_retrievals_by_day.get(day, 0) if pre_boundary else None
                    ),
                }
            )
        return {"history_boundary": boundary_day, "days": rows}

    def get_top_users(self, db: Session, days: int) -> list[dict]:
        start = _window_start(days)
        stats: dict[str, dict] = defaultdict(
            lambda: {"logins": 0, "sessions_created": 0, "decks_created": 0}
        )

        for e in self._events_in_window(db, start):
            if e.event_type == EVENT_LOGIN:
                stats[e.username]["logins"] += 1

        for s in self._sessions_in_window(db, start):
            if s.created_by:
                stats[s.created_by]["sessions_created"] += 1

        deck_rows = (
            db.query(UserSession.created_by)
            .join(SessionSlideDeck, SessionSlideDeck.session_id == UserSession.id)
            .filter(
                SessionSlideDeck.created_at >= start,
                UserSession.created_by.isnot(None),
            )
            .all()
        )
        for (name,) in deck_rows:
            stats[name]["decks_created"] += 1

        ranked = sorted(
            (
                {"username": name, **vals}
                for name, vals in stats.items()
            ),
            key=lambda r: (r["logins"], r["sessions_created"]),
            reverse=True,
        )
        return ranked[:20]

    def get_funnel(self, db: Session, days: int) -> dict:
        start = _window_start(days)
        events = self._events_in_window(db, start)

        login_events = [e for e in events if e.event_type == EVENT_LOGIN]
        proxy = len(login_events) == 0

        if proxy:
            sessions = self._sessions_in_window(db, start)
            logins = len(sessions)
            logged_in_users = {s.created_by for s in sessions if s.created_by}
        else:
            logins = len(login_events)
            logged_in_users = {e.username for e in login_events}

        deck_event_users = {
            e.username for e in events if e.event_type == EVENT_DECK_CREATED
        }
        deck_session_users = {
            name
            for (name,) in db.query(UserSession.created_by)
            .join(SessionSlideDeck, SessionSlideDeck.session_id == UserSession.id)
            .filter(
                SessionSlideDeck.created_at >= start,
                UserSession.created_by.isnot(None),
            )
        }
        decks_created = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.created_at >= start)
            .count()
        )
        return {
            "logins": logins,
            "users_who_logged_in": len(logged_in_users),
            "users_who_created_deck": len(deck_event_users | deck_session_users),
            "decks_created": decks_created,
            "proxy": proxy,
        }

    def get_retention(self, db: Session) -> list[dict]:
        today = datetime.utcnow().date()
        current_week_start = today - timedelta(days=today.weekday())
        # 9 week-starts, oldest first; we emit rows for the last 8
        week_starts = [
            current_week_start - timedelta(weeks=offset) for offset in range(8, -1, -1)
        ]
        window_start = datetime.combine(week_starts[0], dt_time.min)

        active_by_week: dict[str, set] = defaultdict(set)

        def _week_key(ts: datetime) -> str:
            d = ts.date()
            return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

        for e in db.query(UsageEvent).filter(UsageEvent.ts >= window_start):
            active_by_week[_week_key(e.ts)].add(e.username)
        for s in db.query(UserSession).filter(UserSession.created_at >= window_start):
            if s.created_by:
                active_by_week[_week_key(s.created_at)].add(s.created_by)

        rows = []
        for prev_start, week_start in zip(week_starts, week_starts[1:]):
            prev_key = prev_start.strftime("%Y-%m-%d")
            key = week_start.strftime("%Y-%m-%d")
            active = active_by_week.get(key, set())
            prev_active = active_by_week.get(prev_key, set())
            retained = len(active & prev_active) if prev_active else None
            pct = (
                round(100.0 * retained / len(prev_active), 1)
                if prev_active and retained is not None
                else None
            )
            rows.append(
                {
                    "week_start": key,
                    "active_users": len(active),
                    "retained_from_prev": retained,
                    "retention_pct": pct,
                }
            )
        return rows

    def get_heatmap(self, db: Session, days: int) -> dict:
        start = _window_start(days)
        matrix = [[0] * 24 for _ in range(7)]

        for e in self._events_in_window(db, start):
            matrix[e.ts.weekday()][e.ts.hour] += 1
        for s in self._sessions_in_window(db, start):
            matrix[s.created_at.weekday()][s.created_at.hour] += 1

        return {"matrix": matrix, "max": max(max(row) for row in matrix)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_usage_service.py -v`
Expected: 12 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/services/usage_service.py tests/unit/test_usage_service.py
git commit -m "feat: UsageService on-the-fly aggregations for admin usage dashboard"
```

---

### Task 5: `/api/admin/usage` routes

**Files:**
- Create: `src/api/routes/admin_usage.py`
- Modify: `src/api/main.py` (router import + `app.include_router(admin_usage.router)` beside the other routers ~line 413)
- Test: `tests/unit/test_admin_usage_routes.py`

**Interfaces:**
- Consumes: `UsageService` + `ALLOWED_WINDOWS` (Task 4 — exact method names/returns above).
- Produces endpoints: `GET /api/admin/usage/summary`, `/daily`, `/top-users`, `/funnel`, `/heatmap` (all `?days=` in {7,14,21,28}, default 7), and `GET /api/admin/usage/retention` (no params). No auth guards.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_admin_usage_routes.py
"""Unit tests for /api/admin/usage routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app)


@pytest.fixture
def mock_service():
    with patch("src.api.routes.admin_usage.UsageService") as cls:
        yield cls.return_value


class TestSummaryEndpoint:
    def test_returns_summary(self, client, mock_service):
        mock_service.get_summary.return_value = {
            "total_users_ever": 10,
            "total_decks_ever": 25,
            "window": {
                "days": 7,
                "active_users": 4,
                "decks_created": 6,
                "avg_decks_per_active_user": 1.5,
                "logins": 12,
            },
        }
        resp = client.get("/api/admin/usage/summary")
        assert resp.status_code == 200
        assert resp.json()["total_users_ever"] == 10
        mock_service.get_summary.assert_called_once()
        assert mock_service.get_summary.call_args.kwargs.get("days") == 7 or (
            mock_service.get_summary.call_args[0]
            and 7 in mock_service.get_summary.call_args[0]
        )

    def test_invalid_days_rejected(self, client, mock_service):
        assert client.get("/api/admin/usage/summary?days=10").status_code == 422
        assert client.get("/api/admin/usage/summary?days=99").status_code == 422

    def test_valid_windows_accepted(self, client, mock_service):
        mock_service.get_summary.return_value = {}
        for days in (7, 14, 21, 28):
            assert (
                client.get(f"/api/admin/usage/summary?days={days}").status_code == 200
            )


class TestOtherEndpoints:
    def test_daily(self, client, mock_service):
        mock_service.get_daily.return_value = {"history_boundary": None, "days": []}
        resp = client.get("/api/admin/usage/daily?days=14")
        assert resp.status_code == 200
        assert resp.json()["days"] == []

    def test_top_users(self, client, mock_service):
        mock_service.get_top_users.return_value = [
            {"username": "a@x.com", "logins": 3, "sessions_created": 1, "decks_created": 1}
        ]
        resp = client.get("/api/admin/usage/top-users")
        assert resp.status_code == 200
        assert resp.json()[0]["username"] == "a@x.com"

    def test_funnel(self, client, mock_service):
        mock_service.get_funnel.return_value = {
            "logins": 5,
            "users_who_logged_in": 3,
            "users_who_created_deck": 2,
            "decks_created": 2,
            "proxy": False,
        }
        assert client.get("/api/admin/usage/funnel").status_code == 200

    def test_retention(self, client, mock_service):
        mock_service.get_retention.return_value = []
        assert client.get("/api/admin/usage/retention").status_code == 200

    def test_heatmap(self, client, mock_service):
        mock_service.get_heatmap.return_value = {
            "matrix": [[0] * 24 for _ in range(7)],
            "max": 0,
        }
        assert client.get("/api/admin/usage/heatmap").status_code == 200

    def test_service_error_returns_500(self, client, mock_service):
        mock_service.get_summary.side_effect = RuntimeError("boom")
        assert client.get("/api/admin/usage/summary").status_code == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_admin_usage_routes.py -v`
Expected: FAIL — 404s (router not registered) / `ModuleNotFoundError` on patch target.

- [ ] **Step 3: Implement the router and register it**

```python
# src/api/routes/admin_usage.py
"""Admin usage-analytics endpoints (ungated, like the rest of /admin)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.api.services.usage_service import ALLOWED_WINDOWS, UsageService
from src.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/usage", tags=["admin-usage"])


def _validated_days(days: int) -> int:
    if days not in ALLOWED_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"days must be one of {sorted(ALLOWED_WINDOWS)}",
        )
    return days


def _handle(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage analytics error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute usage analytics",
        )


@router.get("/summary")
def get_summary(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_summary, db, days=days)


@router.get("/daily")
def get_daily(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_daily, db, days=days)


@router.get("/top-users")
def get_top_users(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_top_users, db, days=days)


@router.get("/funnel")
def get_funnel(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_funnel, db, days=days)


@router.get("/retention")
def get_retention(db: Session = Depends(get_db)):
    return _handle(UsageService().get_retention, db)


@router.get("/heatmap")
def get_heatmap(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_heatmap, db, days=days)
```

In `src/api/main.py`: add `admin_usage` to the existing `from src.api.routes import ...`
block and add `app.include_router(admin_usage.router)` next to
`app.include_router(admin.router)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_admin_usage_routes.py -v`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/admin_usage.py src/api/main.py tests/unit/test_admin_usage_routes.py
git commit -m "feat: /api/admin/usage analytics endpoints"
```

---

### Task 6: Feedback raw-list endpoint

**Files:**
- Modify: `src/api/services/feedback_service.py` (add `list_feedback` method)
- Modify: `src/api/routes/feedback.py` (add `GET /api/feedback/list`)
- Test: `tests/unit/test_feedback_list.py`

**Interfaces:**
- Produces: `FeedbackService.list_feedback(db, weeks: int = 12, category: str | None = None, severity: str | None = None, page: int = 1, page_size: int = 20) -> dict` returning `{"items": [{"id", "created_at" (ISO str), "category", "severity", "summary", "raw_conversation"}], "total": int, "page": int, "page_size": int}` — newest first.
- Endpoint: `GET /api/feedback/list?weeks=12&category=&severity=&page=1&page_size=20`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_feedback_list.py
"""Unit tests for the raw feedback list (service + route)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    import src.database.models.feedback  # noqa: F401

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()


def _add_feedback(db, category="Bug Report", severity="High", created_at=None, summary="s"):
    from src.database.models.feedback import FeedbackConversation

    db.add(
        FeedbackConversation(
            category=category,
            severity=severity,
            summary=summary,
            raw_conversation=[{"role": "user", "content": "hi"}],
            created_at=created_at or datetime.utcnow(),
        )
    )
    db.commit()


class TestListFeedbackService:
    def test_returns_items_newest_first(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        _add_feedback(db_session, summary="old", created_at=datetime.utcnow() - timedelta(days=2))
        _add_feedback(db_session, summary="new")
        result = FeedbackService().list_feedback(db_session)
        assert result["total"] == 2
        assert result["items"][0]["summary"] == "new"
        assert "raw_conversation" in result["items"][0]

    def test_filters_by_category_and_severity(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        _add_feedback(db_session, category="Bug Report", severity="High")
        _add_feedback(db_session, category="Feature Request", severity="Low")
        result = FeedbackService().list_feedback(db_session, category="Bug Report")
        assert result["total"] == 1
        assert result["items"][0]["category"] == "Bug Report"
        result = FeedbackService().list_feedback(db_session, severity="Low")
        assert result["total"] == 1

    def test_weeks_window_filters_old_items(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        _add_feedback(db_session, created_at=datetime.utcnow() - timedelta(weeks=20))
        _add_feedback(db_session)
        result = FeedbackService().list_feedback(db_session, weeks=12)
        assert result["total"] == 1

    def test_pagination(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        for i in range(25):
            _add_feedback(db_session, summary=f"item-{i}")
        page1 = FeedbackService().list_feedback(db_session, page=1, page_size=20)
        page2 = FeedbackService().list_feedback(db_session, page=2, page_size=20)
        assert page1["total"] == 25
        assert len(page1["items"]) == 20
        assert len(page2["items"]) == 5


class TestListFeedbackRoute:
    @pytest.fixture
    def client(self):
        from src.api.main import app

        return TestClient(app)

    @patch("src.api.routes.feedback.FeedbackService")
    def test_list_endpoint(self, mock_cls, client):
        mock_cls.return_value.list_feedback.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
        }
        resp = client.get("/api/feedback/list?weeks=4&category=Bug%20Report&page=1")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_invalid_page_rejected(self, client):
        assert client.get("/api/feedback/list?page=0").status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_feedback_list.py -v`
Expected: FAIL — `AttributeError: 'FeedbackService' object has no attribute 'list_feedback'` and 404 on the route.

- [ ] **Step 3: Implement service method and route**

Append to `FeedbackService` in `src/api/services/feedback_service.py`:

```python
    def list_feedback(
        self,
        db: Session,
        weeks: int = 12,
        category: str | None = None,
        severity: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """Paginated raw feedback conversations, newest first. Anonymous."""
        cutoff = datetime.utcnow() - timedelta(weeks=weeks)
        query = db.query(FeedbackConversation).filter(
            FeedbackConversation.created_at >= cutoff
        )
        if category:
            query = query.filter(FeedbackConversation.category == category)
        if severity:
            query = query.filter(FeedbackConversation.severity == severity)

        total = query.count()
        items = (
            query.order_by(FeedbackConversation.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [
                {
                    "id": item.id,
                    "created_at": item.created_at.isoformat(),
                    "category": item.category,
                    "severity": item.severity,
                    "summary": item.summary,
                    "raw_conversation": item.raw_conversation,
                }
                for item in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
```

(`FeedbackConversation`, `datetime`, `timedelta`, `Dict`, `Any` are already imported
in that module — verify and add any missing import.)

Append to `src/api/routes/feedback.py`:

```python
@router.get("/list")
def list_feedback(
    weeks: int = Query(default=12, ge=1, le=52),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        service = FeedbackService()
        return service.list_feedback(
            db=db,
            weeks=weeks,
            category=category,
            severity=severity,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"Feedback list error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list feedback",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_feedback_list.py tests/unit/test_feedback_service.py tests/unit/test_feedback_routes.py -v`
Expected: all PASS (existing feedback tests must not regress)

- [ ] **Step 5: Commit**

```bash
git add src/api/services/feedback_service.py src/api/routes/feedback.py tests/unit/test_feedback_list.py
git commit -m "feat: paginated raw feedback list endpoint (anonymous)"
```

---

### Task 7: Frontend API client methods

**Files:**
- Modify: `frontend/src/services/api.ts` (append to the `api` object, after the existing `getReportSummary` method ~line 1627)

**Interfaces:**
- Consumes: endpoint shapes from Tasks 5 & 6 (exact JSON above).
- Produces methods on `api`: `getUsageSummary(days)`, `getUsageDaily(days)`, `getUsageTopUsers(days)`, `getUsageFunnel(days)`, `getUsageRetention()`, `getUsageHeatmap(days)`, `listFeedback(params)`. Exported interfaces: `UsageSummary`, `UsageDailyRow`, `UsageTopUser`, `UsageFunnel`, `UsageRetentionRow`, `UsageHeatmap`, `FeedbackItem`, `FeedbackListResponse`.

- [ ] **Step 1: Add types and methods**

Add exported interfaces near the top-level type definitions of `api.ts` (or directly above the new methods):

```typescript
export interface UsageSummary {
  total_users_ever: number;
  total_decks_ever: number;
  window: {
    days: number;
    active_users: number;
    decks_created: number;
    avg_decks_per_active_user: number | null;
    logins: number;
  };
}

export interface UsageDailyRow {
  date: string;
  logins: number;
  logins_proxy: boolean;
  distinct_users: number;
  new_users: number;
  returning_users: number;
  decks_created: number;
  decks_retrieved: number;
  retrievals_proxy: number | null;
}

export interface UsageTopUser {
  username: string;
  logins: number;
  sessions_created: number;
  decks_created: number;
}

export interface UsageFunnel {
  logins: number;
  users_who_logged_in: number;
  users_who_created_deck: number;
  decks_created: number;
  proxy: boolean;
}

export interface UsageRetentionRow {
  week_start: string;
  active_users: number;
  retained_from_prev: number | null;
  retention_pct: number | null;
}

export interface UsageHeatmap {
  matrix: number[][];
  max: number;
}

export interface FeedbackItem {
  id: number;
  created_at: string;
  category: string;
  severity: string;
  summary: string;
  raw_conversation: Array<{ role: string; content: string }>;
}

export interface FeedbackListResponse {
  items: FeedbackItem[];
  total: number;
  page: number;
  page_size: number;
}
```

Inside the `api` object, after `getReportSummary`, add:

```typescript
  // --- Admin Usage Analytics ---

  async getUsageSummary(days: number = 7): Promise<UsageSummary> {
    const response = await fetch(`${API_BASE_URL}/api/admin/usage/summary?days=${days}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to fetch usage summary');
    return response.json();
  },

  async getUsageDaily(days: number = 7): Promise<{ history_boundary: string | null; days: UsageDailyRow[] }> {
    const response = await fetch(`${API_BASE_URL}/api/admin/usage/daily?days=${days}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to fetch daily usage');
    return response.json();
  },

  async getUsageTopUsers(days: number = 7): Promise<UsageTopUser[]> {
    const response = await fetch(`${API_BASE_URL}/api/admin/usage/top-users?days=${days}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to fetch top users');
    return response.json();
  },

  async getUsageFunnel(days: number = 7): Promise<UsageFunnel> {
    const response = await fetch(`${API_BASE_URL}/api/admin/usage/funnel?days=${days}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to fetch usage funnel');
    return response.json();
  },

  async getUsageRetention(): Promise<UsageRetentionRow[]> {
    const response = await fetch(`${API_BASE_URL}/api/admin/usage/retention`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to fetch retention');
    return response.json();
  },

  async getUsageHeatmap(days: number = 7): Promise<UsageHeatmap> {
    const response = await fetch(`${API_BASE_URL}/api/admin/usage/heatmap?days=${days}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to fetch heatmap');
    return response.json();
  },

  async listFeedback(params: {
    weeks?: number;
    category?: string;
    severity?: string;
    page?: number;
    pageSize?: number;
  } = {}): Promise<FeedbackListResponse> {
    const qs = new URLSearchParams();
    qs.set('weeks', String(params.weeks ?? 12));
    if (params.category) qs.set('category', params.category);
    if (params.severity) qs.set('severity', params.severity);
    qs.set('page', String(params.page ?? 1));
    qs.set('page_size', String(params.pageSize ?? 20));
    const response = await fetch(`${API_BASE_URL}/api/feedback/list?${qs.toString()}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to list feedback');
    return response.json();
  },
```

- [ ] **Step 2: Verify with a build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: frontend API client for usage analytics and feedback list"
```

---

### Task 8: `UsageDashboard` component + Usage tab

**Files:**
- Create: `frontend/src/components/Admin/UsageDashboard.tsx`
- Modify: `frontend/src/components/Admin/AdminPage.tsx` (add `usage` tab, make it default)
- Modify: `frontend/package.json` (add `recharts` via npm install)

**Interfaces:**
- Consumes: all `api.getUsage*` methods and types from Task 7.
- Produces: `export const UsageDashboard: React.FC` rendered as the default `/admin` tab.

**Note for implementer:** Before writing chart code, invoke the `dataviz` skill (Skill tool) and follow its guidance for colors/marks; keep to the layout below.

- [ ] **Step 1: Install recharts**

Run: `cd frontend && npm install recharts`
Expected: dependency added to `package.json` and `package-lock.json`.

- [ ] **Step 2: Create the component**

Layout (top→bottom): window selector · stat cards (Total Users Ever, Total Decks Ever, Active Users, Decks Created, Avg Decks/Active User, Logins) · Daily Logins line chart (dashed segment styling or annotation for pre-boundary proxy days, with a legend note when `logins_proxy` days exist) · Daily Distinct Users stacked bar (new vs returning) · Decks per Day bar · Funnel stat row (Logins → Users logged in → Users created deck → Decks) with "(session proxy)" note when `proxy` is true · Top Users table (Username, Logins, Sessions, Decks) · Retention table (Week, Active, Retained, %) · Activity heatmap (7×24 grid of cells shaded by count/max).

```tsx
// frontend/src/components/Admin/UsageDashboard.tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, Legend, CartesianGrid, ReferenceLine,
} from 'recharts';
import {
  api, UsageSummary, UsageDailyRow, UsageTopUser,
  UsageFunnel, UsageRetentionRow, UsageHeatmap,
} from '../../services/api';

const WINDOW_OPTIONS = [7, 14, 21, 28];
const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export const UsageDashboard: React.FC = () => {
  const [days, setDays] = useState(7);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [daily, setDaily] = useState<UsageDailyRow[]>([]);
  const [boundary, setBoundary] = useState<string | null>(null);
  const [topUsers, setTopUsers] = useState<UsageTopUser[]>([]);
  const [funnel, setFunnel] = useState<UsageFunnel | null>(null);
  const [retention, setRetention] = useState<UsageRetentionRow[]>([]);
  const [heatmap, setHeatmap] = useState<UsageHeatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, d, t, f, r, h] = await Promise.all([
        api.getUsageSummary(days),
        api.getUsageDaily(days),
        api.getUsageTopUsers(days),
        api.getUsageFunnel(days),
        api.getUsageRetention(),
        api.getUsageHeatmap(days),
      ]);
      setSummary(s);
      setDaily(d.days);
      setBoundary(d.history_boundary);
      setTopUsers(t);
      setFunnel(f);
      setRetention(r);
      setHeatmap(h);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const hasProxyDays = daily.some((r) => r.logins_proxy);
  const formatDate = (d: string) =>
    new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Usage</h2>
          <p className="text-sm text-gray-500">Who is using Tellr and how.</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="usage-days" className="text-sm text-gray-600">Window:</label>
          <select
            id="usage-days"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="text-sm border border-gray-300 rounded px-2 py-1"
          >
            {WINDOW_OPTIONS.map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading usage data...</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && summary && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <StatCard label="Total Users Ever" value={String(summary.total_users_ever)} />
            <StatCard label="Total Decks Ever" value={String(summary.total_decks_ever)} />
            <StatCard label={`Active Users (${days}d)`} value={String(summary.window.active_users)} />
            <StatCard label={`Decks (${days}d)`} value={String(summary.window.decks_created)} />
            <StatCard
              label="Decks / Active User"
              value={summary.window.avg_decks_per_active_user !== null
                ? String(summary.window.avg_decks_per_active_user) : '-'}
            />
            <StatCard label={`Logins (${days}d)`} value={String(summary.window.logins)} />
          </div>

          <ChartSection
            title="Daily Logins"
            subtitle={hasProxyDays
              ? 'Days before event tracking use sessions-created as a proxy (dashed).'
              : undefined}
          >
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tickFormatter={formatDate} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip labelFormatter={formatDate} />
                <Line type="monotone" dataKey="logins" stroke="#2563eb" strokeWidth={2} dot={false} name="Logins" />
                {boundary && (
                  <ReferenceLine x={boundary} stroke="#9ca3af" strokeDasharray="4 4"
                    label={{ value: 'event tracking enabled', fontSize: 11, fill: '#6b7280' }} />
                )}
              </LineChart>
            </ResponsiveContainer>
          </ChartSection>

          <ChartSection title="Daily Distinct Users (new vs returning)">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tickFormatter={formatDate} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip labelFormatter={formatDate} />
                <Legend />
                <Bar dataKey="returning_users" stackId="u" fill="#2563eb" name="Returning" />
                <Bar dataKey="new_users" stackId="u" fill="#10b981" name="New" />
              </BarChart>
            </ResponsiveContainer>
          </ChartSection>

          <ChartSection title="Decks Generated per Day">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tickFormatter={formatDate} fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
                <Tooltip labelFormatter={formatDate} />
                <Bar dataKey="decks_created" fill="#7c3aed" name="Decks" />
              </BarChart>
            </ResponsiveContainer>
          </ChartSection>

          {funnel && (
            <ChartSection
              title={`Funnel (${days}d)`}
              subtitle={funnel.proxy ? 'No login events in window — using session creations as proxy.' : undefined}
            >
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label="Logins" value={String(funnel.logins)} />
                <StatCard label="Users Logged In" value={String(funnel.users_who_logged_in)} />
                <StatCard label="Users Created a Deck" value={String(funnel.users_who_created_deck)} />
                <StatCard label="Decks Created" value={String(funnel.decks_created)} />
              </div>
            </ChartSection>
          )}

          <ChartSection title={`Top Users (${days}d)`}>
            {topUsers.length === 0
              ? <p className="text-sm text-gray-500">No user activity in this window.</p>
              : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-left text-gray-600">
                      <th className="pb-2 pr-4 font-medium">User</th>
                      <th className="pb-2 pr-4 font-medium text-right">Logins</th>
                      <th className="pb-2 pr-4 font-medium text-right">Sessions</th>
                      <th className="pb-2 font-medium text-right">Decks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topUsers.map((u) => (
                      <tr key={u.username} className="border-b border-gray-100">
                        <td className="py-2 pr-4 text-gray-800">{u.username}</td>
                        <td className="py-2 pr-4 text-right text-gray-700">{u.logins}</td>
                        <td className="py-2 pr-4 text-right text-gray-700">{u.sessions_created}</td>
                        <td className="py-2 text-right text-gray-700">{u.decks_created}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </ChartSection>

          <ChartSection title="Weekly Retention (last 8 weeks)">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-600">
                  <th className="pb-2 pr-4 font-medium">Week</th>
                  <th className="pb-2 pr-4 font-medium text-right">Active Users</th>
                  <th className="pb-2 pr-4 font-medium text-right">Retained</th>
                  <th className="pb-2 font-medium text-right">Retention %</th>
                </tr>
              </thead>
              <tbody>
                {retention.map((w) => (
                  <tr key={w.week_start} className="border-b border-gray-100">
                    <td className="py-2 pr-4 text-gray-800">{formatDate(w.week_start)}</td>
                    <td className="py-2 pr-4 text-right text-gray-700">{w.active_users}</td>
                    <td className="py-2 pr-4 text-right text-gray-700">{w.retained_from_prev ?? '-'}</td>
                    <td className="py-2 text-right text-gray-700">
                      {w.retention_pct !== null ? `${w.retention_pct}%` : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ChartSection>

          {heatmap && (
            <ChartSection title={`Activity Heatmap (${days}d, UTC)`}>
              <div className="overflow-x-auto">
                <table className="text-xs border-collapse">
                  <thead>
                    <tr>
                      <th className="pr-2 text-left text-gray-500 font-normal" />
                      {Array.from({ length: 24 }, (_, h) => (
                        <th key={h} className="px-1 text-gray-400 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {heatmap.matrix.map((row, dayIdx) => (
                      <tr key={dayIdx}>
                        <td className="pr-2 text-gray-500">{DAY_LABELS[dayIdx]}</td>
                        {row.map((count, hour) => (
                          <td
                            key={hour}
                            title={`${DAY_LABELS[dayIdx]} ${hour}:00 — ${count} events`}
                            className="w-5 h-5 border border-white rounded-sm"
                            style={{
                              backgroundColor: count === 0
                                ? '#f3f4f6'
                                : `rgba(37, 99, 235, ${0.15 + 0.85 * (count / Math.max(heatmap.max, 1))})`,
                            }}
                          />
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ChartSection>
          )}
        </>
      )}
    </div>
  );
};

const StatCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
    <p className="mt-1 text-xl font-semibold text-gray-900">{value}</p>
  </div>
);

const ChartSection: React.FC<{ title: string; subtitle?: string; children: React.ReactNode }> = (
  { title, subtitle, children },
) => (
  <section className="bg-white rounded-lg shadow-sm border border-gray-200">
    <div className="px-6 py-4 border-b border-gray-200">
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
    </div>
    <div className="p-6">{children}</div>
  </section>
);
```

- [ ] **Step 3: Add the Usage tab to AdminPage (default tab)**

In `frontend/src/components/Admin/AdminPage.tsx`:
- `import { UsageDashboard } from './UsageDashboard';`
- Change `type TabId = 'feedback' | ...` to `type TabId = 'usage' | 'feedback' | 'google_slides' | 'slide_style' | 'judge';`
- Change initial state to `useState<TabId>('usage')`.
- Add a **Usage** tab button before the Feedback button (copy the existing button markup, with `aria-controls="usage-panel"` / `id="usage-tab"` / label `Usage`).
- Add the panel before the feedback panel:

```tsx
        <div
          role="tabpanel"
          id="usage-panel"
          aria-labelledby="usage-tab"
          hidden={activeTab !== 'usage'}
          className={activeTab !== 'usage' ? 'sr-only' : ''}
        >
          <UsageDashboard />
        </div>
```

- Update the header description to mention usage analytics, e.g. `Usage analytics, feedback reports, Google Slides, slide style defaults, and LLM judge backend.`

- [ ] **Step 4: Verify with a build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Admin/UsageDashboard.tsx frontend/src/components/Admin/AdminPage.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat: Usage tab with charts on /admin (recharts)"
```

---

### Task 9: FeedbackDashboard revamp — raw feedback browser, demoted lazy AI summary

**Files:**
- Modify: `frontend/src/components/Feedback/FeedbackDashboard.tsx`

**Interfaces:**
- Consumes: `api.listFeedback(...)` + `FeedbackItem` / `FeedbackListResponse` (Task 7); existing `api.getReportStats` / `api.getReportSummary`.
- Produces: reworked `FeedbackDashboard` — survey cards + weekly table unchanged; new Feedback Browser section; AI summary collapsed & lazy.

- [ ] **Step 1: Rework the component**

Keep: `WeekStats`/`Totals`/`Usage`/`FeedbackSummary` interfaces, `loadStats`, the totals cards, and the Weekly Survey Stats section exactly as they are. Make these changes:

1. **Remove** the eager `useEffect(() => { loadSummary(); }, [loadSummary]);` — the summary must only load when its section is expanded.
2. **Add** feedback-browser state and loading:

```tsx
import { api, FeedbackItem } from '../../services/api';

const CATEGORIES = ['Bug Report', 'Feature Request', 'UX Issue', 'Performance', 'Content Quality', 'Other'];
const SEVERITIES = ['Low', 'Medium', 'High'];
const PAGE_SIZE = 20;

// inside the component:
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState('');
  const [severity, setSeverity] = useState('');
  const [browserWeeks, setBrowserWeeks] = useState(12);
  const [browserLoading, setBrowserLoading] = useState(true);
  const [browserError, setBrowserError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryLoaded, setSummaryLoaded] = useState(false);

  const loadFeedback = useCallback(async () => {
    setBrowserLoading(true);
    setBrowserError(null);
    try {
      const data = await api.listFeedback({
        weeks: browserWeeks,
        category: category || undefined,
        severity: severity || undefined,
        page,
        pageSize: PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setBrowserError(err instanceof Error ? err.message : 'Failed to load feedback');
    } finally {
      setBrowserLoading(false);
    }
  }, [browserWeeks, category, severity, page]);

  useEffect(() => { loadFeedback(); }, [loadFeedback]);
  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [browserWeeks, category, severity]);

  const openSummary = () => {
    setSummaryOpen((open) => !open);
    if (!summaryLoaded) {
      setSummaryLoaded(true);
      loadSummary();
    }
  };
```

3. **Add the Feedback Browser section** between the Weekly Survey Stats section and the AI Summary section:

```tsx
      {/* Raw Feedback Browser */}
      <section className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900">Feedback Browser</h2>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1" aria-label="Filter by category">
              <option value="">All categories</option>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1" aria-label="Filter by severity">
              <option value="">All severities</option>
              {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={browserWeeks} onChange={(e) => setBrowserWeeks(Number(e.target.value))}
              className="border border-gray-300 rounded px-2 py-1" aria-label="Weeks window">
              {[4, 8, 12, 26, 52].map((w) => <option key={w} value={w}>{w} weeks</option>)}
            </select>
          </div>
        </div>

        <div className="p-6">
          {browserLoading && <p className="text-sm text-gray-500">Loading feedback...</p>}
          {browserError && <p className="text-sm text-red-600">{browserError}</p>}
          {!browserLoading && !browserError && items.length === 0 && (
            <p className="text-sm text-gray-500">No feedback in this window.</p>
          )}

          {!browserLoading && !browserError && items.length > 0 && (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-gray-600">
                    <th className="pb-2 pr-4 font-medium">Date</th>
                    <th className="pb-2 pr-4 font-medium">Category</th>
                    <th className="pb-2 pr-4 font-medium">Severity</th>
                    <th className="pb-2 font-medium">Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <React.Fragment key={item.id}>
                      <tr
                        className="border-b border-gray-100 cursor-pointer hover:bg-gray-50"
                        onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
                      >
                        <td className="py-2 pr-4 text-gray-700 whitespace-nowrap align-top">
                          {new Date(item.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
                        </td>
                        <td className="py-2 pr-4 align-top">
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
                            {item.category}
                          </span>
                        </td>
                        <td className="py-2 pr-4 align-top">
                          <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                            item.severity === 'High' ? 'bg-red-50 text-red-700'
                              : item.severity === 'Medium' ? 'bg-amber-50 text-amber-700'
                              : 'bg-gray-100 text-gray-600'
                          }`}>
                            {item.severity}
                          </span>
                        </td>
                        <td className="py-2 text-gray-800 align-top">{item.summary}</td>
                      </tr>
                      {expandedId === item.id && (
                        <tr className="border-b border-gray-100 bg-gray-50">
                          <td colSpan={4} className="p-4">
                            <h4 className="text-xs font-medium text-gray-500 uppercase mb-2">Full conversation</h4>
                            <div className="space-y-2">
                              {item.raw_conversation.map((msg, i) => (
                                <div key={i} className={`text-sm rounded-lg px-3 py-2 max-w-3xl ${
                                  msg.role === 'user' ? 'bg-blue-50 text-blue-900' : 'bg-white border border-gray-200 text-gray-700'
                                }`}>
                                  <span className="text-xs font-semibold uppercase text-gray-400 mr-2">{msg.role}</span>
                                  {msg.content}
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>

              <div className="flex items-center justify-between mt-4 text-sm text-gray-600">
                <span>{total} item{total === 1 ? '' : 's'}</span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                    className="px-3 py-1 border border-gray-300 rounded disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <span>Page {page} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}</span>
                  <button
                    disabled={page >= Math.ceil(total / PAGE_SIZE)}
                    onClick={() => setPage((p) => p + 1)}
                    className="px-3 py-1 border border-gray-300 rounded disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
```

4. **Demote the AI summary**: wrap the existing AI Summary section header in a
toggle button that calls `openSummary()`, render the body only when
`summaryOpen`, and change the section heading to `AI Summary (optional)`.
The weeks `<select>` stays inside the expanded body; changing it re-calls
`loadSummary()` (existing behavior via the `summaryWeeks` dependency — keep the
`useEffect` but gate it: `useEffect(() => { if (summaryLoaded) loadSummary(); }, [loadSummary, summaryLoaded]);`).

```tsx
        <button
          type="button"
          onClick={openSummary}
          className="w-full px-6 py-4 flex items-center justify-between text-left"
          aria-expanded={summaryOpen}
        >
          <h2 className="text-lg font-semibold text-gray-900">AI Summary (optional)</h2>
          <span className="text-gray-400 text-sm">{summaryOpen ? 'Hide' : 'Show'}</span>
        </button>
```

- [ ] **Step 2: Verify with a build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Feedback/FeedbackDashboard.tsx
git commit -m "feat: raw feedback browser; demote AI summary to lazy collapsed section"
```

---

### Task 10: Integration — full test suite, build, docs

**Files:**
- Modify: `docs/technical/feedback-system.md` (dashboard section update + pointer)
- Create: `docs/technical/usage-analytics.md`

- [ ] **Step 1: Run the full backend suite**

Run: `pytest tests/unit -q && pytest tests/integration -q`
Expected: all PASS. Fix any regressions before proceeding (common suspects: middleware wiring in `main.py` affecting unrelated route tests — event writes must stay swallow-all).

- [ ] **Step 2: Build the frontend**

Run: `cd frontend && npm run build`
Expected: success.

- [ ] **Step 3: Write `docs/technical/usage-analytics.md`**

Document (following the structure of `docs/technical/feedback-system.md`): the `usage_events` table and event semantics (30-min visit dedup, deck dedup), capture sites, the six `/api/admin/usage/*` endpoints with example responses, metric definitions (copy from the spec's "Metric definitions" section), the history-boundary/proxy semantics, and the warning that `user_sessions` is durable history — `POST /api/sessions/cleanup` must never be scheduled.

- [ ] **Step 4: Update `docs/technical/feedback-system.md`**

In the "Feedback Dashboard (Hidden Page)" section: note the admin page now defaults to the Usage tab (cross-reference `usage-analytics.md`), describe the Feedback tab's raw feedback browser + demoted lazy AI summary, and add `GET /api/feedback/list` to the API table.

- [ ] **Step 5: Commit**

```bash
git add docs/technical/usage-analytics.md docs/technical/feedback-system.md
git commit -m "docs: usage analytics technical doc; update feedback-system doc"
```

---

### Task 11: Dev deploy on a prod-Lakebase branch + Playwright verification

This task runs in the main session (not a subagent) — it needs workspace credentials
and the deploy loop.

- [ ] **Step 1: Deploy** — invoke the `deploy-tellr-dev` skill and follow it:
  publish a `.devN` via `gh workflow run publish-dev.yml`, then
  `./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>`
  (this creates/uses a fork of the prod Lakebase branch per the skill).

- [ ] **Step 2: Verify with Playwright** — open the deployed app's `/admin` URL
  (authenticated via the local browser profile / OAuth). Check against the spec:
  - Usage tab is default and renders: 6 stat cards, 3 daily charts, funnel, top-users
    table, retention table, heatmap; window selector switches 7/14/21/28 and data reloads.
  - Values are plausible against the branch DB (e.g. `total_users_ever` ≥ distinct
    `created_by` in `user_sessions`).
  - Feedback tab: browser table renders with filters + expandable conversations;
    AI summary collapsed by default and loads only on expand.
  - Fresh events work: hit the app (login event), open a deck (deck_retrieved), then
    confirm today's counts tick up on refresh.
- [ ] **Step 3: Iterate** on any mismatch until the page matches the spec.
  If the deployed app cannot be reached/authenticated, STOP and report that manual
  review is needed.
