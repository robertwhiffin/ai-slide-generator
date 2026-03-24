"""Tests for missing permission checks added to existing endpoints.

Task 6b: Validate that get_session_slides, export_session, editing lock
endpoints, comment read endpoints, and save_from_session all enforce
deck-based permission checks.

Uses in-memory SQLite with monkeypatched context functions (same pattern
as test_deck_permission_routes.py).
"""

import asyncio
import pytest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — register all models with Base
from src.core.database import Base
from src.core.permission_context import PermissionContext
from src.database.models import UserSession
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile_contributor import PermissionLevel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """In-memory SQLite session for unit tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def owner_session(db):
    """A root session created by 'owner@test.com'."""
    s = UserSession(
        session_id="sess-owner-1",
        created_by="owner@test.com",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture
def contributor_session(db, owner_session):
    """A contributor session parented to owner_session."""
    s = UserSession(
        session_id="sess-contrib-1",
        created_by="contrib@test.com",
        parent_session_id=owner_session.id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture
def deck_contributor_view(db, owner_session):
    """DeckContributor giving 'viewer@test.com' CAN_VIEW on owner_session."""
    dc = DeckContributor(
        user_session_id=owner_session.id,
        identity_type="USER",
        identity_id="viewer-uid",
        identity_name="viewer@test.com",
        permission_level=PermissionLevel.CAN_VIEW.value,
        created_by="owner@test.com",
    )
    db.add(dc)
    db.commit()
    db.refresh(dc)
    return dc


@pytest.fixture
def deck_contributor_edit(db, owner_session):
    """DeckContributor giving 'editor@test.com' CAN_EDIT on owner_session."""
    dc = DeckContributor(
        user_session_id=owner_session.id,
        identity_type="USER",
        identity_id="editor-uid",
        identity_name="editor@test.com",
        permission_level=PermissionLevel.CAN_EDIT.value,
        created_by="owner@test.com",
    )
    db.add(dc)
    db.commit()
    db.refresh(dc)
    return dc


def _make_session_info(session_obj, is_contributor=False, parent_id=None):
    """Helper to build a session_info dict mimicking session_manager.get_session()."""
    return {
        "id": session_obj.id,
        "session_id": session_obj.session_id,
        "created_by": session_obj.created_by,
        "is_contributor_session": is_contributor,
        "parent_session_internal_id": parent_id,
    }


def _stranger_ctx():
    return PermissionContext(user_id="stranger-uid", user_name="stranger@test.com")


def _viewer_ctx():
    return PermissionContext(user_id="viewer-uid", user_name="viewer@test.com")


def _editor_ctx():
    return PermissionContext(user_id="editor-uid", user_name="editor@test.com")


def _owner_ctx():
    return PermissionContext(user_id="owner-uid", user_name="owner@test.com")


def _fake_db_session(db):
    """Return a context manager that yields the test db session."""
    @contextmanager
    def _ctx():
        yield db
    return _ctx


def _run(coro):
    """Run a coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# 1. get_session_slides — requires CAN_VIEW
# ===========================================================================


class TestGetSessionSlidesPermission:
    """get_session_slides must enforce require_view_deck."""

    def test_stranger_blocked(self, db, owner_session):
        """Stranger with no deck permission should get 403."""
        from src.api.routes.sessions import get_session_slides
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)
        mock_mgr.get_slide_deck.return_value = None

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(get_session_slides(owner_session.session_id))
            assert exc_info.value.status_code == 403

    def test_viewer_allowed(self, db, owner_session, deck_contributor_view):
        """Viewer with CAN_VIEW should be allowed."""
        from src.api.routes.sessions import get_session_slides

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)
        mock_mgr.get_slide_deck.return_value = None

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_viewer_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            result = _run(get_session_slides(owner_session.session_id))
            assert "session_id" in result

    def test_owner_allowed(self, db, owner_session):
        """Owner should be allowed (creator = CAN_MANAGE)."""
        from src.api.routes.sessions import get_session_slides

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)
        mock_mgr.get_slide_deck.return_value = None

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_owner_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            result = _run(get_session_slides(owner_session.session_id))
            assert "session_id" in result


# ===========================================================================
# 2. export_session — requires CAN_VIEW
# ===========================================================================


class TestExportSessionPermission:
    """export_session must enforce require_view_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.sessions import export_session
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(export_session(owner_session.session_id))
            assert exc_info.value.status_code == 403

    def test_viewer_allowed(self, db, owner_session, deck_contributor_view):
        from src.api.routes.sessions import export_session

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)
        mock_mgr.get_messages.return_value = []
        mock_mgr.get_slide_deck.return_value = None

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_viewer_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)), \
             patch("src.api.routes.sessions.Path"):
            import builtins
            with patch.object(builtins, "open", MagicMock()):
                result = _run(export_session(owner_session.session_id))
            assert result["status"] == "exported"


# ===========================================================================
# 3. Editing lock endpoints
# ===========================================================================


class TestAcquireEditingLockPermission:
    """acquire_editing_lock must enforce require_edit_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.sessions import acquire_editing_lock
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(acquire_editing_lock(owner_session.session_id))
            assert exc_info.value.status_code == 403

    def test_viewer_blocked(self, db, owner_session, deck_contributor_view):
        """Viewer (CAN_VIEW) cannot acquire edit lock."""
        from src.api.routes.sessions import acquire_editing_lock
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_current_user", return_value="viewer@test.com"), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_viewer_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(acquire_editing_lock(owner_session.session_id))
            assert exc_info.value.status_code == 403

    def test_editor_allowed(self, db, owner_session, deck_contributor_edit):
        from src.api.routes.sessions import acquire_editing_lock

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)
        mock_mgr.acquire_editing_lock.return_value = {"locked": True}

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_current_user", return_value="editor@test.com"), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_editor_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            result = _run(acquire_editing_lock(owner_session.session_id))
            assert result == {"locked": True}


class TestReleaseEditingLockPermission:
    """release_editing_lock must enforce require_edit_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.sessions import release_editing_lock
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(release_editing_lock(owner_session.session_id))
            assert exc_info.value.status_code == 403


class TestGetEditingLockStatusPermission:
    """get_editing_lock_status must enforce require_view_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.sessions import get_editing_lock_status
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(get_editing_lock_status(owner_session.session_id))
            assert exc_info.value.status_code == 403

    def test_viewer_allowed(self, db, owner_session, deck_contributor_view):
        from src.api.routes.sessions import get_editing_lock_status

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)
        mock_mgr.get_editing_lock_status.return_value = {"locked": False}

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_viewer_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            result = _run(get_editing_lock_status(owner_session.session_id))
            assert result == {"locked": False}


class TestHeartbeatEditingLockPermission:
    """heartbeat_editing_lock must enforce require_edit_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.sessions import heartbeat_editing_lock
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.sessions.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.sessions.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.sessions.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.sessions.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(heartbeat_editing_lock(owner_session.session_id))
            assert exc_info.value.status_code == 403


# ===========================================================================
# 4. Comment endpoints — require_view_deck
# ===========================================================================


class TestListCommentsPermission:
    """list_comments must enforce require_view_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.comments import list_comments
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.comments.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.comments.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.comments.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.comments.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(list_comments(session_id=owner_session.session_id))
            assert exc_info.value.status_code == 403

    def test_viewer_allowed(self, db, owner_session, deck_contributor_view):
        from src.api.routes.comments import list_comments

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)
        mock_mgr.list_comments.return_value = []

        with patch("src.api.routes.comments.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.comments.get_current_user", return_value="viewer@test.com"), \
             patch("src.api.routes.comments.get_permission_context", return_value=_viewer_ctx()), \
             patch("src.api.routes.comments.get_db_session", _fake_db_session(db)):
            result = _run(list_comments(session_id=owner_session.session_id))
            assert "comments" in result


class TestAddCommentPermission:
    """add_comment must enforce require_view_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.comments import add_comment, AddCommentRequest
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        req = AddCommentRequest(
            session_id=owner_session.session_id,
            slide_id="slide-1",
            content="test comment",
        )

        with patch("src.api.routes.comments.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.comments.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.comments.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.comments.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(add_comment(req))
            assert exc_info.value.status_code == 403


class TestMentionableUsersPermission:
    """mentionable_users must enforce require_view_deck."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.comments import mentionable_users
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.comments.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.comments.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.comments.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.comments.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(mentionable_users(session_id=owner_session.session_id))
            assert exc_info.value.status_code == 403


class TestListMentionsPermission:
    """list_mentions must enforce require_view_deck when session_id is given."""

    def test_stranger_blocked_with_session_id(self, db, owner_session):
        from src.api.routes.comments import list_mentions
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = _make_session_info(owner_session)

        with patch("src.api.routes.comments.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.comments.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.comments.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.comments.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(list_mentions(session_id=owner_session.session_id))
            assert exc_info.value.status_code == 403

    def test_no_session_id_skips_check(self, db):
        """When no session_id is provided, no deck check needed."""
        from src.api.routes.comments import list_mentions

        mock_mgr = MagicMock()
        mock_mgr.list_mentions.return_value = []

        with patch("src.api.routes.comments.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.comments.get_current_user", return_value="stranger@test.com"):
            result = _run(list_mentions(session_id=None))
            assert "mentions" in result


# ===========================================================================
# 5. save_from_session — require deck access or being session creator
# ===========================================================================


class TestSaveFromSessionPermission:
    """save_from_session must check caller is session creator or has deck access."""

    def test_stranger_blocked(self, db, owner_session):
        from src.api.routes.profiles import save_from_session, SaveProfileRequest
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        session_info = _make_session_info(owner_session)
        session_info["agent_config"] = None
        mock_mgr.get_session.return_value = session_info

        req = SaveProfileRequest(name="test-profile")

        with patch("src.api.routes.profiles.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.profiles.get_permission_context", return_value=_stranger_ctx()), \
             patch("src.api.routes.profiles.get_db_session", _fake_db_session(db)):
            with pytest.raises(HTTPException) as exc_info:
                _run(save_from_session(owner_session.session_id, req))
            assert exc_info.value.status_code == 403

    def test_owner_allowed(self, db, owner_session):
        """Session creator should be allowed to save profile."""
        from src.api.routes.profiles import save_from_session, SaveProfileRequest
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        session_info = _make_session_info(owner_session)
        session_info["agent_config"] = None
        mock_mgr.get_session.return_value = session_info

        req = SaveProfileRequest(name="test-profile")

        with patch("src.api.routes.profiles.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.profiles.get_permission_context", return_value=_owner_ctx()), \
             patch("src.api.routes.profiles.get_db_session", _fake_db_session(db)):
            # Should NOT raise 403 — may raise other errors due to mocking,
            # but the permission check itself should pass
            try:
                _run(save_from_session(owner_session.session_id, req))
            except HTTPException as e:
                assert e.status_code != 403, f"Owner should not get 403, got: {e.detail}"

    def test_deck_contributor_allowed(self, db, owner_session, deck_contributor_view):
        """User with any deck permission should be allowed."""
        from src.api.routes.profiles import save_from_session, SaveProfileRequest
        from fastapi import HTTPException

        mock_mgr = MagicMock()
        session_info = _make_session_info(owner_session)
        session_info["agent_config"] = None
        mock_mgr.get_session.return_value = session_info

        req = SaveProfileRequest(name="test-profile")

        with patch("src.api.routes.profiles.get_session_manager", return_value=mock_mgr), \
             patch("src.api.routes.profiles.get_permission_context", return_value=_viewer_ctx()), \
             patch("src.api.routes.profiles.get_db_session", _fake_db_session(db)):
            try:
                _run(save_from_session(owner_session.session_id, req))
            except HTTPException as e:
                assert e.status_code != 403, f"Deck contributor should not get 403, got: {e.detail}"
