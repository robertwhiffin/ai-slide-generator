"""Unit tests for slide style default endpoint, delete guard, and migration idempotency."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    from src.api.main import app

    return TestClient(app)


def _make_style(
    id=1,
    name="Test Style",
    description="A test style",
    category="Test",
    style_content="body { color: black; }",
    image_guidelines=None,
    is_active=True,
    is_system=False,
    is_default=False,
    created_by="system",
    updated_by="system",
    created_at=None,
    updated_at=None,
):
    """Create a mock SlideStyleLibrary object."""
    s = MagicMock()
    s.id = id
    s.name = name
    s.description = description
    s.category = category
    s.style_content = style_content
    s.image_guidelines = image_guidelines
    s.is_active = is_active
    s.is_system = is_system
    s.is_default = is_default
    s.created_by = created_by
    s.updated_by = updated_by
    s.created_at = created_at or datetime(2026, 1, 1, 12, 0, 0)
    s.updated_at = updated_at or datetime(2026, 1, 1, 12, 0, 0)
    return s


def _mock_db_context(styles_by_id):
    """Create a mock db session context manager for get_db_session.

    Args:
        styles_by_id: dict mapping style_id -> mock style object (or empty dict)
    """
    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()

        def filter_side_effect(*args):
            filter_chain = MagicMock()

            # Try to figure out which style is being queried by id
            # For .first() calls, check the filter args for id matching
            def first_side_effect():
                for arg in args:
                    # Check if this is an id filter by inspecting the mock calls
                    for sid, style in styles_by_id.items():
                        if hasattr(arg, 'right') and hasattr(arg.right, 'value'):
                            if arg.right.value == sid:
                                return style
                # Default: return the first style if only one exists
                if len(styles_by_id) == 1:
                    return next(iter(styles_by_id.values()))
                return None

            filter_chain.first = first_side_effect
            filter_chain.update = MagicMock()
            filter_chain.filter = filter_side_effect
            return filter_chain

        chain.filter = filter_side_effect
        return chain

    mock_db.query = query_side_effect
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    return mock_db


class TestSetDefault:
    """Tests for POST /api/settings/slide-styles/{id}/set-default."""

    @patch("src.api.routes.settings.slide_styles.get_db_session")
    def test_set_default_returns_style_with_is_default_true(self, mock_get_db, client):
        """POST /set-default sets the default and returns style with is_default=True."""
        style = _make_style(id=1, name="Custom Style", is_default=False)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        # query(...).filter(...).first() returns the style
        mock_db.query.return_value.filter.return_value.first.return_value = style
        mock_db.query.return_value.filter.return_value.update = MagicMock()

        def refresh_side_effect(s):
            s.is_default = True

        mock_db.refresh = refresh_side_effect
        mock_get_db.return_value = mock_db

        response = client.post("/api/settings/slide-styles/1/set-default")
        assert response.status_code == 200
        data = response.json()
        assert data["is_default"] is True
        assert data["id"] == 1
        assert data["name"] == "Custom Style"

    @patch("src.api.routes.settings.slide_styles.get_db_session")
    def test_set_default_unsets_previous_default(self, mock_get_db, client):
        """POST /set-default unsets the previous default (only one is_default=True at a time)."""
        style = _make_style(id=2, name="New Default", is_default=False)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        mock_db.query.return_value.filter.return_value.first.return_value = style
        mock_update = MagicMock()
        mock_db.query.return_value.filter.return_value.update = mock_update

        def refresh_side_effect(s):
            s.is_default = True

        mock_db.refresh = refresh_side_effect
        mock_get_db.return_value = mock_db

        response = client.post("/api/settings/slide-styles/2/set-default")
        assert response.status_code == 200

        # Verify the update call was made to unset previous defaults
        mock_update.assert_called_once_with({"is_default": False})

    @patch("src.api.routes.settings.slide_styles.get_db_session")
    def test_set_default_idempotent_on_already_default(self, mock_get_db, client):
        """POST /set-default on already-default style returns 200 (idempotent)."""
        style = _make_style(id=1, name="Already Default", is_default=True)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        mock_db.query.return_value.filter.return_value.first.return_value = style
        mock_get_db.return_value = mock_db

        response = client.post("/api/settings/slide-styles/1/set-default")
        assert response.status_code == 200
        data = response.json()
        assert data["is_default"] is True

        # Should NOT have called commit since it was already default
        mock_db.commit.assert_not_called()

    @patch("src.api.routes.settings.slide_styles.get_db_session")
    def test_set_default_inactive_style_returns_400(self, mock_get_db, client):
        """POST /set-default on inactive style returns 400."""
        style = _make_style(id=1, name="Inactive Style", is_active=False, is_default=False)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        mock_db.query.return_value.filter.return_value.first.return_value = style
        mock_get_db.return_value = mock_db

        response = client.post("/api/settings/slide-styles/1/set-default")
        assert response.status_code == 400
        assert "inactive" in response.json()["detail"].lower()

    @patch("src.api.routes.settings.slide_styles.get_db_session")
    def test_set_default_nonexistent_style_returns_404(self, mock_get_db, client):
        """POST /set-default on nonexistent style returns 404."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        response = client.post("/api/settings/slide-styles/9999/set-default")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestDeleteDefaultReassign:
    """Tests for DELETE reassigning default to system style.

    The delete endpoint uses FastAPI's Depends(get_db) which is harder to mock
    at the unit level. The reassign logic is verified by E2E integration tests
    in slide-styles-integration.spec.ts.
    """
    pass


class TestMigrationIdempotency:
    """Tests for _migrate_slide_style_default migration idempotency."""

    def test_migration_twice_does_not_error(self):
        """Calling _migrate_slide_style_default twice does not raise errors."""
        from src.core.database import _migrate_slide_style_default

        mock_conn = MagicMock()
        mock_inspector = MagicMock()
        # First call: column does not exist
        mock_inspector.get_columns.return_value = [
            {"name": "id"},
            {"name": "name"},
            {"name": "is_system"},
            {"name": "is_active"},
        ]
        _qual = lambda t: t

        # First call adds the column
        _migrate_slide_style_default(mock_conn, mock_inspector, None, _qual, is_sqlite=True)
        first_call_count = mock_conn.execute.call_count

        # Second call: column already exists
        mock_inspector.get_columns.return_value = [
            {"name": "id"},
            {"name": "name"},
            {"name": "is_system"},
            {"name": "is_active"},
            {"name": "is_default"},
        ]

        # Should not raise
        _migrate_slide_style_default(mock_conn, mock_inspector, None, _qual, is_sqlite=True)
        second_call_count = mock_conn.execute.call_count - first_call_count

        # First call: ALTER TABLE + UPDATE = 2 execute calls
        # Second call: only UPDATE (no ALTER TABLE) = 1 execute call
        assert first_call_count == 2  # ALTER + seed UPDATE
        assert second_call_count == 1  # only seed UPDATE (no ALTER)

    def test_migration_does_not_duplicate_defaults(self):
        """Calling migration twice does not create duplicate defaults.

        The SQL uses NOT EXISTS to prevent duplicates, so the UPDATE
        should be harmless on second call.
        """
        from src.core.database import _migrate_slide_style_default

        mock_conn = MagicMock()
        mock_inspector = MagicMock()
        # Column already exists for both calls
        mock_inspector.get_columns.return_value = [
            {"name": "id"},
            {"name": "name"},
            {"name": "is_default"},
            {"name": "is_system"},
            {"name": "is_active"},
        ]
        _qual = lambda t: t

        # Call twice — both should succeed without error
        _migrate_slide_style_default(mock_conn, mock_inspector, None, _qual, is_sqlite=True)
        _migrate_slide_style_default(mock_conn, mock_inspector, None, _qual, is_sqlite=True)

        # Each call executes one UPDATE (the seed query with NOT EXISTS guard).
        # The SQL's NOT EXISTS clause prevents actual duplication in a real DB.
        # With mocks, we just verify both calls completed without error and
        # each issued exactly one execute call (the seed UPDATE).
        assert mock_conn.execute.call_count == 2  # One seed UPDATE per call

    def test_migration_skips_if_table_missing(self):
        """Migration gracefully skips if slide_style_library table doesn't exist."""
        from src.core.database import _migrate_slide_style_default

        mock_conn = MagicMock()
        mock_inspector = MagicMock()
        mock_inspector.get_columns.side_effect = Exception("no such table")
        _qual = lambda t: t

        # Should not raise
        _migrate_slide_style_default(mock_conn, mock_inspector, None, _qual, is_sqlite=True)

        # No SQL should have been executed
        mock_conn.execute.assert_not_called()
