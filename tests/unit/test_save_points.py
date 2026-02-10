"""Save points (versioning) tests.

These tests validate the save point/versioning feature:
    Create(version) -> Preview(version) -> Restore(version) == Expected_State

Each test ensures:
1. Version creation stores complete deck snapshots with chat history
2. Version listing returns correct order (newest first)
3. Preview returns deck + chat history + verification without modifying DB
4. Restore reverts deck, deletes newer versions and messages
5. Version limit (40) is enforced with oldest-first eviction
6. Version numbers are never reused (continue incrementing)

This suite covers the save points feature added in the
save-points-and-fixes branch.
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Dict, Any, Optional, List

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.api.services.chat_service import ChatService
from src.database.models.session import SlideDeckVersion

from tests.fixtures.html import (
    load_3_slide_deck,
    load_6_slide_deck,
    generate_chart_slide,
    generate_content_slide,
)


class MockSessionForVersions:
    """Mock session object with messages and versions for testing."""

    def __init__(self, session_id: int = 1):
        self.id = session_id
        self.messages = []
        self.slide_deck = None
        self.versions = []


class MockSlideDeckRecord:
    """Mock SessionSlideDeck database record."""

    def __init__(self, session_id: int, deck_json: str = "{}"):
        self.session_id = session_id
        self.deck_json = deck_json
        self.verification_map = None
        self.title = "Test Deck"
        self.slide_count = 3
        self.updated_at = datetime.utcnow()


class MockMessage:
    """Mock session message for chat history capture."""

    def __init__(self, msg_id: int, role: str, content: str, message_type: str = "text"):
        self.id = msg_id
        self.role = role
        self.content = content
        self.message_type = message_type
        self.created_at = datetime.utcnow()
        self.session_id = 1


class MockVersionRecord:
    """Mock SlideDeckVersion database record."""

    def __init__(
        self,
        version_number: int,
        description: str,
        deck_json: str,
        session_id: int = 1,
        verification_map_json: Optional[str] = None,
        chat_history_json: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ):
        self.id = version_number
        self.session_id = session_id
        self.version_number = version_number
        self.description = description
        self.deck_json = deck_json
        self.verification_map_json = verification_map_json
        self.chat_history_json = chat_history_json
        self.created_at = created_at or datetime.utcnow()


def _create_test_deck(num_slides: int = 3) -> SlideDeck:
    """Create a test SlideDeck with the specified number of slides."""
    if num_slides <= 3:
        html = load_3_slide_deck()
    else:
        html = load_6_slide_deck()
    deck = SlideDeck.from_html_string(html)
    # Trim to exact count if needed
    while len(deck.slides) > num_slides:
        deck.remove_slide(len(deck.slides) - 1)
    return deck


def _create_deck_dict(num_slides: int = 3, title: str = "Test Deck") -> Dict[str, Any]:
    """Create a deck dictionary matching the format stored in versions."""
    deck = _create_test_deck(num_slides)
    result = deck.to_dict()
    result["title"] = title
    return result


def _create_chat_history(num_messages: int = 4) -> List[Dict[str, Any]]:
    """Create a sample chat history list."""
    history = []
    for i in range(num_messages):
        role = "user" if i % 2 == 0 else "assistant"
        history.append({
            "id": i + 1,
            "role": role,
            "content": f"Test message {i + 1}",
            "message_type": "text",
            "created_at": datetime.utcnow().isoformat(),
        })
    return history


class TestVersionCreation:
    """Test save point creation and version numbering."""

    def test_create_version_valid_scenarios(self):
        """Test version creation with various valid inputs."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)

        # Mock database session and queries
        mock_session = MockSessionForVersions(session_id=1)
        mock_session.messages = [
            MockMessage(1, "user", "Create slides about AI"),
            MockMessage(2, "assistant", "Here are your slides"),
        ]

        deck_dict = _create_deck_dict(3)
        verification_map = {"hash1": {"status": "verified"}}

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            # Mock _get_session_or_raise to return our mock session
            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            # Mock query for max version (no existing versions)
            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query
            mock_query.first.return_value = None  # No existing versions
            mock_query.count.return_value = 0  # Below limit

            # Mock the add and flush - flush triggers created_at default
            def mock_add(obj):
                if hasattr(obj, 'created_at') and obj.created_at is None:
                    obj.created_at = datetime.utcnow()
            mock_db_session.add = MagicMock(side_effect=mock_add)
            mock_db_session.flush = MagicMock()

            # Test 1: First version creation (version_number = 1)
            result = sm.create_version(
                session_id="test-session",
                description="Generated 3 slides",
                deck_dict=deck_dict,
                verification_map=verification_map,
            )

            assert result["version_number"] == 1
            assert result["description"] == "Generated 3 slides"
            assert "created_at" in result
            assert result["slide_count"] == 3
            mock_db_session.add.assert_called_once()

            # Test 2: Verify chat history auto-captured when not provided
            added_version = mock_db_session.add.call_args[0][0]
            chat_history = json.loads(added_version.chat_history_json)
            assert len(chat_history) == 2
            assert chat_history[0]["role"] == "user"
            assert chat_history[1]["role"] == "assistant"

            # Test 3: Verify verification_map stored
            assert added_version.verification_map_json == json.dumps(verification_map)

    def test_create_version_error_handling(self):
        """Test version creation error handling."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)

        # Test: Session not found raises ValueError
        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(side_effect=ValueError("Session not found"))

            with pytest.raises(ValueError, match="Session not found"):
                sm.create_version(
                    session_id="nonexistent",
                    description="Test",
                    deck_dict={"slides": []},
                )

    def test_version_numbers_never_reused(self):
        """Version numbers should continue incrementing even after deletions."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query
            # Simulate existing version 5 (versions 1-4 deleted, 5 remains)
            mock_query.first.return_value = (5,)
            mock_query.count.return_value = 1

            def mock_add(obj):
                if hasattr(obj, 'created_at') and obj.created_at is None:
                    obj.created_at = datetime.utcnow()
            mock_db_session.add = MagicMock(side_effect=mock_add)
            mock_db_session.flush = MagicMock()

            result = sm.create_version(
                session_id="test-session",
                description="After deletions",
                deck_dict={"slides": []},
            )

            # Should be version 6, not 1
            assert result["version_number"] == 6


class TestVersionLimit:
    """Test version limit enforcement (40 max, oldest eviction)."""

    def test_version_limit_enforced(self):
        """When at limit, oldest version should be deleted before creating new one."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            # Set up query mocks
            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query

            # Simulate: max version is 40, count is 40 (at limit)
            mock_query.first.side_effect = [
                (40,),  # max version query
                MockVersionRecord(1, "oldest", "{}"),  # oldest version for deletion
            ]
            mock_query.count.return_value = 40  # At limit

            def mock_add(obj):
                if hasattr(obj, 'created_at') and obj.created_at is None:
                    obj.created_at = datetime.utcnow()
            mock_db_session.add = MagicMock(side_effect=mock_add)
            mock_db_session.flush = MagicMock()
            mock_db_session.delete = MagicMock()

            result = sm.create_version(
                session_id="test-session",
                description="Version at limit",
                deck_dict={"slides": []},
            )

            # Oldest version should have been deleted
            mock_db_session.delete.assert_called_once()

            # New version should be 41
            assert result["version_number"] == 41

    def test_below_limit_no_deletion(self):
        """When below limit, no versions should be deleted."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query
            mock_query.first.return_value = (10,)  # max version is 10
            mock_query.count.return_value = 10  # Below limit of 40

            def mock_add(obj):
                if hasattr(obj, 'created_at') and obj.created_at is None:
                    obj.created_at = datetime.utcnow()
            mock_db_session.add = MagicMock(side_effect=mock_add)
            mock_db_session.flush = MagicMock()
            mock_db_session.delete = MagicMock()

            sm.create_version(
                session_id="test-session",
                description="Normal version",
                deck_dict={"slides": []},
            )

            # No deletion should have occurred
            mock_db_session.delete.assert_not_called()


class TestVersionListing:
    """Test listing versions for a session."""

    def test_list_versions_ordered_newest_first(self):
        """Versions should be returned newest first."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        # Create mock version records
        v1 = MockVersionRecord(1, "Generated 3 slides", json.dumps({"slides": [{}] * 3}))
        v2 = MockVersionRecord(2, "Edited slide 1", json.dumps({"slides": [{}] * 3}))
        v3 = MockVersionRecord(3, "Added 2 slides", json.dumps({"slides": [{}] * 5}))

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query
            # Return in desc order (newest first)
            mock_query.all.return_value = [v3, v2, v1]

            result = sm.list_versions("test-session")

            assert len(result) == 3
            assert result[0]["version_number"] == 3
            assert result[1]["version_number"] == 2
            assert result[2]["version_number"] == 1
            assert result[0]["description"] == "Added 2 slides"
            assert result[0]["slide_count"] == 5

    def test_list_versions_empty_session(self):
        """Empty session should return empty list."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query
            mock_query.all.return_value = []

            result = sm.list_versions("test-session")

            assert result == []


class TestVersionPreview:
    """Test previewing a version (read-only, returns deck + chat history)."""

    def test_preview_returns_deck_and_chat_history(self):
        """Preview should return full deck snapshot, chat history, and verification."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        deck_dict = _create_deck_dict(3, title="AI Presentation")
        chat_history = _create_chat_history(4)
        verification_map = {"hash_abc": {"status": "verified", "score": 0.95}}

        mock_version = MockVersionRecord(
            version_number=2,
            description="Edited slide 1",
            deck_json=json.dumps(deck_dict),
            verification_map_json=json.dumps(verification_map),
            chat_history_json=json.dumps(chat_history),
        )

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = mock_version

            # Mock compute_slide_hash to return predictable hashes
            with patch("src.utils.slide_hash.compute_slide_hash", return_value="hash_abc"):
                result = sm.get_version("test-session", 2)

            # Should return version data
            assert result is not None
            assert result["version_number"] == 2
            assert result["description"] == "Edited slide 1"

            # Should include deck
            assert "deck" in result
            assert len(result["deck"]["slides"]) == 3

            # Should include chat history
            assert "chat_history" in result
            assert len(result["chat_history"]) == 4
            assert result["chat_history"][0]["role"] == "user"

            # Should include verification map
            assert "verification_map" in result

            # No writes should have happened
            mock_db_session.add.assert_not_called()
            mock_db_session.delete.assert_not_called()

    def test_preview_nonexistent_version(self):
        """Preview of nonexistent version should return None."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = None  # Version not found

            result = sm.get_version("test-session", 999)

            assert result is None


class TestVersionRestore:
    """Test restoring (reverting) to a previous version."""

    def test_restore_valid_scenarios(self):
        """Restore should revert deck, delete newer versions and messages."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)

        # Create mock session with slide deck
        mock_session = MockSessionForVersions(session_id=1)
        mock_slide_deck = MockSlideDeckRecord(session_id=1)
        mock_session.slide_deck = mock_slide_deck

        # Version 2 is the target for restore
        deck_dict_v2 = _create_deck_dict(3, title="Version 2 Deck")
        verification_map_v2 = {"hash_v2": {"status": "verified"}}
        chat_history_v2 = _create_chat_history(2)

        mock_version = MockVersionRecord(
            version_number=2,
            description="Edited slide 1",
            deck_json=json.dumps(deck_dict_v2),
            verification_map_json=json.dumps(verification_map_v2),
            chat_history_json=json.dumps(chat_history_v2),
            created_at=datetime.utcnow() - timedelta(hours=1),
        )

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = mock_version
            # Simulate: 2 newer versions deleted, 3 newer messages deleted
            mock_query.delete.side_effect = [2, 3]

            with patch("src.utils.slide_hash.compute_slide_hash", return_value="hash_v2"):
                result = sm.restore_version("test-session", 2)

            # Should return restored version data
            assert result["version_number"] == 2
            assert result["description"] == "Edited slide 1"
            assert result["deleted_versions"] == 2
            assert result["deleted_messages"] == 3

            # Should include deck and chat history
            assert "deck" in result
            assert len(result["deck"]["slides"]) == 3
            assert "chat_history" in result
            assert len(result["chat_history"]) == 2

            # Session slide deck should be updated
            assert mock_slide_deck.deck_json == json.dumps(deck_dict_v2)
            assert mock_slide_deck.slide_count == 3

    def test_restore_nonexistent_version_raises_error(self):
        """Restore to nonexistent version should raise ValueError."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = None  # Version not found

            with pytest.raises(ValueError, match="Version 999 not found"):
                sm.restore_version("test-session", 999)


class TestCreateSavePoint:
    """Test ChatService.create_save_point integration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.session_id = "test-session-123"

    def _create_chat_service(self) -> ChatService:
        """Create a ChatService with mocked dependencies."""
        mock_agent = MagicMock()
        service = ChatService.__new__(ChatService)
        service.agent = mock_agent
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)
        return service

    def test_create_save_point_from_cache(self):
        """Save point should use cached deck and fetch verification map."""
        service = self._create_chat_service()

        # Set up deck in cache
        deck = _create_test_deck(3)
        service._deck_cache[self.session_id] = deck

        mock_sm = MagicMock()
        mock_sm.get_verification_map.return_value = {"hash1": {"status": "verified"}}
        mock_sm.create_version.return_value = {
            "version_number": 1,
            "description": "Generated 3 slides",
            "created_at": datetime.utcnow().isoformat(),
            "slide_count": 3,
            "message_count": 0,
        }

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            result = service.create_save_point(self.session_id, "Generated 3 slides")

        assert result["version_number"] == 1
        assert result["description"] == "Generated 3 slides"

        # Verify create_version was called with correct args
        mock_sm.create_version.assert_called_once()
        call_kwargs = mock_sm.create_version.call_args
        assert call_kwargs.kwargs["session_id"] == self.session_id
        assert call_kwargs.kwargs["description"] == "Generated 3 slides"
        assert call_kwargs.kwargs["verification_map"] == {"hash1": {"status": "verified"}}

    def test_create_save_point_no_deck_raises_error(self):
        """Save point with no deck should raise ValueError."""
        service = self._create_chat_service()
        # No deck in cache

        mock_sm = MagicMock()
        mock_sm.get_slide_deck.return_value = None  # No deck in DB either

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            with pytest.raises(ValueError, match="No slide deck available"):
                service.create_save_point(self.session_id, "Should fail")


class TestReloadDeckFromDatabase:
    """Test cache invalidation after version restore."""

    def test_reload_clears_cache_and_reloads(self):
        """Reload should clear cache entry and load fresh from database."""
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()
        service._deck_cache = {}

        import threading
        service._cache_lock = threading.Lock()

        session_id = "test-session"

        # Put a stale deck in cache
        stale_deck = _create_test_deck(3)
        service._deck_cache[session_id] = stale_deck

        # Mock database to return a different deck
        fresh_deck_dict = _create_deck_dict(6, title="Fresh Deck")
        mock_sm = MagicMock()
        mock_sm.get_slide_deck.return_value = fresh_deck_dict

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            result = service.reload_deck_from_database(session_id)

        # Cache should have been cleared and reloaded
        assert result is not None
        # The reloaded deck should be from the database (6 slides)
        assert len(result.slides) == 6

    def test_reload_nonexistent_session(self):
        """Reload for nonexistent session should return None."""
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()
        service._deck_cache = {}

        import threading
        service._cache_lock = threading.Lock()

        mock_sm = MagicMock()
        mock_sm.get_slide_deck.return_value = None

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            result = service.reload_deck_from_database("nonexistent")

        assert result is None


class TestCurrentVersionNumber:
    """Test getting the current (latest) version number."""

    def test_get_current_version_valid_scenarios(self):
        """Should return latest version number or None."""
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)
        mock_session = MockSessionForVersions(session_id=1)

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.order_by.return_value = mock_query

            # Test with existing versions
            mock_query.first.return_value = (5,)
            result = sm.get_current_version_number("test-session")
            assert result == 5

            # Test with no versions
            mock_query.first.return_value = None
            result = sm.get_current_version_number("test-session")
            assert result is None
