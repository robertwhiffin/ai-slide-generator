"""Tests for PermissionService — profile + deck permission methods.

Uses in-memory SQLite with StaticPool. Validates:
- PERMISSION_PRIORITY values
- Deck permission resolution (creator, direct user, group, fallback by name)
- get_shared_session_ids filtering
- Renamed profile permission methods
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — register all models with Base
from src.core.database import Base
from src.database.models import ConfigProfile, ConfigProfileContributor, UserSession
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
def profile(db):
    """A test profile owned by 'owner@test.com'."""
    p = ConfigProfile(
        name="test-profile",
        is_default=False,
        is_deleted=False,
        created_by="owner@test.com",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def session_owned(db):
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
def session_other(db):
    """A root session created by 'other@test.com'."""
    s = UserSession(
        session_id="sess-other-1",
        created_by="other@test.com",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# TestPermissionPriority
# ---------------------------------------------------------------------------


class TestPermissionPriority:
    """PERMISSION_PRIORITY should map CAN_USE=1, CAN_VIEW=1, CAN_EDIT=2, CAN_MANAGE=3."""

    def test_can_use_priority(self):
        from src.services.permission_service import PERMISSION_PRIORITY

        assert PERMISSION_PRIORITY[PermissionLevel.CAN_USE] == 1

    def test_can_view_priority(self):
        from src.services.permission_service import PERMISSION_PRIORITY

        assert PERMISSION_PRIORITY[PermissionLevel.CAN_VIEW] == 1

    def test_can_edit_priority(self):
        from src.services.permission_service import PERMISSION_PRIORITY

        assert PERMISSION_PRIORITY[PermissionLevel.CAN_EDIT] == 2

    def test_can_manage_priority(self):
        from src.services.permission_service import PERMISSION_PRIORITY

        assert PERMISSION_PRIORITY[PermissionLevel.CAN_MANAGE] == 3


# ---------------------------------------------------------------------------
# TestDeckPermission
# ---------------------------------------------------------------------------


class TestDeckPermission:
    """get_deck_permission resolution: creator → direct user → fallback name → group → None."""

    def test_creator_gets_can_manage(self, db, session_owned):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        perm = svc.get_deck_permission(
            db,
            session_id=session_owned.id,
            user_id="uid-999",
            user_name="owner@test.com",
            group_ids=[],
        )
        assert perm == PermissionLevel.CAN_MANAGE

    def test_direct_user_match_by_identity_id(self, db, session_other):
        from src.services.permission_service import PermissionService

        # Add a DeckContributor for user uid-100 with CAN_EDIT
        dc = DeckContributor(
            user_session_id=session_other.id,
            identity_type="USER",
            identity_id="uid-100",
            identity_name="viewer@test.com",
            permission_level=PermissionLevel.CAN_EDIT.value,
        )
        db.add(dc)
        db.commit()

        svc = PermissionService()
        perm = svc.get_deck_permission(
            db,
            session_id=session_other.id,
            user_id="uid-100",
            user_name="viewer@test.com",
            group_ids=[],
        )
        assert perm == PermissionLevel.CAN_EDIT

    def test_fallback_by_identity_name(self, db, session_other):
        from src.services.permission_service import PermissionService

        dc = DeckContributor(
            user_session_id=session_other.id,
            identity_type="USER",
            identity_id="uid-unknown",
            identity_name="fallback@test.com",
            permission_level=PermissionLevel.CAN_VIEW.value,
        )
        db.add(dc)
        db.commit()

        svc = PermissionService()
        # user_id does NOT match identity_id, but user_name matches identity_name
        perm = svc.get_deck_permission(
            db,
            session_id=session_other.id,
            user_id="uid-different",
            user_name="fallback@test.com",
            group_ids=[],
        )
        assert perm == PermissionLevel.CAN_VIEW

    def test_group_highest_wins(self, db, session_other):
        from src.services.permission_service import PermissionService

        # Two group entries with different levels
        db.add(DeckContributor(
            user_session_id=session_other.id,
            identity_type="GROUP",
            identity_id="grp-a",
            identity_name="GroupA",
            permission_level=PermissionLevel.CAN_VIEW.value,
        ))
        db.add(DeckContributor(
            user_session_id=session_other.id,
            identity_type="GROUP",
            identity_id="grp-b",
            identity_name="GroupB",
            permission_level=PermissionLevel.CAN_EDIT.value,
        ))
        db.commit()

        svc = PermissionService()
        perm = svc.get_deck_permission(
            db,
            session_id=session_other.id,
            user_id="uid-nobody",
            user_name="nobody@test.com",
            group_ids=["grp-a", "grp-b"],
        )
        assert perm == PermissionLevel.CAN_EDIT

    def test_no_match_returns_none(self, db, session_other):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        perm = svc.get_deck_permission(
            db,
            session_id=session_other.id,
            user_id="uid-stranger",
            user_name="stranger@test.com",
            group_ids=[],
        )
        assert perm is None


# ---------------------------------------------------------------------------
# TestGetSharedSessionIds
# ---------------------------------------------------------------------------


class TestGetSharedSessionIds:
    """get_shared_session_ids returns sessions shared with user, excludes own."""

    def test_returns_shared_sessions(self, db, session_other):
        from src.services.permission_service import PermissionService

        # Share session_other with uid-viewer
        db.add(DeckContributor(
            user_session_id=session_other.id,
            identity_type="USER",
            identity_id="uid-viewer",
            identity_name="viewer@test.com",
            permission_level=PermissionLevel.CAN_VIEW.value,
        ))
        db.commit()

        svc = PermissionService()
        ids = svc.get_shared_session_ids(
            db,
            user_id="uid-viewer",
            user_name="viewer@test.com",
            group_ids=[],
        )
        assert session_other.id in ids

    def test_excludes_own_sessions(self, db, session_owned):
        from src.services.permission_service import PermissionService

        # Share session_owned with owner themselves via deck_contributors
        db.add(DeckContributor(
            user_session_id=session_owned.id,
            identity_type="USER",
            identity_id="uid-owner",
            identity_name="owner@test.com",
            permission_level=PermissionLevel.CAN_EDIT.value,
        ))
        db.commit()

        svc = PermissionService()
        ids = svc.get_shared_session_ids(
            db,
            user_id="uid-owner",
            user_name="owner@test.com",
            group_ids=[],
        )
        # session_owned is created_by owner@test.com, so it should be excluded
        assert session_owned.id not in ids

    def test_group_shared_sessions(self, db, session_other):
        from src.services.permission_service import PermissionService

        db.add(DeckContributor(
            user_session_id=session_other.id,
            identity_type="GROUP",
            identity_id="grp-team",
            identity_name="Team",
            permission_level=PermissionLevel.CAN_EDIT.value,
        ))
        db.commit()

        svc = PermissionService()
        ids = svc.get_shared_session_ids(
            db,
            user_id="uid-member",
            user_name="member@test.com",
            group_ids=["grp-team"],
        )
        assert session_other.id in ids


# ---------------------------------------------------------------------------
# TestProfilePermissionRenamed
# ---------------------------------------------------------------------------


class TestProfilePermissionRenamed:
    """Renamed profile methods exist and work correctly."""

    def test_get_profile_permission_exists(self):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert hasattr(svc, "get_profile_permission")

    def test_can_use_profile_exists(self):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert hasattr(svc, "can_use_profile")

    def test_require_use_profile_exists(self):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert hasattr(svc, "require_use_profile")

    def test_can_edit_profile_exists(self):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert hasattr(svc, "can_edit_profile")

    def test_can_manage_profile_exists(self):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert hasattr(svc, "can_manage_profile")

    def test_creator_gets_can_manage(self, db, profile):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        perm = svc.get_profile_permission(
            db,
            profile_id=profile.id,
            user_name="owner@test.com",
        )
        assert perm == PermissionLevel.CAN_MANAGE

    def test_no_access_returns_none(self, db, profile):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        perm = svc.get_profile_permission(
            db,
            profile_id=profile.id,
            user_name="stranger@test.com",
        )
        assert perm is None

    def test_stateless_constructor(self):
        """PermissionService() takes no args."""
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert not hasattr(svc, "db") or svc.db is None if hasattr(svc, "db") else True

    def test_factory_takes_no_args(self):
        """get_permission_service() takes no args."""
        from src.services.permission_service import get_permission_service

        svc = get_permission_service()
        assert isinstance(svc, type(svc))


# ---------------------------------------------------------------------------
# TestDeckConvenienceMethods
# ---------------------------------------------------------------------------


class TestDeckConvenienceMethods:
    """Deck convenience check and require methods."""

    def test_can_view_deck_true_for_creator(self, db, session_owned):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert svc.can_view_deck(
            db, session_id=session_owned.id,
            user_id="uid-x", user_name="owner@test.com", group_ids=[],
        ) is True

    def test_can_edit_deck_false_for_viewer(self, db, session_other):
        from src.services.permission_service import PermissionService

        db.add(DeckContributor(
            user_session_id=session_other.id,
            identity_type="USER",
            identity_id="uid-viewer",
            identity_name="viewer@test.com",
            permission_level=PermissionLevel.CAN_VIEW.value,
        ))
        db.commit()

        svc = PermissionService()
        assert svc.can_edit_deck(
            db, session_id=session_other.id,
            user_id="uid-viewer", user_name="viewer@test.com", group_ids=[],
        ) is False

    def test_can_manage_deck_true_for_creator(self, db, session_owned):
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        assert svc.can_manage_deck(
            db, session_id=session_owned.id,
            user_id="uid-x", user_name="owner@test.com", group_ids=[],
        ) is True

    def test_require_view_deck_raises_for_stranger(self, db, session_other):
        from fastapi import HTTPException
        from src.services.permission_service import PermissionService

        svc = PermissionService()
        with pytest.raises(HTTPException) as exc_info:
            svc.require_view_deck(
                db, session_id=session_other.id,
                user_id="uid-stranger", user_name="stranger@test.com", group_ids=[],
            )
        assert exc_info.value.status_code == 403

    def test_require_edit_deck_raises_for_viewer(self, db, session_other):
        from fastapi import HTTPException
        from src.services.permission_service import PermissionService

        db.add(DeckContributor(
            user_session_id=session_other.id,
            identity_type="USER",
            identity_id="uid-viewer",
            identity_name="viewer@test.com",
            permission_level=PermissionLevel.CAN_VIEW.value,
        ))
        db.commit()

        svc = PermissionService()
        with pytest.raises(HTTPException) as exc_info:
            svc.require_edit_deck(
                db, session_id=session_other.id,
                user_id="uid-viewer", user_name="viewer@test.com", group_ids=[],
            )
        assert exc_info.value.status_code == 403

    def test_require_manage_deck_raises_for_editor(self, db, session_other):
        from fastapi import HTTPException
        from src.services.permission_service import PermissionService

        db.add(DeckContributor(
            user_session_id=session_other.id,
            identity_type="USER",
            identity_id="uid-editor",
            identity_name="editor@test.com",
            permission_level=PermissionLevel.CAN_EDIT.value,
        ))
        db.commit()

        svc = PermissionService()
        with pytest.raises(HTTPException) as exc_info:
            svc.require_manage_deck(
                db, session_id=session_other.id,
                user_id="uid-editor", user_name="editor@test.com", group_ids=[],
            )
        assert exc_info.value.status_code == 403
