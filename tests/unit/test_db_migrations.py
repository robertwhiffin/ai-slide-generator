"""Unit tests for database migration logic (_run_migrations).

Verifies that the migration function detects missing columns on existing
tables and issues ALTER TABLE statements, and skips columns that already exist.
"""
import pytest
from unittest.mock import Mock, patch, call

from src.core.database import _run_migrations, Base

# _run_migrations imports inspect locally: `from sqlalchemy import text, inspect`
# So we patch sqlalchemy.inspect which is where the local import resolves from.
INSPECT_PATCH = "sqlalchemy.inspect"


@pytest.fixture
def mock_engine():
    """Mock SQLAlchemy engine with context manager support."""
    from unittest.mock import MagicMock
    return MagicMock()


@pytest.fixture
def mock_inspector():
    """Mock SQLAlchemy inspector."""
    inspector = Mock()
    # Default: table exists with original columns (no created_by, visibility, experiment_id)
    inspector.get_columns.return_value = [
        {"name": "id"},
        {"name": "session_id"},
        {"name": "user_id"},
        {"name": "title"},
        {"name": "created_at"},
        {"name": "last_activity"},
        {"name": "profile_id"},
        {"name": "profile_name"},
        {"name": "genie_conversation_id"},
        {"name": "is_processing"},
        {"name": "processing_started_at"},
    ]
    inspector.get_table_names.return_value = ["user_sessions", "session_messages"]
    return inspector


class TestRunMigrations:
    """_run_migrations should detect and add missing columns."""

    def test_detects_missing_columns(self, mock_engine, mock_inspector):
        """Should detect created_by, visibility, experiment_id as missing."""
        with patch(INSPECT_PATCH, return_value=mock_inspector):
            with patch("src.core.database.os.getenv", return_value=None):
                _run_migrations(mock_engine)

        # Should have called engine.connect() to run ALTER TABLE
        assert mock_engine.connect.called
        conn = mock_engine.connect.return_value.__enter__.return_value

        # Verify ALTER TABLE statements were executed for all 3 columns
        executed_stmts = [str(c[0][0]) for c in conn.execute.call_args_list]
        assert any("created_by" in stmt for stmt in executed_stmts)
        assert any("visibility" in stmt for stmt in executed_stmts)
        assert any("experiment_id" in stmt for stmt in executed_stmts)

    def test_skips_existing_columns(self, mock_engine, mock_inspector):
        """Should not ALTER TABLE for columns that already exist."""
        # Add the new columns to the existing columns list
        mock_inspector.get_columns.return_value = [
            {"name": "id"},
            {"name": "session_id"},
            {"name": "user_id"},
            {"name": "created_by"},
            {"name": "visibility"},
            {"name": "experiment_id"},
            {"name": "title"},
            {"name": "created_at"},
            {"name": "last_activity"},
            {"name": "profile_id"},
            {"name": "profile_name"},
            {"name": "genie_conversation_id"},
            {"name": "is_processing"},
            {"name": "processing_started_at"},
        ]

        with patch(INSPECT_PATCH, return_value=mock_inspector):
            with patch("src.core.database.os.getenv", return_value=None):
                _run_migrations(mock_engine)

        # Should NOT call engine.connect() since no migrations needed
        assert not mock_engine.connect.called

    def test_handles_missing_table(self, mock_engine, mock_inspector):
        """Should skip migration gracefully if user_sessions table doesn't exist."""
        mock_inspector.get_columns.side_effect = Exception("relation does not exist")

        with patch(INSPECT_PATCH, return_value=mock_inspector):
            with patch("src.core.database.os.getenv", return_value=None):
                # Should not raise
                _run_migrations(mock_engine)

        # No ALTER TABLE since table doesn't exist
        assert not mock_engine.connect.called

    def test_handles_partial_missing_columns(self, mock_engine, mock_inspector):
        """Should only add columns that are actually missing."""
        # Only created_by exists, visibility and experiment_id are missing
        mock_inspector.get_columns.return_value = [
            {"name": "id"},
            {"name": "session_id"},
            {"name": "user_id"},
            {"name": "created_by"},
            {"name": "title"},
            {"name": "created_at"},
            {"name": "last_activity"},
            {"name": "profile_id"},
            {"name": "profile_name"},
            {"name": "genie_conversation_id"},
            {"name": "is_processing"},
            {"name": "processing_started_at"},
        ]

        with patch(INSPECT_PATCH, return_value=mock_inspector):
            with patch("src.core.database.os.getenv", return_value=None):
                _run_migrations(mock_engine)

        conn = mock_engine.connect.return_value.__enter__.return_value
        executed_stmts = [str(c[0][0]) for c in conn.execute.call_args_list]

        # created_by should NOT be altered (already exists)
        assert not any("created_by" in stmt for stmt in executed_stmts)
        # visibility and experiment_id should be altered
        assert any("visibility" in stmt for stmt in executed_stmts)
        assert any("experiment_id" in stmt for stmt in executed_stmts)

    def test_uses_schema_from_env(self, mock_engine, mock_inspector):
        """Should pass schema to inspector when LAKEBASE_SCHEMA is set."""
        with patch(INSPECT_PATCH, return_value=mock_inspector):
            with patch("src.core.database.os.getenv", return_value="app_data"):
                _run_migrations(mock_engine)

        # Inspector should be called with schema
        mock_inspector.get_columns.assert_called_with("user_sessions", schema="app_data")

    def test_logs_missing_tables(self, mock_engine, mock_inspector):
        """Should identify tables that need to be created by create_all."""
        # Only user_sessions exists, others are missing
        mock_inspector.get_table_names.return_value = ["user_sessions"]

        with patch(INSPECT_PATCH, return_value=mock_inspector):
            with patch("src.core.database.os.getenv", return_value=None):
                # Should not raise — just logs
                _run_migrations(mock_engine)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
