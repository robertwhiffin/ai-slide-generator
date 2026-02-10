"""Unit tests for session manager permission enforcement."""
import pytest
from unittest.mock import Mock, patch

from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.database.models.permissions import PermissionLevel, SessionVisibility
from src.database.models.session import UserSession
from src.services.permission_service import PermissionDeniedError


@pytest.fixture
def session_manager():
    """Create session manager instance."""
    return SessionManager()


@pytest.fixture
def mock_db_session():
    """Mock database session context manager."""
    mock_db = Mock()
    mock_ctx = Mock()
    mock_ctx.__enter__ = Mock(return_value=mock_db)
    mock_ctx.__exit__ = Mock(return_value=False)
    return mock_ctx


class TestSessionCreation:
    """Test session creation with ownership."""
    
    def test_create_session_sets_owner(self, session_manager):
        """Session creation should set created_by to current user."""
        from datetime import datetime
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            with patch("src.api.services.session_manager.get_current_user", return_value="user@company.com"):
                mock_db = Mock()
                mock_session = Mock(spec=UserSession)
                mock_session.created_at = datetime.utcnow()
                mock_session.last_activity = datetime.utcnow()
                mock_session.messages = []
                mock_get_db.return_value.__enter__.return_value = mock_db
                
                # Mock the session object returned from db.add
                def mock_add(obj):
                    obj.created_at = datetime.utcnow()
                    obj.last_activity = datetime.utcnow()
                mock_db.add.side_effect = mock_add
                
                result = session_manager.create_session(
                    title="Test Session"
                )
                
                # Check that created_by was set
                assert result["created_by"] == "user@company.com"
                assert mock_db.add.called
    
    def test_create_session_defaults_to_private(self, session_manager):
        """Session should default to private visibility."""
        from datetime import datetime
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            with patch("src.api.services.session_manager.get_current_user", return_value="user@company.com"):
                mock_db = Mock()
                mock_get_db.return_value.__enter__.return_value = mock_db
                
                # Mock the session object with proper datetime
                def mock_add(obj):
                    obj.created_at = datetime.utcnow()
                    obj.last_activity = datetime.utcnow()
                mock_db.add.side_effect = mock_add
                
                result = session_manager.create_session()
                
                assert result["visibility"] == SessionVisibility.PRIVATE.value
    
    def test_create_session_respects_visibility_param(self, session_manager):
        """Should allow setting visibility on creation."""
        from datetime import datetime
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            with patch("src.api.services.session_manager.get_current_user", return_value="user@company.com"):
                mock_db = Mock()
                mock_get_db.return_value.__enter__.return_value = mock_db
                
                # Mock the session object with proper datetime
                def mock_add(obj):
                    obj.created_at = datetime.utcnow()
                    obj.last_activity = datetime.utcnow()
                mock_db.add.side_effect = mock_add
                
                result = session_manager.create_session(
                    visibility=SessionVisibility.WORKSPACE
                )
                
                assert result["visibility"] == SessionVisibility.WORKSPACE.value


class TestPermissionEnforcement:
    """Test permission checks on session operations."""
    
    def test_get_session_checks_permission(self, session_manager):
        """get_session should enforce read permission."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_session = Mock(spec=UserSession)
            mock_session.session_id = "test-123"
            mock_session.created_by = "owner@company.com"
            mock_session.messages = []  # Add empty messages list
            
            mock_db.query.return_value.filter.return_value.first.return_value = mock_session
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            with patch("src.services.permission_service.PermissionService.require_permission") as mock_require:
                session_manager.get_session("test-123")
                
                # Should check read permission
                assert mock_require.called
                args = mock_require.call_args[0]
                assert args[1] == PermissionLevel.READ
    
    def test_delete_session_checks_edit_permission(self, session_manager):
        """delete_session should enforce edit permission."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_session = Mock(spec=UserSession)
            mock_session.session_id = "test-123"
            
            mock_db.query.return_value.filter.return_value.first.return_value = mock_session
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            with patch("src.services.permission_service.PermissionService.require_permission") as mock_require:
                session_manager.delete_session("test-123")
                
                # Should check edit permission
                assert mock_require.called
                args = mock_require.call_args[0]
                assert args[1] == PermissionLevel.EDIT
    
    def test_rename_session_checks_edit_permission(self, session_manager):
        """rename_session should enforce edit permission."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_session = Mock(spec=UserSession)
            mock_session.session_id = "test-123"
            
            mock_db.query.return_value.filter.return_value.first.return_value = mock_session
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            with patch("src.services.permission_service.PermissionService.require_permission") as mock_require:
                session_manager.rename_session("test-123", "New Title")
                
                # Should check edit permission
                assert mock_require.called
                args = mock_require.call_args[0]
                assert args[1] == PermissionLevel.EDIT
    
    def test_list_sessions_filters_by_permission(self, session_manager):
        """list_sessions should only return accessible sessions."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            with patch("src.api.services.session_manager.get_current_user", return_value="user@company.com"):
                mock_db = Mock()
                mock_get_db.return_value.__enter__.return_value = mock_db
                
                with patch("src.services.permission_service.PermissionService.list_accessible_sessions") as mock_list:
                    mock_session1 = Mock(spec=UserSession)
                    mock_session1.session_id = "session-1"
                    mock_session1.last_activity = Mock()
                    mock_session1.messages = []
                    mock_session1.slide_deck = None
                    
                    mock_list.return_value = [mock_session1]
                    
                    result = session_manager.list_sessions()
                    
                    # Should use permission service to filter
                    assert mock_list.called
                    assert len(result) == 1


class TestPermissionManagement:
    """Test permission management methods."""
    
    def test_grant_permission_creates_acl_entry(self, session_manager):
        """grant_session_permission should create permission."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            with patch("src.api.services.session_manager.get_current_user", return_value="owner@company.com"):
                mock_db = Mock()
                mock_session = Mock(spec=UserSession)
                mock_session.created_by = "owner@company.com"
                
                mock_db.query.return_value.filter.return_value.first.return_value = mock_session
                mock_get_db.return_value.__enter__.return_value = mock_db
                
                with patch("src.services.permission_service.PermissionService.grant_permission") as mock_grant:
                    session_manager.grant_session_permission(
                        session_id="test-123",
                        principal_type="user",
                        principal_id="colleague@company.com",
                        permission="read",
                    )
                    
                    assert mock_grant.called
    
    def test_revoke_permission_removes_acl_entry(self, session_manager):
        """revoke_session_permission should remove permission."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            with patch("src.api.services.session_manager.get_current_user", return_value="owner@company.com"):
                mock_db = Mock()
                mock_session = Mock(spec=UserSession)
                mock_session.created_by = "owner@company.com"
                
                mock_db.query.return_value.filter.return_value.first.return_value = mock_session
                mock_get_db.return_value.__enter__.return_value = mock_db
                
                with patch("src.services.permission_service.PermissionService.revoke_permission") as mock_revoke:
                    mock_revoke.return_value = True
                    
                    result = session_manager.revoke_session_permission(
                        session_id="test-123",
                        principal_type="user",
                        principal_id="colleague@company.com",
                    )
                    
                    assert result is True
                    assert mock_revoke.called
    
    def test_set_visibility_changes_session(self, session_manager):
        """set_session_visibility should update visibility."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            with patch("src.api.services.session_manager.get_current_user", return_value="owner@company.com"):
                mock_db = Mock()
                mock_session = Mock(spec=UserSession)
                mock_session.created_by = "owner@company.com"
                mock_session.visibility = "private"
                
                mock_db.query.return_value.filter.return_value.first.return_value = mock_session
                mock_get_db.return_value.__enter__.return_value = mock_db
                
                with patch("src.services.permission_service.PermissionService.set_visibility") as mock_set_vis:
                    session_manager.set_session_visibility(
                        session_id="test-123",
                        visibility="workspace",
                    )
                    
                    assert mock_set_vis.called
    
    def test_list_permissions_returns_acls(self, session_manager):
        """list_session_permissions should return permission list."""
        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_session = Mock(spec=UserSession)
            
            mock_db.query.return_value.filter.return_value.first.return_value = mock_session
            mock_get_db.return_value.__enter__.return_value = mock_db
            
            with patch("src.services.permission_service.PermissionService.require_permission"):
                with patch("src.services.permission_service.PermissionService.list_permissions") as mock_list:
                    mock_perm = Mock()
                    mock_perm.principal_type = "user"
                    mock_perm.principal_id = "colleague@company.com"
                    mock_perm.permission = "read"
                    mock_perm.granted_by = "owner@company.com"
                    mock_perm.granted_at = Mock()
                    mock_perm.granted_at.isoformat.return_value = "2026-01-29T10:00:00Z"
                    
                    mock_list.return_value = [mock_perm]
                    
                    result = session_manager.list_session_permissions("test-123")
                    
                    assert len(result) == 1
                    assert result[0]["principal_id"] == "colleague@company.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
