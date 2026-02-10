"""Unit tests for permission service."""
import pytest
from unittest.mock import Mock, patch

from src.database.models.permissions import (
    PermissionLevel,
    PrincipalType,
    SessionPermission,
    SessionVisibility,
)
from src.database.models.session import UserSession
from src.services.permission_service import PermissionDeniedError, PermissionService


@pytest.fixture
def mock_db():
    """Mock database session."""
    return Mock()


@pytest.fixture
def permission_service(mock_db):
    """Create permission service instance."""
    return PermissionService(mock_db)


@pytest.fixture
def owner_session():
    """Create a session with an owner."""
    session = Mock(spec=UserSession)
    session.id = 1
    session.session_id = "test-session-123"
    session.created_by = "owner@company.com"
    session.visibility = SessionVisibility.PRIVATE.value
    return session


class TestPermissionChecks:
    """Test permission checking logic."""
    
    def test_owner_has_full_access(self, permission_service, owner_session):
        """Owner should have edit permission."""
        with patch("src.services.permission_service.get_current_user", return_value="owner@company.com"):
            # Owner should have edit (and read)
            assert permission_service.check_permission(
                owner_session, PermissionLevel.EDIT
            )
            assert permission_service.check_permission(
                owner_session, PermissionLevel.READ
            )
    
    def test_non_owner_private_session_denied(self, permission_service, owner_session, mock_db):
        """Non-owner should not access private session without grant."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with patch("src.services.permission_service.get_current_user", return_value="other@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                assert not permission_service.check_permission(
                    owner_session, PermissionLevel.READ
                )
    
    def test_workspace_visibility_grants_read(self, permission_service, owner_session, mock_db):
        """Workspace visibility should grant read to all users."""
        owner_session.visibility = SessionVisibility.WORKSPACE.value
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with patch("src.services.permission_service.get_current_user", return_value="anyone@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                # Should have read access
                assert permission_service.check_permission(
                    owner_session, PermissionLevel.READ
                )
                # Should NOT have edit access
                assert not permission_service.check_permission(
                    owner_session, PermissionLevel.EDIT
                )
    
    def test_explicit_user_grant_read(self, permission_service, owner_session, mock_db):
        """Explicit user grant should provide access."""
        mock_perm = Mock(spec=SessionPermission)
        mock_perm.permission = PermissionLevel.READ.value
        
        mock_db.query.return_value.filter.return_value.first.return_value = mock_perm
        
        with patch("src.services.permission_service.get_current_user", return_value="colleague@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                assert permission_service.check_permission(
                    owner_session, PermissionLevel.READ
                )
    
    def test_explicit_user_grant_edit(self, permission_service, owner_session, mock_db):
        """Edit grant should provide both read and edit."""
        mock_perm = Mock(spec=SessionPermission)
        mock_perm.permission = PermissionLevel.EDIT.value
        
        mock_db.query.return_value.filter.return_value.first.return_value = mock_perm
        
        with patch("src.services.permission_service.get_current_user", return_value="editor@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                # Edit includes read
                assert permission_service.check_permission(
                    owner_session, PermissionLevel.READ
                )
                assert permission_service.check_permission(
                    owner_session, PermissionLevel.EDIT
                )
    
    def test_group_permission_grants_access(self, permission_service, owner_session, mock_db):
        """Group membership should grant access."""
        mock_perm = Mock(spec=SessionPermission)
        mock_perm.permission = PermissionLevel.READ.value
        
        # First query for user grant returns None, second for group grant returns permission
        mock_db.query.return_value.filter.return_value.first.side_effect = [None, mock_perm]
        
        with patch("src.services.permission_service.get_current_user", return_value="member@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value={"data-team"}):
                assert permission_service.check_permission(
                    owner_session, PermissionLevel.READ
                )
    
    def test_require_permission_raises_on_denial(self, permission_service, owner_session, mock_db):
        """require_permission should raise PermissionDeniedError."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with patch("src.services.permission_service.get_current_user", return_value="other@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                with pytest.raises(PermissionDeniedError):
                    permission_service.require_permission(
                        owner_session, PermissionLevel.READ
                    )


class TestPermissionGrants:
    """Test granting and revoking permissions."""
    
    def test_owner_can_grant_permission(self, permission_service, owner_session, mock_db):
        """Owner should be able to grant permissions."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with patch("src.services.permission_service.get_current_user", return_value="owner@company.com"):
            perm = permission_service.grant_permission(
                session=owner_session,
                principal_type=PrincipalType.USER,
                principal_id="colleague@company.com",
                permission=PermissionLevel.READ,
            )
            
            assert mock_db.add.called
            assert mock_db.flush.called
    
    def test_non_owner_cannot_grant_permission(self, permission_service, owner_session):
        """Non-owner should not be able to grant permissions."""
        with patch("src.services.permission_service.get_current_user", return_value="other@company.com"):
            with pytest.raises(PermissionDeniedError):
                permission_service.grant_permission(
                    session=owner_session,
                    principal_type=PrincipalType.USER,
                    principal_id="someone@company.com",
                    permission=PermissionLevel.READ,
                )
    
    def test_owner_can_revoke_permission(self, permission_service, owner_session, mock_db):
        """Owner should be able to revoke permissions."""
        mock_perm = Mock(spec=SessionPermission)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_perm
        
        with patch("src.services.permission_service.get_current_user", return_value="owner@company.com"):
            result = permission_service.revoke_permission(
                session=owner_session,
                principal_type=PrincipalType.USER,
                principal_id="colleague@company.com",
            )
            
            assert result is True
            assert mock_db.delete.called
            assert mock_db.flush.called
    
    def test_owner_can_change_visibility(self, permission_service, owner_session, mock_db):
        """Owner should be able to change session visibility."""
        with patch("src.services.permission_service.get_current_user", return_value="owner@company.com"):
            permission_service.set_visibility(
                session=owner_session,
                visibility=SessionVisibility.WORKSPACE,
            )
            
            assert owner_session.visibility == SessionVisibility.WORKSPACE.value
            assert mock_db.flush.called
    
    def test_non_owner_cannot_change_visibility(self, permission_service, owner_session):
        """Non-owner should not be able to change visibility."""
        with patch("src.services.permission_service.get_current_user", return_value="other@company.com"):
            with pytest.raises(PermissionDeniedError):
                permission_service.set_visibility(
                    session=owner_session,
                    visibility=SessionVisibility.WORKSPACE,
                )


class TestGroupResolution:
    """Test Databricks group membership resolution."""
    
    def test_get_user_groups_success(self, permission_service):
        """Should retrieve user's groups from Databricks API."""
        mock_client = Mock()
        mock_user = Mock()
        mock_group1 = Mock()
        mock_group1.display = "data-team"
        mock_group2 = Mock()
        mock_group2.display = "engineering"
        mock_user.groups = [mock_group1, mock_group2]
        
        mock_client.users.list.return_value = [mock_user]
        
        with patch("src.services.permission_service.get_user_client", return_value=mock_client):
            groups = permission_service._get_user_groups("user@company.com")
            
            assert groups == {"data-team", "engineering"}
    
    def test_get_user_groups_caches_result(self, permission_service):
        """Should cache group lookups to avoid repeated API calls."""
        mock_client = Mock()
        mock_user = Mock()
        mock_group = Mock()
        mock_group.display = "data-team"
        mock_user.groups = [mock_group]
        
        mock_client.users.list.return_value = [mock_user]
        
        with patch("src.services.permission_service.get_user_client", return_value=mock_client):
            # First call
            groups1 = permission_service._get_user_groups("user@company.com")
            # Second call (should use cache)
            groups2 = permission_service._get_user_groups("user@company.com")
            
            assert groups1 == groups2
            # API should only be called once
            assert mock_client.users.list.call_count == 1
    
    def test_get_user_groups_handles_not_found(self, permission_service):
        """Should handle user not found gracefully."""
        mock_client = Mock()
        mock_client.users.list.return_value = []
        
        with patch("src.services.permission_service.get_user_client", return_value=mock_client):
            groups = permission_service._get_user_groups("unknown@company.com")
            
            assert groups == set()
    
    def test_get_user_groups_handles_api_error(self, permission_service):
        """Should handle API errors gracefully."""
        mock_client = Mock()
        mock_client.users.list.side_effect = Exception("API Error")
        
        with patch("src.services.permission_service.get_user_client", return_value=mock_client):
            groups = permission_service._get_user_groups("user@company.com")
            
            # Should return empty set on error
            assert groups == set()


class TestListAccessibleSessions:
    """Test listing sessions accessible to user."""
    
    def test_list_includes_owned_sessions(self, permission_service, mock_db):
        """Should include sessions owned by user."""
        owned_session = Mock(spec=UserSession)
        owned_session.session_id = "owned-session"
        owned_session.created_by = "user@company.com"
        
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [owned_session]
        mock_db.query.return_value = mock_query
        
        with patch("src.services.permission_service.get_current_user", return_value="user@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                sessions = permission_service.list_accessible_sessions()
                
                assert len(sessions) >= 1
                assert any(s.session_id == "owned-session" for s in sessions)
    
    def test_list_includes_workspace_visible_sessions(self, permission_service, mock_db):
        """Should include workspace-visible sessions when requesting read."""
        workspace_session = Mock(spec=UserSession)
        workspace_session.session_id = "workspace-session"
        workspace_session.visibility = SessionVisibility.WORKSPACE.value
        
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [workspace_session]
        mock_db.query.return_value = mock_query
        
        with patch("src.services.permission_service.get_current_user", return_value="user@company.com"):
            with patch.object(permission_service, "_get_user_groups", return_value=set()):
                sessions = permission_service.list_accessible_sessions(
                    permission=PermissionLevel.READ
                )
                
                # Should include workspace visible sessions
                assert any(s.session_id == "workspace-session" for s in sessions)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
