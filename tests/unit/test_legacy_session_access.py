"""Unit tests for legacy session access (sessions with created_by = NULL).

Verifies that sessions created before ownership tracking was introduced
grant access to any authenticated user, since they have no owner.
"""
import pytest
from unittest.mock import Mock, patch

from src.database.models.permissions import (
    PermissionLevel,
    SessionVisibility,
)
from src.database.models.session import UserSession
from src.services.permission_service import PermissionService


@pytest.fixture
def mock_db():
    """Mock database session."""
    return Mock()


@pytest.fixture
def permission_service(mock_db):
    """Create permission service instance."""
    return PermissionService(mock_db)


@pytest.fixture
def legacy_session():
    """Session with no owner (created before ownership tracking)."""
    session = Mock(spec=UserSession)
    session.id = 1
    session.session_id = "legacy-session-001"
    session.created_by = None  # No owner — legacy session
    session.visibility = "private"
    return session


@pytest.fixture
def owned_session():
    """Session with an explicit owner."""
    session = Mock(spec=UserSession)
    session.id = 2
    session.session_id = "owned-session-001"
    session.created_by = "owner@company.com"
    session.visibility = SessionVisibility.PRIVATE.value
    return session


class TestLegacySessionAccess:
    """Legacy sessions (created_by = NULL) should be accessible to any authenticated user."""

    def test_legacy_session_grants_read_to_any_user(self, permission_service, legacy_session):
        """Any authenticated user should be able to read a legacy session."""
        with patch("src.services.permission_service.get_current_user", return_value="anyone@company.com"):
            assert permission_service.check_permission(
                legacy_session, PermissionLevel.READ
            )

    def test_legacy_session_grants_edit_to_any_user(self, permission_service, legacy_session):
        """Any authenticated user should be able to edit a legacy session."""
        with patch("src.services.permission_service.get_current_user", return_value="anyone@company.com"):
            assert permission_service.check_permission(
                legacy_session, PermissionLevel.EDIT
            )

    def test_legacy_session_denies_anonymous(self, permission_service, legacy_session):
        """Unauthenticated users (no current_user) should not access legacy sessions."""
        with patch("src.services.permission_service.get_current_user", return_value=None):
            assert not permission_service.check_permission(
                legacy_session, PermissionLevel.READ
            )

    def test_legacy_session_require_permission_does_not_raise(self, permission_service, legacy_session):
        """require_permission should NOT raise for authenticated users on legacy sessions."""
        with patch("src.services.permission_service.get_current_user", return_value="user@company.com"):
            # Should not raise
            permission_service.require_permission(
                legacy_session, PermissionLevel.READ
            )
            permission_service.require_permission(
                legacy_session, PermissionLevel.EDIT
            )

    def test_owned_session_still_restricts_access(self, permission_service, owned_session, mock_db):
        """Owned sessions should still enforce normal permission checks."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("src.services.permission_service.get_current_user", return_value="stranger@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                assert not permission_service.check_permission(
                    owned_session, PermissionLevel.READ
                )

    def test_owned_session_owner_still_has_access(self, permission_service, owned_session):
        """Owner of an owned session should still have full access."""
        with patch("src.services.permission_service.get_current_user", return_value="owner@company.com"):
            assert permission_service.check_permission(
                owned_session, PermissionLevel.EDIT
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
