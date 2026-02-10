"""Deck persistence tests.

These tests validate that all deck operations are correctly persisted to the database.
The key invariant is:
    Operation(cache) -> Save(database) -> Load(database) == Expected_State

Each test ensures that after an operation:
1. The operation succeeds in memory/cache
2. The change is saved to the database
3. Loading from database (simulating restart) returns the correct state
4. No data is lost between save and load

This suite addresses the issue where local state appears correct but changes
are lost after page refresh or session restore.
"""

import pytest
import json
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Dict, Any, Optional, List

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.api.services.chat_service import ChatService

from tests.fixtures.html import (
    load_3_slide_deck,
    load_6_slide_deck,
    generate_chart_slide,
    generate_content_slide,
)


class MockSessionManager:
    """Mock session manager that simulates database persistence."""

    def __init__(self):
        self.saved_decks: Dict[str, Dict[str, Any]] = {}
        self.save_calls: List[Dict[str, Any]] = []
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._lock_held: Dict[str, bool] = {}

    def save_slide_deck(
        self,
        session_id: str,
        title: Optional[str],
        html_content: str,
        scripts_content: Optional[str] = None,
        slide_count: int = 0,
        deck_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Simulate saving deck to database."""
        self.save_calls.append({
            "session_id": session_id,
            "title": title,
            "html_content": html_content,
            "scripts_content": scripts_content,
            "slide_count": slide_count,
            "deck_dict": deck_dict,
        })

        self.saved_decks[session_id] = {
            "session_id": session_id,
            "title": title,
            "html_content": html_content,
            "scripts_content": scripts_content,
            "slide_count": slide_count,
            "slides": deck_dict.get("slides", []) if deck_dict else [],
            "css": deck_dict.get("css", "") if deck_dict else "",
        }

        return {"session_id": session_id, "slide_count": slide_count}

    def get_slide_deck(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Simulate loading deck from database."""
        return self.saved_decks.get(session_id)

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session info."""
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "id": session_id,
                "profile_id": None,
                "profile_name": None,
                "genie_conversation_id": None,
            }
        return self.sessions[session_id]

    def create_session(self, session_id: str, **kwargs) -> Dict[str, Any]:
        """Create a new session."""
        self.sessions[session_id] = {
            "id": session_id,
            **kwargs,
        }
        return self.sessions[session_id]

    def update_last_activity(self, session_id: str):
        """Update session activity timestamp."""
        pass

    def add_message(self, session_id: str, role: str, content: str, message_type: str = "text"):
        """Add message to session."""
        pass

    def acquire_session_lock(self, session_id: str) -> bool:
        """Acquire session lock."""
        if self._lock_held.get(session_id):
            return False
        self._lock_held[session_id] = True
        return True

    def release_session_lock(self, session_id: str):
        """Release session lock."""
        self._lock_held[session_id] = False

    def get_verification_map(self, session_id: str) -> Dict[str, Any]:
        """Get verification map for a session."""
        return {}

    def create_version(
        self,
        session_id: str,
        description: str,
        deck_dict: Dict[str, Any],
        verification_map: Optional[Dict[str, Any]] = None,
        chat_history: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Simulate creating a save point version."""
        return {
            "version_number": 1,
            "description": description,
            "created_at": "2026-01-01T00:00:00",
            "slide_count": len(deck_dict.get("slides", [])),
            "message_count": 0,
        }

    def clear_saved_data(self):
        """Clear all saved data (simulate fresh database)."""
        self.saved_decks.clear()
        self.save_calls.clear()

    def get_save_count(self) -> int:
        """Get number of save calls made."""
        return len(self.save_calls)

    def get_last_save(self) -> Optional[Dict[str, Any]]:
        """Get the most recent save call."""
        return self.save_calls[-1] if self.save_calls else None


class TestPersistenceBasics:
    """Test basic persistence functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_session_manager = MockSessionManager()
        self.session_id = "test-session-123"

    def _create_chat_service_with_mock(self) -> ChatService:
        """Create a ChatService with mocked dependencies."""
        with patch('src.api.services.chat_service.get_session_manager') as mock_get_sm:
            mock_get_sm.return_value = self.mock_session_manager

            # Create service with mocked agent
            mock_agent = MagicMock()
            service = ChatService.__new__(ChatService)
            service.agent = mock_agent
            service._deck_cache = {}
            service._cache_lock = MagicMock()
            service._cache_lock.__enter__ = MagicMock(return_value=None)
            service._cache_lock.__exit__ = MagicMock(return_value=None)

            return service

    def _setup_deck_in_cache(self, service: ChatService, html: str) -> SlideDeck:
        """Set up a deck in the service cache."""
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[self.session_id] = deck
        return deck

    def test_reorder_persists_to_database(self):
        """Reordering slides should save to database."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)
        original_count = len(deck.slides)

        # Get original order
        original_first_html = deck.slides[0].html
        original_second_html = deck.slides[1].html

        # Reorder: swap first two slides
        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            result = service.reorder_slides(self.session_id, [1, 0, 2, 3, 4, 5])

        # Verify save was called
        assert self.mock_session_manager.get_save_count() == 1

        # Verify saved data
        saved = self.mock_session_manager.get_last_save()
        assert saved is not None
        assert saved["session_id"] == self.session_id
        assert saved["slide_count"] == original_count
        assert saved["deck_dict"] is not None

        # Verify order changed in saved data
        saved_slides = saved["deck_dict"]["slides"]
        assert saved_slides[0]["html"] == original_second_html
        assert saved_slides[1]["html"] == original_first_html

    def test_update_slide_persists_to_database(self):
        """Updating a slide's HTML should save to database."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        self._setup_deck_in_cache(service, html)

        new_html = '<div class="slide"><h1>Updated Title</h1></div>'

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            result = service.update_slide(self.session_id, 0, new_html)

        # Verify save was called
        assert self.mock_session_manager.get_save_count() == 1

        # Verify saved data contains the update
        saved = self.mock_session_manager.get_last_save()
        assert saved is not None
        saved_slides = saved["deck_dict"]["slides"]
        assert "Updated Title" in saved_slides[0]["html"]

    def test_delete_slide_persists_to_database(self):
        """Deleting a slide should save to database."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)
        original_count = len(deck.slides)

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            result = service.delete_slide(self.session_id, 2)

        # Verify save was called
        assert self.mock_session_manager.get_save_count() == 1

        # Verify slide count decreased
        saved = self.mock_session_manager.get_last_save()
        assert saved["slide_count"] == original_count - 1
        assert len(saved["deck_dict"]["slides"]) == original_count - 1

    def test_duplicate_slide_persists_to_database(self):
        """Duplicating a slide should save to database."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)
        original_count = len(deck.slides)

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            result = service.duplicate_slide(self.session_id, 0)

        # Verify save was called
        assert self.mock_session_manager.get_save_count() == 1

        # Verify slide count increased
        saved = self.mock_session_manager.get_last_save()
        assert saved["slide_count"] == original_count + 1
        assert len(saved["deck_dict"]["slides"]) == original_count + 1


class TestPersistenceAfterRestart:
    """Test that changes survive simulated restarts (cache clear + reload)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_session_manager = MockSessionManager()
        self.session_id = "test-session-456"

    def _create_chat_service_with_mock(self) -> ChatService:
        """Create a ChatService with mocked dependencies."""
        mock_agent = MagicMock()
        service = ChatService.__new__(ChatService)
        service.agent = mock_agent
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)
        return service

    def _setup_deck_in_cache(self, service: ChatService, html: str) -> SlideDeck:
        """Set up a deck in the service cache."""
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[self.session_id] = deck
        return deck

    def _simulate_restart(self, service: ChatService):
        """Simulate a backend restart by clearing the cache."""
        service._deck_cache.clear()

    def test_reorder_survives_restart(self):
        """Reordered slides should be preserved after restart."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)

        # Get original slide IDs/content for verification
        original_second_html = deck.slides[1].html

        # Reorder
        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.reorder_slides(self.session_id, [1, 0, 2, 3, 4, 5])

        # Simulate restart
        self._simulate_restart(service)

        # Load from "database"
        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            loaded_deck = service._get_or_load_deck(self.session_id)

        # Verify the reorder persisted
        assert loaded_deck is not None
        assert loaded_deck.slides[0].html == original_second_html

    def test_update_survives_restart(self):
        """Updated slide content should be preserved after restart."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        self._setup_deck_in_cache(service, html)

        new_html = '<div class="slide"><h1>Persistent Update</h1></div>'

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.update_slide(self.session_id, 0, new_html)

        # Simulate restart
        self._simulate_restart(service)

        # Load from "database"
        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            loaded_deck = service._get_or_load_deck(self.session_id)

        # Verify update persisted
        assert loaded_deck is not None
        assert "Persistent Update" in loaded_deck.slides[0].html

    def test_delete_survives_restart(self):
        """Deleted slides should stay deleted after restart."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)
        original_count = len(deck.slides)

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.delete_slide(self.session_id, 0)

        # Simulate restart
        self._simulate_restart(service)

        # Load from "database"
        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            loaded_deck = service._get_or_load_deck(self.session_id)

        # Verify delete persisted
        assert loaded_deck is not None
        assert len(loaded_deck.slides) == original_count - 1

    def test_duplicate_survives_restart(self):
        """Duplicated slides should persist after restart."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)
        original_count = len(deck.slides)
        original_first_html = deck.slides[0].html

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.duplicate_slide(self.session_id, 0)

        # Simulate restart
        self._simulate_restart(service)

        # Load from "database"
        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            loaded_deck = service._get_or_load_deck(self.session_id)

        # Verify duplicate persisted
        assert loaded_deck is not None
        assert len(loaded_deck.slides) == original_count + 1
        # Both first and second slide should have same content
        assert loaded_deck.slides[0].html == original_first_html
        assert loaded_deck.slides[1].html == original_first_html


class TestMultipleOperationsPersistence:
    """Test that multiple sequential operations all persist correctly."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_session_manager = MockSessionManager()
        self.session_id = "test-session-789"

    def _create_chat_service_with_mock(self) -> ChatService:
        """Create a ChatService with mocked dependencies."""
        mock_agent = MagicMock()
        service = ChatService.__new__(ChatService)
        service.agent = mock_agent
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)
        return service

    def _setup_deck_in_cache(self, service: ChatService, html: str) -> SlideDeck:
        """Set up a deck in the service cache."""
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[self.session_id] = deck
        return deck

    def test_multiple_edits_all_persist(self):
        """Multiple edits should all be saved."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        self._setup_deck_in_cache(service, html)

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            # Edit slide 0
            service.update_slide(self.session_id, 0, '<div class="slide"><h1>Edit 1</h1></div>')
            # Edit slide 1
            service.update_slide(self.session_id, 1, '<div class="slide"><h1>Edit 2</h1></div>')
            # Edit slide 2
            service.update_slide(self.session_id, 2, '<div class="slide"><h1>Edit 3</h1></div>')

        # Verify all saves happened
        assert self.mock_session_manager.get_save_count() == 3

        # Verify final state
        final_save = self.mock_session_manager.get_last_save()
        slides = final_save["deck_dict"]["slides"]
        assert "Edit 1" in slides[0]["html"]
        assert "Edit 2" in slides[1]["html"]
        assert "Edit 3" in slides[2]["html"]

    def test_mixed_operations_persist(self):
        """Mix of different operations should all persist."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)
        original_count = len(deck.slides)

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            # Duplicate slide 0
            service.duplicate_slide(self.session_id, 0)
            # Delete slide 3
            service.delete_slide(self.session_id, 3)
            # Edit slide 1
            service.update_slide(self.session_id, 1, '<div class="slide"><h1>Mixed Op Edit</h1></div>')
            # Reorder
            service.reorder_slides(self.session_id, [1, 0, 2, 3, 4, 5])

        # Verify all saves happened
        assert self.mock_session_manager.get_save_count() == 4

        # Verify final slide count (original + 1 duplicate - 1 delete = original)
        final_save = self.mock_session_manager.get_last_save()
        assert final_save["slide_count"] == original_count


class TestScriptPersistence:
    """Test that slide scripts (Chart.js) are correctly persisted."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_session_manager = MockSessionManager()
        self.session_id = "test-session-scripts"

    def _create_chat_service_with_mock(self) -> ChatService:
        """Create a ChatService with mocked dependencies."""
        mock_agent = MagicMock()
        service = ChatService.__new__(ChatService)
        service.agent = mock_agent
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)
        return service

    def _setup_deck_in_cache(self, service: ChatService, html: str) -> SlideDeck:
        """Set up a deck in the service cache."""
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[self.session_id] = deck
        return deck

    def test_scripts_preserved_on_reorder(self):
        """Slide scripts should be preserved when reordering."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)

        # Find slides with scripts
        slides_with_scripts = [(i, s.scripts) for i, s in enumerate(deck.slides) if s.scripts]

        if slides_with_scripts:
            original_idx, original_script = slides_with_scripts[0]

            with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
                # Move scripted slide to end
                new_order = list(range(len(deck.slides)))
                new_order.remove(original_idx)
                new_order.append(original_idx)
                service.reorder_slides(self.session_id, new_order)

            # Verify scripts are in saved data
            saved = self.mock_session_manager.get_last_save()
            saved_slides = saved["deck_dict"]["slides"]

            # The slide should be at the end now
            last_slide = saved_slides[-1]
            assert last_slide.get("scripts") is not None
            assert len(last_slide["scripts"]) > 0

    def test_scripts_preserved_on_duplicate(self):
        """Duplicated slides should retain their scripts."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)

        # Find a slide with scripts
        scripted_idx = None
        original_script = None
        for i, slide in enumerate(deck.slides):
            if slide.scripts:
                scripted_idx = i
                original_script = slide.scripts
                break

        if scripted_idx is not None:
            with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
                service.duplicate_slide(self.session_id, scripted_idx)

            # Verify both original and duplicate have scripts
            saved = self.mock_session_manager.get_last_save()
            saved_slides = saved["deck_dict"]["slides"]

            # Original at scripted_idx, duplicate at scripted_idx + 1
            assert saved_slides[scripted_idx].get("scripts") is not None
            assert saved_slides[scripted_idx + 1].get("scripts") is not None

    def test_chart_scripts_survive_html_edit(self):
        """Chart.js scripts should survive when editing a slide's HTML content."""
        service = self._create_chat_service_with_mock()

        # Manually create a deck with chart slides that have scripts
        chart_html, chart_script = generate_chart_slide(
            title="Revenue", canvas_id="revenueChart"
        )
        content_html = generate_content_slide(title="Summary")

        slide_0 = Slide(html=chart_html, slide_id="slide_0", scripts=chart_script)
        slide_1 = Slide(html=content_html, slide_id="slide_1")
        deck = SlideDeck(slides=[slide_0, slide_1], css="")
        service._deck_cache[self.session_id] = deck

        # Edit the content slide (should not affect chart scripts)
        new_html = '<div class="slide"><h1>Updated Summary</h1></div>'

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.update_slide(self.session_id, 1, new_html)

        saved = self.mock_session_manager.get_last_save()
        saved_slides = saved["deck_dict"]["slides"]

        # Chart slide script should be preserved
        assert saved_slides[0].get("scripts") is not None
        assert "revenueChart" in saved_slides[0]["scripts"]

    def test_reconstruct_from_dict_preserves_scripts(self):
        """Saving to dict then reconstructing should preserve all scripts."""
        service = self._create_chat_service_with_mock()

        # Create deck with chart
        chart_html, chart_script = generate_chart_slide(
            title="Growth", canvas_id="growthChart"
        )
        slide = Slide(html=chart_html, slide_id="slide_0", scripts=chart_script)
        deck = SlideDeck(slides=[slide], css=".test { }")

        # Save to dict
        deck_dict = deck.to_dict()

        # Verify scripts are in the dict
        assert deck_dict["slides"][0].get("scripts") is not None
        assert "growthChart" in deck_dict["slides"][0]["scripts"]

        # Reconstruct from dict
        reconstructed = service._reconstruct_deck_from_dict(deck_dict)

        # Scripts should match
        assert reconstructed.slides[0].scripts == chart_script


class TestCSSPersistence:
    """Test that CSS is correctly persisted."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_session_manager = MockSessionManager()
        self.session_id = "test-session-css"

    def _create_chat_service_with_mock(self) -> ChatService:
        """Create a ChatService with mocked dependencies."""
        mock_agent = MagicMock()
        service = ChatService.__new__(ChatService)
        service.agent = mock_agent
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)
        return service

    def _setup_deck_in_cache(self, service: ChatService, html: str) -> SlideDeck:
        """Set up a deck in the service cache."""
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[self.session_id] = deck
        return deck

    def test_css_preserved_on_operations(self):
        """CSS should be preserved through all operations."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)
        original_css = deck.css

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.reorder_slides(self.session_id, [1, 0, 2, 3, 4, 5])

        # Verify CSS is in saved data
        saved = self.mock_session_manager.get_last_save()
        assert saved["deck_dict"].get("css") is not None
        # CSS should be preserved
        assert len(saved["deck_dict"]["css"]) > 0


class TestEdgeCases:
    """Test edge cases that might cause persistence failures."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_session_manager = MockSessionManager()
        self.session_id = "test-session-edge"

    def _create_chat_service_with_mock(self) -> ChatService:
        """Create a ChatService with mocked dependencies."""
        mock_agent = MagicMock()
        service = ChatService.__new__(ChatService)
        service.agent = mock_agent
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)
        return service

    def _setup_deck_in_cache(self, service: ChatService, html: str) -> SlideDeck:
        """Set up a deck in the service cache."""
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[self.session_id] = deck
        return deck

    def test_empty_html_content_still_saves(self):
        """Slides with minimal content should still save."""
        service = self._create_chat_service_with_mock()
        html = load_3_slide_deck()
        self._setup_deck_in_cache(service, html)

        # Update with minimal but valid HTML
        minimal_html = '<div class="slide"></div>'

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.update_slide(self.session_id, 0, minimal_html)

        # Verify save was called
        assert self.mock_session_manager.get_save_count() == 1
        saved = self.mock_session_manager.get_last_save()
        assert saved["deck_dict"]["slides"][0]["html"] == minimal_html

    def test_special_characters_in_content_save(self):
        """Content with special characters should save correctly."""
        service = self._create_chat_service_with_mock()
        html = load_3_slide_deck()
        self._setup_deck_in_cache(service, html)

        # HTML with special characters
        special_html = '<div class="slide"><h1>Test &amp; "Quotes" &lt;Tags&gt;</h1></div>'

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.update_slide(self.session_id, 0, special_html)

        saved = self.mock_session_manager.get_last_save()
        assert saved["deck_dict"]["slides"][0]["html"] == special_html

    def test_unicode_content_saves(self):
        """Unicode content should save correctly."""
        service = self._create_chat_service_with_mock()
        html = load_3_slide_deck()
        self._setup_deck_in_cache(service, html)

        # HTML with unicode
        unicode_html = '<div class="slide"><h1>日本語 emoji 🎉 中文</h1></div>'

        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            service.update_slide(self.session_id, 0, unicode_html)

        saved = self.mock_session_manager.get_last_save()
        assert saved["deck_dict"]["slides"][0]["html"] == unicode_html

    def test_large_deck_saves(self):
        """Large decks should save correctly."""
        service = self._create_chat_service_with_mock()
        html = load_6_slide_deck()
        deck = self._setup_deck_in_cache(service, html)

        # Add many slides via duplicate
        with patch('src.api.services.chat_service.get_session_manager', return_value=self.mock_session_manager):
            for _ in range(10):
                service.duplicate_slide(self.session_id, 0)

        # Verify final save has all slides
        saved = self.mock_session_manager.get_last_save()
        assert saved["slide_count"] == 16  # 6 original + 10 duplicates


class TestSaveFailureHandling:
    """Test behavior when save operations might fail."""

    def setup_method(self):
        """Set up test fixtures."""
        self.session_id = "test-session-failure"

    def test_save_exception_propagates(self):
        """Exceptions during save should propagate to caller."""
        mock_session_manager = MockSessionManager()

        # Make save raise an exception
        def failing_save(*args, **kwargs):
            raise Exception("Database write failed")

        mock_session_manager.save_slide_deck = failing_save

        mock_agent = MagicMock()
        service = ChatService.__new__(ChatService)
        service.agent = mock_agent
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)

        html = load_3_slide_deck()
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[self.session_id] = deck

        with patch('src.api.services.chat_service.get_session_manager', return_value=mock_session_manager):
            with pytest.raises(Exception, match="Database write failed"):
                service.update_slide(self.session_id, 0, '<div class="slide"><h1>Test</h1></div>')
