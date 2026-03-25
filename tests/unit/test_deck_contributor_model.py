"""Unit tests for DeckContributor model and PermissionLevel enum update."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    # Register all models needed for FK resolution
    import src.database.models.session  # noqa: F401
    import src.database.models.deck_contributor  # noqa: F401
    import src.database.models.profile_contributor  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def _create_user_session(db_session, session_id="test-session-1"):
    """Helper to create a UserSession row so FK constraints are satisfied."""
    from src.database.models.session import UserSession

    us = UserSession(session_id=session_id, created_by="test-user@example.com")
    db_session.add(us)
    db_session.commit()
    return us


class TestPermissionLevelEnum:
    """Tests for PermissionLevel enum updates."""

    def test_can_use_exists(self):
        """CAN_USE should exist in the PermissionLevel enum."""
        from src.database.models.profile_contributor import PermissionLevel

        assert hasattr(PermissionLevel, "CAN_USE")
        assert PermissionLevel.CAN_USE.value == "CAN_USE"

    def test_all_four_levels_exist(self):
        """All four permission levels should exist."""
        from src.database.models.profile_contributor import PermissionLevel

        levels = {member.value for member in PermissionLevel}
        assert levels == {"CAN_USE", "CAN_VIEW", "CAN_EDIT", "CAN_MANAGE"}

    def test_can_use_is_first(self):
        """CAN_USE should be the first member of the enum."""
        from src.database.models.profile_contributor import PermissionLevel

        members = list(PermissionLevel)
        assert members[0] == PermissionLevel.CAN_USE


class TestDeckContributorModel:
    """Tests for DeckContributor model."""

    def test_create_and_read_back(self, db_session):
        """Test creating a DeckContributor and reading it back."""
        from src.database.models.deck_contributor import DeckContributor

        us = _create_user_session(db_session)

        contributor = DeckContributor(
            user_session_id=us.id,
            identity_type="USER",
            identity_id="user1@example.com",
            identity_name="User One",
            permission_level="CAN_VIEW",
            created_by="admin@example.com",
        )
        db_session.add(contributor)
        db_session.commit()

        result = db_session.query(DeckContributor).first()
        assert result is not None
        assert result.id is not None
        assert result.user_session_id == us.id
        assert result.identity_type == "USER"
        assert result.identity_id == "user1@example.com"
        assert result.identity_name == "User One"
        assert result.permission_level == "CAN_VIEW"
        assert result.created_by == "admin@example.com"
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_unique_constraint_same_session_same_identity(self, db_session):
        """Same user_session_id + identity_id should raise IntegrityError."""
        from src.database.models.deck_contributor import DeckContributor

        us = _create_user_session(db_session)

        c1 = DeckContributor(
            user_session_id=us.id,
            identity_type="USER",
            identity_id="user1@example.com",
            identity_name="User One",
            permission_level="CAN_VIEW",
        )
        db_session.add(c1)
        db_session.commit()

        c2 = DeckContributor(
            user_session_id=us.id,
            identity_type="USER",
            identity_id="user1@example.com",
            identity_name="User One Duplicate",
            permission_level="CAN_EDIT",
        )
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_different_sessions_same_identity_allowed(self, db_session):
        """Different user_session_ids with the same identity_id should be allowed."""
        from src.database.models.deck_contributor import DeckContributor
        from src.database.models.session import UserSession

        us1 = _create_user_session(db_session, session_id="session-1")
        us2 = UserSession(session_id="session-2", created_by="other-user@example.com")
        db_session.add(us2)
        db_session.commit()

        c1 = DeckContributor(
            user_session_id=us1.id,
            identity_type="USER",
            identity_id="shared@example.com",
            identity_name="Shared User",
            permission_level="CAN_VIEW",
        )
        c2 = DeckContributor(
            user_session_id=us2.id,
            identity_type="USER",
            identity_id="shared@example.com",
            identity_name="Shared User",
            permission_level="CAN_EDIT",
        )
        db_session.add_all([c1, c2])
        db_session.commit()

        results = db_session.query(DeckContributor).all()
        assert len(results) == 2

    def test_table_name(self):
        """Table name should be deck_contributors."""
        from src.database.models.deck_contributor import DeckContributor

        assert DeckContributor.__tablename__ == "deck_contributors"


class TestUserSessionProfileColumns:
    """Tests that profile_id and profile_name have been removed from UserSession."""

    def test_no_profile_id_column(self):
        from src.database.models.session import UserSession

        column_names = [c.name for c in UserSession.__table__.columns]
        assert "profile_id" not in column_names

    def test_no_profile_name_column(self):
        from src.database.models.session import UserSession

        column_names = [c.name for c in UserSession.__table__.columns]
        assert "profile_name" not in column_names
