"""Integration tests for permission API endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

from src.api.main import app
from src.database.models.session import UserSession
from src.services.permission_service import PermissionDeniedError


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_session():
    """Mock session for testing."""
    session = Mock(spec=UserSession)
    session.id = 1
    session.session_id = "test-session-123"
    session.created_by = "owner@company.com"
    session.visibility = "private"
    session.title = "Test Session"
    session.messages = []
    session.slide_deck = None
    session.created_at = Mock()
    session.created_at.isoformat.return_value = "2026-01-29T10:00:00Z"
    session.last_activity = Mock()
    session.last_activity.isoformat.return_value = "2026-01-29T10:00:00Z"
    return session


class TestGrantPermissionAPI:
    """Test POST /api/sessions/{id}/permissions endpoint."""
    
    def test_grant_permission_success(self, client, mock_session):
        """Should grant permission successfully."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.grant_session_permission.return_value = {
                "session_id": "test-session-123",
                "principal_type": "user",
                "principal_id": "colleague@company.com",
                "permission": "read",
                "granted_by": "owner@company.com",
                "granted_at": "2026-01-29T10:00:00Z",
            }
            
            response = client.post(
                "/api/sessions/test-session-123/permissions",
                json={
                    "principal_type": "user",
                    "principal_id": "colleague@company.com",
                    "permission": "read",
                },
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["principal_id"] == "colleague@company.com"
            assert data["permission"] == "read"
    
    def test_grant_permission_forbidden_for_non_owner(self, client):
        """Should return 403 if user is not owner."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.grant_session_permission.side_effect = PermissionDeniedError("Not owner")
            
            response = client.post(
                "/api/sessions/test-session-123/permissions",
                json={
                    "principal_type": "user",
                    "principal_id": "colleague@company.com",
                    "permission": "read",
                },
            )
            
            assert response.status_code == 403
    
    def test_grant_permission_validates_request(self, client):
        """Should validate request body."""
        response = client.post(
            "/api/sessions/test-session-123/permissions",
            json={
                "principal_type": "invalid",  # Invalid type
                "principal_id": "colleague@company.com",
                "permission": "read",
            },
        )
        
        assert response.status_code == 422  # Validation error


class TestRevokePermissionAPI:
    """Test DELETE /api/sessions/{id}/permissions endpoint."""
    
    def test_revoke_permission_success(self, client):
        """Should revoke permission successfully."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.revoke_session_permission.return_value = True
            
            response = client.request(
                "DELETE",
                "/api/sessions/test-session-123/permissions",
                json={
                    "principal_type": "user",
                    "principal_id": "colleague@company.com",
                },
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "revoked"
    
    def test_revoke_permission_not_found(self, client):
        """Should return not_found if permission doesn't exist."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.revoke_session_permission.return_value = False
            
            response = client.request(
                "DELETE",
                "/api/sessions/test-session-123/permissions",
                json={
                    "principal_type": "user",
                    "principal_id": "colleague@company.com",
                },
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_found"


class TestListPermissionsAPI:
    """Test GET /api/sessions/{id}/permissions endpoint."""
    
    def test_list_permissions_success(self, client):
        """Should list permissions successfully."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.list_session_permissions.return_value = [
                {
                    "principal_type": "user",
                    "principal_id": "colleague@company.com",
                    "permission": "read",
                    "granted_by": "owner@company.com",
                    "granted_at": "2026-01-29T10:00:00Z",
                },
                {
                    "principal_type": "group",
                    "principal_id": "data-team",
                    "permission": "edit",
                    "granted_by": "owner@company.com",
                    "granted_at": "2026-01-29T10:05:00Z",
                },
            ]
            
            response = client.get("/api/sessions/test-session-123/permissions")
            
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 2
            assert len(data["permissions"]) == 2
    
    def test_list_permissions_requires_read(self, client):
        """Should require read permission to list permissions."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.list_session_permissions.side_effect = PermissionDeniedError("No access")
            
            response = client.get("/api/sessions/test-session-123/permissions")
            
            assert response.status_code == 403


class TestSetVisibilityAPI:
    """Test PATCH /api/sessions/{id}/permissions/visibility endpoint."""
    
    def test_set_visibility_success(self, client):
        """Should change visibility successfully."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.set_session_visibility.return_value = {
                "session_id": "test-session-123",
                "visibility": "workspace",
                "updated_at": "2026-01-29T10:15:00Z",
            }
            
            response = client.patch(
                "/api/sessions/test-session-123/permissions/visibility",
                json={"visibility": "workspace"},
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["visibility"] == "workspace"
    
    def test_set_visibility_validates_value(self, client):
        """Should validate visibility value."""
        response = client.patch(
            "/api/sessions/test-session-123/permissions/visibility",
            json={"visibility": "invalid"},  # Invalid visibility
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_set_visibility_forbidden_for_non_owner(self, client):
        """Should return 403 if user is not owner."""
        with patch("src.api.routes.permissions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.set_session_visibility.side_effect = PermissionDeniedError("Not owner")
            
            response = client.patch(
                "/api/sessions/test-session-123/permissions/visibility",
                json={"visibility": "workspace"},
            )
            
            assert response.status_code == 403


class TestSessionListFiltering:
    """Test that session list respects permissions."""
    
    def test_list_sessions_filters_by_permission(self, client):
        """Should only return accessible sessions."""
        with patch("src.api.routes.sessions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.list_sessions.return_value = [
                {
                    "session_id": "my-session",
                    "created_by": "me@company.com",
                    "visibility": "private",
                    "title": "My Session",
                    "created_at": "2026-01-29T10:00:00Z",
                    "last_activity": "2026-01-29T10:00:00Z",
                    "message_count": 0,
                    "has_slide_deck": False,
                },
            ]
            
            response = client.get("/api/sessions")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["session_id"] == "my-session"


class TestSessionCreationOwnership:
    """Test that session creation sets ownership."""
    
    def test_create_session_sets_owner(self, client):
        """Should set created_by on session creation."""
        with patch("src.api.routes.sessions.get_session_manager") as mock_get_mgr:
            with patch("src.core.user_context.get_current_user", return_value="user@company.com"):
                mock_mgr = Mock()
                mock_get_mgr.return_value = mock_mgr
                mock_mgr.create_session.return_value = {
                    "session_id": "new-session-123",
                    "created_by": "user@company.com",
                    "visibility": "private",
                    "title": "New Session",
                    "created_at": "2026-01-29T10:00:00Z",
                }
                
                response = client.post(
                    "/api/sessions",
                    json={"title": "New Session"},
                )
                
                assert response.status_code == 200
                data = response.json()
                assert data["created_by"] == "user@company.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
