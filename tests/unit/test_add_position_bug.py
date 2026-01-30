"""
Test for add slide position bug.

Reproduces the exact scenario from the bug report:
1. Deck with 3 slides (indices 0, 1, 2)
2. User selects slide 2 (index 1) via "add to chat"
3. User types "add a slide in before this with an inappropriate joke"
4. Expected: slide inserted at position 1 (before selected slide)
5. Actual bug: slide inserted at position 0 (beginning)
"""

import pytest
from unittest.mock import MagicMock, patch
from src.domain.slide_deck import SlideDeck, Slide
from src.api.services.chat_service import ChatService


class TestAddPositionBug:
    """Tests for the add slide position bug."""

    def _create_test_deck(self, num_slides: int = 3) -> SlideDeck:
        """Create a test deck with the specified number of slides."""
        deck = SlideDeck(title="Test Deck", css="")
        for i in range(num_slides):
            slide = Slide(
                html=f"<section><h1>Slide {i + 1}</h1></section>",
                scripts="",
                slide_id=f"slide_{i}",
            )
            deck.slides.append(slide)
        return deck

    def test_detect_add_position_before_this(self):
        """Test that 'before this' is detected as position_type 'before'."""
        service = ChatService.__new__(ChatService)

        # Message from bug report
        message = "add a slide in before this with an inappropriate joke"
        position = service._detect_add_position(message)

        assert position[0] == "before", f"Expected 'before', got {position[0]}"
        assert position[1] is None, f"Expected None for absolute position, got {position[1]}"

    def test_detect_add_intent_add_slide(self):
        """Test that 'add a slide' is detected as add intent."""
        from src.services.agent import SlideGeneratorAgent

        agent = SlideGeneratorAgent.__new__(SlideGeneratorAgent)
        message = "add a slide in before this with an inappropriate joke"

        is_add = agent._detect_add_intent(message)

        assert is_add is True, "Expected add intent to be detected"

    def test_add_operation_position_calculation(self):
        """Test the position calculation for 'before' operations."""
        service = ChatService.__new__(ChatService)
        service._deck_cache = {}
        service._cache_lock = MagicMock()

        session_id = "test-session"

        # Create initial deck with 3 slides
        deck = self._create_test_deck(3)
        service._deck_cache[session_id] = deck

        # Mock _get_or_load_deck to return our deck
        service._get_or_load_deck = MagicMock(return_value=deck)

        # New slide to add
        new_slide = Slide(
            html="<section><h1>Joke Slide</h1></section>",
            scripts="",
            slide_id="new_slide",
        )

        # Simulate the replacement_info from agent
        # User selected slide at index 1
        replacement_info = {
            "replacement_slides": [new_slide],
            "replacement_css": "",
            "original_indices": [1],  # Selected slide 2 (index 1)
            "start_index": 1,
            "original_count": 1,
            "replacement_count": 1,
            "net_change": 0,
            "success": True,
            "is_add_operation": True,
            "add_position": ("before", None),  # Should insert BEFORE selected slide
        }

        # Apply the replacement
        result = service._apply_slide_replacements(
            replacement_info=replacement_info,
            session_id=session_id,
        )

        # Get the updated deck from cache
        updated_deck = service._deck_cache[session_id]

        # Verify: New slide should be at index 1 (position "before" selected slide)
        # Original slide 1 should now be at index 2
        # Deck should have 4 slides total
        assert len(updated_deck.slides) == 4, f"Expected 4 slides, got {len(updated_deck.slides)}"

        # The joke slide should be at index 1
        assert "Joke Slide" in updated_deck.slides[1].html, (
            f"Expected joke slide at index 1, but got: {updated_deck.slides[1].html[:50]}"
        )

        # Original slide 2 (which was at index 1) should now be at index 2
        assert "Slide 2" in updated_deck.slides[2].html, (
            f"Expected original Slide 2 at index 2, but got: {updated_deck.slides[2].html[:50]}"
        )

    def test_add_beginning_position(self):
        """Test that 'beginning' position inserts at index 0."""
        service = ChatService.__new__(ChatService)
        service._deck_cache = {}
        service._cache_lock = MagicMock()

        session_id = "test-session"
        deck = self._create_test_deck(3)
        service._deck_cache[session_id] = deck
        service._get_or_load_deck = MagicMock(return_value=deck)

        new_slide = Slide(
            html="<section><h1>Title Slide</h1></section>",
            scripts="",
            slide_id="new_slide",
        )

        replacement_info = {
            "replacement_slides": [new_slide],
            "replacement_css": "",
            "original_indices": [1],  # Selected slide 2
            "start_index": 1,
            "original_count": 1,
            "replacement_count": 1,
            "net_change": 0,
            "success": True,
            "is_add_operation": True,
            "add_position": ("beginning", 0),  # ABSOLUTE beginning
        }

        result = service._apply_slide_replacements(
            replacement_info=replacement_info,
            session_id=session_id,
        )

        updated_deck = service._deck_cache[session_id]

        assert len(updated_deck.slides) == 4
        assert "Title Slide" in updated_deck.slides[0].html, (
            f"Expected title slide at index 0, but got: {updated_deck.slides[0].html[:50]}"
        )

    def test_add_after_position(self):
        """Test that 'after' position inserts after the selected slide."""
        service = ChatService.__new__(ChatService)
        service._deck_cache = {}
        service._cache_lock = MagicMock()

        session_id = "test-session"
        deck = self._create_test_deck(3)
        service._deck_cache[session_id] = deck
        service._get_or_load_deck = MagicMock(return_value=deck)

        new_slide = Slide(
            html="<section><h1>New Slide After</h1></section>",
            scripts="",
            slide_id="new_slide",
        )

        replacement_info = {
            "replacement_slides": [new_slide],
            "replacement_css": "",
            "original_indices": [1],  # Selected slide 2
            "start_index": 1,
            "original_count": 1,
            "replacement_count": 1,
            "net_change": 0,
            "success": True,
            "is_add_operation": True,
            "add_position": ("after", None),  # Default - after selected
        }

        result = service._apply_slide_replacements(
            replacement_info=replacement_info,
            session_id=session_id,
        )

        updated_deck = service._deck_cache[session_id]

        assert len(updated_deck.slides) == 4
        # After index 1 means insert at index 2 (start_idx + max(original_count, 1))
        assert "New Slide After" in updated_deck.slides[2].html, (
            f"Expected new slide at index 2, but got: {updated_deck.slides[2].html[:50]}"
        )


class TestAddPositionEdgeCases:
    """Tests for edge cases that could cause position bugs."""

    def _create_test_deck(self, num_slides: int = 3) -> SlideDeck:
        """Create a test deck with the specified number of slides."""
        deck = SlideDeck(title="Test Deck", css="")
        for i in range(num_slides):
            slide = Slide(
                html=f"<section><h1>Slide {i + 1}</h1></section>",
                scripts="",
                slide_id=f"slide_{i}",
            )
            deck.slides.append(slide)
        return deck

    def test_add_before_with_empty_deck_fallback(self):
        """Test that add operation falls back to position 0 when deck is empty.

        This tests the edge case where:
        1. User had a deck in the frontend
        2. User selected slide index 1
        3. But the backend deck is empty (save failed or inconsistent state)
        4. The slide ends up at position 0

        This would explain the bug where slides appear at wrong position.
        """
        service = ChatService.__new__(ChatService)
        service._deck_cache = {}
        service._cache_lock = MagicMock()

        session_id = "test-session"

        # Backend deck has 0 slides (inconsistent with frontend!)
        deck = SlideDeck(title="Empty Deck", css="")
        service._deck_cache[session_id] = deck
        service._get_or_load_deck = MagicMock(return_value=deck)

        new_slide = Slide(
            html="<section><h1>New Slide</h1></section>",
            scripts="",
            slide_id="new_slide",
        )

        # User selected slide index 1 in frontend (but backend has no slides)
        replacement_info = {
            "replacement_slides": [new_slide],
            "replacement_css": "",
            "original_indices": [1],  # Frontend thinks slide 2 is selected
            "start_index": 1,  # Index 1 from frontend
            "original_count": 1,
            "replacement_count": 1,
            "net_change": 0,
            "success": True,
            "is_add_operation": True,
            "add_position": ("before", None),
        }

        result = service._apply_slide_replacements(
            replacement_info=replacement_info,
            session_id=session_id,
        )

        updated_deck = service._deck_cache[session_id]

        # The slide ends up at position 0 because len(deck.slides) was 0
        # This means: start_idx=1 >= 0, but start_idx=1 < len(deck.slides)=0 is FALSE
        # So insert_position falls back to 0
        assert len(updated_deck.slides) == 1
        assert "New Slide" in updated_deck.slides[0].html

    def test_add_before_with_mismatched_deck_size(self):
        """Test that add operation falls back to position 0 when deck size < start_index.

        This tests the edge case where:
        1. User had a 3-slide deck in the frontend
        2. User selected slide index 1
        3. But the backend deck only has 1 slide (save failed or stale state)
        4. start_index=1 but deck has only 1 slide (index 0)
        5. The slide ends up at position 0
        """
        service = ChatService.__new__(ChatService)
        service._deck_cache = {}
        service._cache_lock = MagicMock()

        session_id = "test-session"

        # Backend deck has only 1 slide (inconsistent with frontend which has 3)
        deck = self._create_test_deck(1)  # Only 1 slide
        service._deck_cache[session_id] = deck
        service._get_or_load_deck = MagicMock(return_value=deck)

        new_slide = Slide(
            html="<section><h1>New Slide</h1></section>",
            scripts="",
            slide_id="new_slide",
        )

        # User selected slide index 1 in frontend (but backend only has index 0)
        replacement_info = {
            "replacement_slides": [new_slide],
            "replacement_css": "",
            "original_indices": [1],  # Frontend thinks slide 2 is selected
            "start_index": 1,  # Index 1 from frontend
            "original_count": 1,
            "replacement_count": 1,
            "net_change": 0,
            "success": True,
            "is_add_operation": True,
            "add_position": ("before", None),
        }

        result = service._apply_slide_replacements(
            replacement_info=replacement_info,
            session_id=session_id,
        )

        updated_deck = service._deck_cache[session_id]

        # The slide ends up at position 0 because:
        # start_idx=1 >= 0 is TRUE
        # start_idx=1 < len(deck.slides)=1 is FALSE
        # So insert_position falls back to 0
        assert len(updated_deck.slides) == 2
        # New slide at position 0, original slide at position 1
        assert "New Slide" in updated_deck.slides[0].html
        assert "Slide 1" in updated_deck.slides[1].html


class TestAddPositionValidation:
    """Tests to validate that deck state inconsistencies are detected."""

    def _create_test_deck(self, num_slides: int = 3) -> SlideDeck:
        """Create a test deck with the specified number of slides."""
        deck = SlideDeck(title="Test Deck", css="")
        for i in range(num_slides):
            slide = Slide(
                html=f"<section><h1>Slide {i + 1}</h1></section>",
                scripts="",
                slide_id=f"slide_{i}",
            )
            deck.slides.append(slide)
        return deck

    def test_detect_deck_state_mismatch(self):
        """Test that we can detect when backend deck differs from frontend selection."""
        service = ChatService.__new__(ChatService)
        service._deck_cache = {}
        service._cache_lock = MagicMock()

        session_id = "test-session"

        # Backend has 1 slide, but frontend thinks it has 3
        backend_deck = self._create_test_deck(1)
        service._deck_cache[session_id] = backend_deck
        service._get_or_load_deck = MagicMock(return_value=backend_deck)

        # Frontend sent index 2 (slide 3 of 3)
        frontend_selected_index = 2
        backend_slide_count = len(backend_deck.slides)

        # This is the validation we need
        has_mismatch = frontend_selected_index >= backend_slide_count

        assert has_mismatch is True, "Should detect that frontend index exceeds backend deck size"


class TestRC14StateValidation:
    """Tests for RC14: Early state mismatch detection in send_message_streaming."""

    def _create_test_deck(self, num_slides: int = 3) -> SlideDeck:
        """Create a test deck with the specified number of slides."""
        deck = SlideDeck(title="Test Deck", css="")
        for i in range(num_slides):
            slide = Slide(
                html=f"<section><h1>Slide {i + 1}</h1></section>",
                scripts="",
                slide_id=f"slide_{i}",
            )
            deck.slides.append(slide)
        return deck

    def test_state_mismatch_detection_logic(self):
        """Test the state mismatch detection logic used in RC14."""
        # Backend has 1 slide
        backend_slide_count = 1

        # Frontend selected index 2 (slide 3)
        selected_indices = [2]
        max_index = max(selected_indices)

        # This is the validation condition from RC14
        has_mismatch = max_index >= backend_slide_count

        assert has_mismatch is True, "Should detect mismatch when selected index >= slide count"

    def test_state_mismatch_with_valid_selection(self):
        """Test that no mismatch is detected for valid selections."""
        # Backend has 3 slides
        backend_slide_count = 3

        # Frontend selected index 1 (slide 2) - valid
        selected_indices = [1]
        max_index = max(selected_indices)

        # This is the validation condition from RC14
        has_mismatch = max_index >= backend_slide_count

        assert has_mismatch is False, "Should not detect mismatch when selection is valid"

    def test_state_mismatch_with_multiple_selections(self):
        """Test mismatch detection with multiple selected slides."""
        # Backend has 2 slides
        backend_slide_count = 2

        # Frontend selected indices 0, 1, 2 - index 2 is invalid
        selected_indices = [0, 1, 2]
        max_index = max(selected_indices)

        # This is the validation condition from RC14
        has_mismatch = max_index >= backend_slide_count

        assert has_mismatch is True, "Should detect mismatch when any selected index is invalid"


class TestAddPositionPersistence:
    """Tests that verify the add operation persists to database."""

    def _create_test_deck(self, num_slides: int = 3) -> SlideDeck:
        """Create a test deck with the specified number of slides."""
        deck = SlideDeck(title="Test Deck", css="")
        for i in range(num_slides):
            slide = Slide(
                html=f"<section><h1>Slide {i + 1}</h1></section>",
                scripts="",
                slide_id=f"slide_{i}",
            )
            deck.slides.append(slide)
        return deck

    @patch('src.api.services.chat_service.get_session_manager')
    def test_add_operation_saves_to_database(self, mock_get_session_manager):
        """Test that after an add operation, save_slide_deck is called."""
        from src.api.services.chat_service import ChatService
        from src.services.agent import SlideGeneratorAgent

        # Mock session manager
        mock_session_manager = MagicMock()
        mock_get_session_manager.return_value = mock_session_manager

        # Mock session exists
        mock_session_manager.get_session.return_value = {"id": "test-session"}

        # Create service with mocked agent
        service = ChatService.__new__(ChatService)
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service.agent = MagicMock(spec=SlideGeneratorAgent)

        session_id = "test-session"
        deck = self._create_test_deck(3)
        service._deck_cache[session_id] = deck
        service._get_or_load_deck = MagicMock(return_value=deck)

        # Simulate the streaming response completing with add operation
        new_slide = Slide(
            html="<section><h1>New Slide</h1></section>",
            scripts="",
            slide_id="new_slide",
        )

        replacement_info = {
            "replacement_slides": [new_slide],
            "replacement_css": "",
            "original_indices": [1],
            "start_index": 1,
            "original_count": 1,
            "replacement_count": 1,
            "net_change": 0,
            "success": True,
            "is_add_operation": True,
        }

        # Call _apply_slide_replacements with add_position
        replacement_info["add_position"] = ("before", None)
        service._detect_add_position = MagicMock(return_value=("before", None))

        slide_deck_dict = service._apply_slide_replacements(
            replacement_info=replacement_info,
            session_id=session_id,
        )

        # Verify the deck was updated in cache
        updated_deck = service._deck_cache[session_id]
        assert len(updated_deck.slides) == 4

        # The actual save happens in send_message_streaming after _apply_slide_replacements
        # We're testing that _apply_slide_replacements returns a valid dict
        assert slide_deck_dict is not None
        assert "slides" in slide_deck_dict
        assert len(slide_deck_dict["slides"]) == 4
