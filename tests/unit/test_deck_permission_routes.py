"""Tests for deck-centric permission checks in session/chat/slides/comments routes.

Validates that route-level permission helpers use DeckContributor (deck-based)
instead of ConfigProfileContributor (profile-based) for access control.

Uses in-memory SQLite with StaticPool and monkeypatches context functions.
"""

import pytest
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
    """A contributor session parented to owner_session, created by 'contrib@test.com'."""
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
def deck_contributor_edit(db, owner_session):
    """A DeckContributor giving 'editor@test.com' CAN_EDIT on owner_session."""
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


@pytest.fixture
def deck_contributor_view(db, owner_session):
    """A DeckContributor giving 'viewer@test.com' CAN_VIEW on owner_session."""
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


# ---------------------------------------------------------------------------
# Test _get_session_permission in sessions.py
# ---------------------------------------------------------------------------


class TestSessionsGetSessionPermission:
    """sessions.py _get_session_permission should use deck-based permissions."""

    def test_creator_gets_can_manage(self, db, owner_session):
        """Session creator should get CAN_MANAGE via deck permission (creator check)."""
        from src.api.routes.sessions import _get_session_permission

        session_info = {
            "id": owner_session.id,
            "session_id": owner_session.session_id,
            "created_by": "owner@test.com",
            "is_contributor_session": False,
            "parent_session_internal_id": None,
        }

        ctx = PermissionContext(user_id="owner-uid", user_name="owner@test.com")
        with patch("src.api.routes.sessions.get_permission_context", return_value=ctx), \
             patch("src.api.routes.sessions.get_current_user", return_value="owner@test.com"):
            has_access, perm = _get_session_permission(session_info, db)

        assert has_access is True
        assert perm == PermissionLevel.CAN_MANAGE

    def test_deck_contributor_gets_edit(self, db, owner_session, deck_contributor_edit):
        """User with CAN_EDIT DeckContributor entry should get CAN_EDIT."""
        from src.api.routes.sessions import _get_session_permission

        session_info = {
            "id": owner_session.id,
            "session_id": owner_session.session_id,
            "created_by": "owner@test.com",
            "is_contributor_session": False,
            "parent_session_internal_id": None,
        }

        ctx = PermissionContext(user_id="editor-uid", user_name="editor@test.com")
        with patch("src.api.routes.sessions.get_permission_context", return_value=ctx), \
             patch("src.api.routes.sessions.get_current_user", return_value="editor@test.com"):
            has_access, perm = _get_session_permission(session_info, db)

        assert has_access is True
        assert perm == PermissionLevel.CAN_EDIT

    def test_stranger_gets_no_access(self, db, owner_session):
        """User with no DeckContributor entry and not creator should get no access."""
        from src.api.routes.sessions import _get_session_permission

        session_info = {
            "id": owner_session.id,
            "session_id": owner_session.session_id,
            "created_by": "owner@test.com",
            "is_contributor_session": False,
            "parent_session_internal_id": None,
        }

        ctx = PermissionContext(user_id="stranger-uid", user_name="stranger@test.com")
        with patch("src.api.routes.sessions.get_permission_context", return_value=ctx), \
             patch("src.api.routes.sessions.get_current_user", return_value="stranger@test.com"):
            has_access, perm = _get_session_permission(session_info, db)

        assert has_access is False
        assert perm is None

    def test_contributor_session_checks_parent(self, db, owner_session, contributor_session, deck_contributor_edit):
        """Contributor session should check deck permission on parent session."""
        from src.api.routes.sessions import _get_session_permission

        session_info = {
            "id": contributor_session.id,
            "session_id": contributor_session.session_id,
            "created_by": "contrib@test.com",
            "is_contributor_session": True,
            "parent_session_internal_id": owner_session.id,
        }

        ctx = PermissionContext(user_id="editor-uid", user_name="editor@test.com")
        with patch("src.api.routes.sessions.get_permission_context", return_value=ctx), \
             patch("src.api.routes.sessions.get_current_user", return_value="editor@test.com"):
            has_access, perm = _get_session_permission(session_info, db)

        assert has_access is True
        assert perm == PermissionLevel.CAN_EDIT


# ---------------------------------------------------------------------------
# Test _get_session_permission in slides.py (parallel copy)
# ---------------------------------------------------------------------------


class TestSlidesGetSessionPermission:
    """slides.py _get_session_permission should use deck-based permissions."""

    def test_creator_gets_can_manage(self, db, owner_session):
        """Session creator gets CAN_MANAGE for slides."""
        from src.api.routes.slides import _get_session_permission

        mock_session_info = {
            "id": owner_session.id,
            "session_id": owner_session.session_id,
            "created_by": "owner@test.com",
            "is_contributor_session": False,
            "parent_session_internal_id": None,
        }

        ctx = PermissionContext(user_id="owner-uid", user_name="owner@test.com")
        with patch("src.api.routes.slides.get_permission_context", return_value=ctx), \
             patch("src.api.routes.slides.get_current_user", return_value="owner@test.com"), \
             patch("src.api.routes.slides.get_session_manager") as mock_mgr:
            mock_mgr.return_value.get_session.return_value = mock_session_info
            has_access, perm = _get_session_permission(owner_session.session_id, db)

        assert has_access is True
        assert perm == PermissionLevel.CAN_MANAGE

    def test_stranger_gets_no_access(self, db, owner_session):
        """Stranger gets no access to slides."""
        from src.api.routes.slides import _get_session_permission

        mock_session_info = {
            "id": owner_session.id,
            "session_id": owner_session.session_id,
            "created_by": "owner@test.com",
            "is_contributor_session": False,
            "parent_session_internal_id": None,
        }

        ctx = PermissionContext(user_id="stranger-uid", user_name="stranger@test.com")
        with patch("src.api.routes.slides.get_permission_context", return_value=ctx), \
             patch("src.api.routes.slides.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.slides.get_session_manager") as mock_mgr:
            mock_mgr.return_value.get_session.return_value = mock_session_info
            has_access, perm = _get_session_permission(owner_session.session_id, db)

        assert has_access is False
        assert perm is None

    def test_deck_contributor_gets_edit(self, db, owner_session, deck_contributor_edit):
        """Deck contributor with CAN_EDIT gets edit access to slides."""
        from src.api.routes.slides import _get_session_permission

        mock_session_info = {
            "id": owner_session.id,
            "session_id": owner_session.session_id,
            "created_by": "owner@test.com",
            "is_contributor_session": False,
            "parent_session_internal_id": None,
        }

        ctx = PermissionContext(user_id="editor-uid", user_name="editor@test.com")
        with patch("src.api.routes.slides.get_permission_context", return_value=ctx), \
             patch("src.api.routes.slides.get_current_user", return_value="editor@test.com"), \
             patch("src.api.routes.slides.get_session_manager") as mock_mgr:
            mock_mgr.return_value.get_session.return_value = mock_session_info
            has_access, perm = _get_session_permission(owner_session.session_id, db)

        assert has_access is True
        assert perm == PermissionLevel.CAN_EDIT


# ---------------------------------------------------------------------------
# Test _check_chat_permission in chat.py
# ---------------------------------------------------------------------------


class TestChatCheckPermission:
    """chat.py _check_chat_permission should use deck-based permissions."""

    def test_owner_can_chat(self, db, owner_session):
        """Owner of root session can always chat."""
        from src.api.routes.chat import _check_chat_permission

        mock_session_info = {
            "id": owner_session.id,
            "session_id": owner_session.session_id,
            "created_by": "owner@test.com",
            "is_contributor_session": False,
            "parent_session_internal_id": None,
        }

        ctx = PermissionContext(user_id="owner-uid", user_name="owner@test.com")
        with patch("src.api.routes.chat.get_permission_context", return_value=ctx), \
             patch("src.api.routes.chat.get_current_user", return_value="owner@test.com"), \
             patch("src.api.routes.chat.get_session_manager") as mock_mgr:
            mock_mgr.return_value.get_session.return_value = mock_session_info
            # Should not raise
            _check_chat_permission(owner_session.session_id, db)

    def test_contributor_with_edit_can_chat(self, db, owner_session, contributor_session, deck_contributor_edit):
        """Contributor with CAN_EDIT on parent deck can chat in their contributor session."""
        from src.api.routes.chat import _check_chat_permission

        mock_session_info = {
            "id": contributor_session.id,
            "session_id": contributor_session.session_id,
            "created_by": "editor@test.com",
            "is_contributor_session": True,
            "parent_session_internal_id": owner_session.id,
        }

        ctx = PermissionContext(user_id="editor-uid", user_name="editor@test.com")
        with patch("src.api.routes.chat.get_permission_context", return_value=ctx), \
             patch("src.api.routes.chat.get_current_user", return_value="editor@test.com"), \
             patch("src.api.routes.chat.get_session_manager") as mock_mgr:
            mock_mgr.return_value.get_session.return_value = mock_session_info
            mock_mgr.return_value.require_editing_lock.return_value = None
            # Should not raise
            _check_chat_permission(contributor_session.session_id, db)

    def test_contributor_with_view_cannot_chat(self, db, owner_session, deck_contributor_view):
        """Contributor with only CAN_VIEW cannot chat (view-only)."""
        from fastapi import HTTPException
        from src.api.routes.chat import _check_chat_permission

        # Create a contributor session for the viewer
        contrib = UserSession(
            session_id="sess-viewer-contrib",
            created_by="viewer@test.com",
            parent_session_id=owner_session.id,
        )
        db.add(contrib)
        db.commit()
        db.refresh(contrib)

        mock_session_info = {
            "id": contrib.id,
            "session_id": contrib.session_id,
            "created_by": "viewer@test.com",
            "is_contributor_session": True,
            "parent_session_internal_id": owner_session.id,
        }

        ctx = PermissionContext(user_id="viewer-uid", user_name="viewer@test.com")
        with patch("src.api.routes.chat.get_permission_context", return_value=ctx), \
             patch("src.api.routes.chat.get_current_user", return_value="viewer@test.com"), \
             patch("src.api.routes.chat.get_session_manager") as mock_mgr:
            mock_mgr.return_value.get_session.return_value = mock_session_info
            with pytest.raises(HTTPException) as exc_info:
                _check_chat_permission(contrib.session_id, db)
            assert exc_info.value.status_code == 403

    def test_stranger_cannot_chat(self, db, owner_session):
        """User with no deck access cannot chat."""
        from fastapi import HTTPException
        from src.api.routes.chat import _check_chat_permission

        # Stranger's contributor session (shouldn't exist in practice, but test the guard)
        contrib = UserSession(
            session_id="sess-stranger-contrib",
            created_by="stranger@test.com",
            parent_session_id=owner_session.id,
        )
        db.add(contrib)
        db.commit()
        db.refresh(contrib)

        mock_session_info = {
            "id": contrib.id,
            "session_id": contrib.session_id,
            "created_by": "stranger@test.com",
            "is_contributor_session": True,
            "parent_session_internal_id": owner_session.id,
        }

        ctx = PermissionContext(user_id="stranger-uid", user_name="stranger@test.com")
        with patch("src.api.routes.chat.get_permission_context", return_value=ctx), \
             patch("src.api.routes.chat.get_current_user", return_value="stranger@test.com"), \
             patch("src.api.routes.chat.get_session_manager") as mock_mgr:
            mock_mgr.return_value.get_session.return_value = mock_session_info
            with pytest.raises(HTTPException) as exc_info:
                _check_chat_permission(contrib.session_id, db)
            assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Test get_mentionable_users uses deck_contributors
# ---------------------------------------------------------------------------


class TestMentionableUsers:
    """get_mentionable_users should query DeckContributor, not ConfigProfileContributor."""

    def test_returns_deck_contributors(self, db, owner_session, deck_contributor_edit):
        """Mentionable users should include deck contributors and session creator."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager()

        # Patch get_db_session to return our test db
        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = sm.get_mentionable_users(owner_session.session_id)

        usernames = [u["username"] for u in result["users"]]
        # Should include the session creator
        assert "owner@test.com" in usernames
        # Should include the deck contributor (editor@test.com)
        assert "editor@test.com" in usernames
        # Should NOT look up profile contributors (no profile_id dependency)
        assert result["is_global"] is False

    def test_no_profile_dependency(self, db, owner_session, deck_contributor_edit):
        """Mentionable users should work even when session has no profile_id."""
        from src.api.services.session_manager import SessionManager

        # Verify owner_session has no profile_id
        assert owner_session.profile_id is None

        sm = SessionManager()

        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = sm.get_mentionable_users(owner_session.session_id)

        # Should still return users (creator + deck contributors)
        assert len(result["users"]) >= 1


# ---------------------------------------------------------------------------
# Test shared presentations uses get_shared_session_ids
# ---------------------------------------------------------------------------


class TestSharedPresentations:
    """The shared presentations endpoint should use get_shared_session_ids from PermissionService."""

    def test_get_shared_session_ids_returns_deck_shared(self, db, owner_session, deck_contributor_edit):
        """get_shared_session_ids should return sessions shared via DeckContributor."""
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        shared = svc.get_shared_session_ids(
            db,
            user_id="editor-uid",
            user_name="editor@test.com",
        )

        assert owner_session.id in shared

    def test_get_shared_session_ids_excludes_own(self, db, owner_session, deck_contributor_edit):
        """get_shared_session_ids should exclude sessions where user is creator."""
        from src.services.permission_service import PermissionService

        # Add deck contributor for the owner themselves
        dc = DeckContributor(
            user_session_id=owner_session.id,
            identity_type="USER",
            identity_id="owner-uid",
            identity_name="owner@test.com",
            permission_level=PermissionLevel.CAN_MANAGE.value,
            created_by="owner@test.com",
        )
        db.add(dc)
        db.commit()

        svc = PermissionService()
        shared = svc.get_shared_session_ids(
            db,
            user_id="owner-uid",
            user_name="owner@test.com",
        )

        # Owner's own session should be excluded
        assert owner_session.id not in shared

    def test_stranger_gets_no_shared_sessions(self, db, owner_session):
        """User with no DeckContributor entries should get no shared sessions."""
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        shared = svc.get_shared_session_ids(
            db,
            user_id="stranger-uid",
            user_name="stranger@test.com",
        )

        assert len(shared) == 0


# ---------------------------------------------------------------------------
# Test session_manager.create_session without profile_id/profile_name
# ---------------------------------------------------------------------------


class TestCreateSessionNoProfile:
    """create_session should work without profile_id/profile_name params in the route."""

    def test_create_session_no_profile_params(self, db, owner_session):
        """Session creation via the route should not require profile_id."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager()
        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = sm.create_session(
                session_id="new-session-1",
                created_by="someone@test.com",
            )

        assert result["session_id"] == "new-session-1"
        assert result["created_by"] == "someone@test.com"


# ---------------------------------------------------------------------------
# Test create_chat_request without profile_id/profile_name
# ---------------------------------------------------------------------------


class TestCreateChatRequestNoProfile:
    """create_chat_request should work without profile_id/profile_name params."""

    def test_create_chat_request_no_profile(self, db, owner_session):
        """create_chat_request should accept call without profile params."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager()
        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=db)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            request_id = sm.create_chat_request(
                session_id=owner_session.session_id,
                created_by="owner@test.com",
            )

        assert request_id is not None
        assert isinstance(request_id, str)
