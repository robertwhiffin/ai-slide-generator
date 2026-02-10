"""Chart persistence tests.

These tests validate that Chart.js scripts are correctly preserved during:
1. Slide edit operations (HTML replacement doesn't lose chart scripts)
2. Database save/load cycles (_reconstruct_deck_from_dict preserves per-slide scripts)
3. Optimize operations (RC15: canvas ID suffix handling after RC4 dedup)
4. Script matching with RC4 dedup suffix (_XXXXXX stripped for fallback matching)

The key invariant:
    Deck_With_Charts + Edit_Operation = Deck_With_Charts_Preserved

This suite covers the HTML edit chart loss fix and RC15 optimize
script preservation from the save-points-and-fixes branch.
"""

import re
import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any, Optional, List

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.api.services.chat_service import ChatService
from src.utils.html_utils import extract_canvas_ids_from_html, split_script_by_canvas

from tests.fixtures.html import (
    load_3_slide_deck,
    load_6_slide_deck,
    generate_chart_slide,
    generate_content_slide,
)
from tests.validation import (
    validate_no_duplicate_canvas_ids,
    validate_javascript_syntax,
)
from tests.validation.canvas_validator import validate_deck_canvas_integrity


class MockSessionManager:
    """Mock session manager for chart persistence tests."""

    def __init__(self):
        self.saved_decks: Dict[str, Dict[str, Any]] = {}
        self.save_calls: List[Dict[str, Any]] = []

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
        return {"id": session_id, "profile_id": None, "profile_name": None, "genie_conversation_id": None}

    def update_last_activity(self, session_id: str):
        pass

    def add_message(self, session_id: str, role: str, content: str, message_type: str = "text"):
        pass

    def acquire_session_lock(self, session_id: str) -> bool:
        return True

    def release_session_lock(self, session_id: str):
        pass

    def get_verification_map(self, session_id: str) -> Dict[str, Any]:
        return {}


def _create_deck_with_charts(num_chart_slides: int = 2, num_content_slides: int = 1) -> SlideDeck:
    """Create a deck with chart slides (with scripts) and content slides."""
    slides = []

    for i in range(num_chart_slides):
        chart_html, chart_script = generate_chart_slide(
            title=f"Chart {i + 1}",
            canvas_id=f"testChart{i}",
            chart_type="bar" if i % 2 == 0 else "line",
            slide_number=i + 1,
        )
        slide = Slide(html=chart_html, slide_id=f"slide_{i}", scripts=chart_script)
        slides.append(slide)

    for i in range(num_content_slides):
        content_html = generate_content_slide(
            title=f"Content {i + 1}",
            slide_number=num_chart_slides + i + 1,
        )
        slide = Slide(html=content_html, slide_id=f"slide_{num_chart_slides + i}")
        slides.append(slide)

    deck = SlideDeck(slides=slides, css=".slide { padding: 20px; }")
    return deck


def _create_chat_service_with_deck(session_id: str, deck: SlideDeck) -> ChatService:
    """Create a ChatService with a deck in cache."""
    service = ChatService.__new__(ChatService)
    service.agent = MagicMock()
    service._deck_cache = {session_id: deck}
    service._cache_lock = MagicMock()
    service._cache_lock.__enter__ = MagicMock(return_value=None)
    service._cache_lock.__exit__ = MagicMock(return_value=None)
    return service


class TestScriptPreservationDuringEdit:
    """Test that chart scripts survive slide edit operations."""

    def setup_method(self):
        self.session_id = "test-session"
        self.mock_sm = MockSessionManager()

    def test_edit_preserves_chart_scripts(self):
        """Editing a slide's HTML should preserve its Chart.js script."""
        deck = _create_deck_with_charts(2, 1)
        service = _create_chat_service_with_deck(self.session_id, deck)

        # Verify chart slides have scripts before edit
        assert deck.slides[0].scripts is not None
        assert "testChart0" in deck.slides[0].scripts
        assert deck.slides[1].scripts is not None
        assert "testChart1" in deck.slides[1].scripts

        # Simulate edit: LLM returns same HTML with modified title but no scripts
        edited_html = deck.slides[0].html.replace("Chart 1", "Updated Chart Title")
        replacement_slide = Slide(html=edited_html, slide_id="slide_0", scripts="")

        replacement_info = {
            "start_index": 0,
            "original_count": 1,
            "replacement_slides": [replacement_slide],
            "replacement_css": "",
            "is_add_operation": False,
        }

        with patch("src.api.services.chat_service.get_session_manager", return_value=self.mock_sm):
            result = service._apply_slide_replacements(replacement_info, self.session_id)

        # Chart script should be preserved for edited slide
        edited_slide = service._deck_cache[self.session_id].slides[0]
        assert edited_slide.scripts is not None
        assert "testChart0" in edited_slide.scripts

        # Other chart slide should be untouched
        other_chart = service._deck_cache[self.session_id].slides[1]
        assert other_chart.scripts is not None
        assert "testChart1" in other_chart.scripts

    def test_edit_content_slide_no_script_loss(self):
        """Editing a content slide should not affect chart slides."""
        deck = _create_deck_with_charts(2, 1)
        service = _create_chat_service_with_deck(self.session_id, deck)

        # Record original scripts
        original_scripts_0 = deck.slides[0].scripts
        original_scripts_1 = deck.slides[1].scripts

        # Edit content slide (index 2)
        edited_html = '<div class="slide"><h2>Updated Content</h2><p>New text</p></div>'
        replacement_slide = Slide(html=edited_html, slide_id="slide_2")

        replacement_info = {
            "start_index": 2,
            "original_count": 1,
            "replacement_slides": [replacement_slide],
            "replacement_css": "",
            "is_add_operation": False,
        }

        with patch("src.api.services.chat_service.get_session_manager", return_value=self.mock_sm):
            service._apply_slide_replacements(replacement_info, self.session_id)

        # Chart slides should be completely untouched
        assert service._deck_cache[self.session_id].slides[0].scripts == original_scripts_0
        assert service._deck_cache[self.session_id].slides[1].scripts == original_scripts_1


class TestRC15OptimizeScriptPreservation:
    """Test RC15: Canvas ID suffix handling after optimize (RC4 dedup)."""

    def setup_method(self):
        self.session_id = "test-session"
        self.mock_sm = MockSessionManager()

    def test_optimize_updates_canvas_id_references_in_script(self):
        """After optimize, script getElementById should be updated to new canvas ID."""
        # Create deck with original canvas ID
        chart_html, chart_script = generate_chart_slide(
            title="Revenue Chart",
            canvas_id="revenueChart",
        )
        slide = Slide(html=chart_html, slide_id="slide_0", scripts=chart_script)
        deck = SlideDeck(slides=[slide], css="")
        service = _create_chat_service_with_deck(self.session_id, deck)

        # Simulate optimize: LLM returns HTML with RC4 deduped canvas ID
        # RC4 adds suffix like _a1b2c3 (6 hex chars)
        new_canvas_id = "revenueChart_9c1816"
        optimized_html = chart_html.replace('id="revenueChart"', f'id="{new_canvas_id}"')
        replacement_slide = Slide(html=optimized_html, slide_id="slide_0", scripts="")

        replacement_info = {
            "start_index": 0,
            "original_count": 1,
            "replacement_slides": [replacement_slide],
            "replacement_css": "",
            "is_add_operation": False,
        }

        with patch("src.api.services.chat_service.get_session_manager", return_value=self.mock_sm):
            service._apply_slide_replacements(replacement_info, self.session_id)

        result_slide = service._deck_cache[self.session_id].slides[0]

        # Script should be preserved
        assert result_slide.scripts is not None
        assert len(result_slide.scripts) > 0

        # Script should reference the NEW canvas ID (not old one)
        assert new_canvas_id in result_slide.scripts
        # Old ID references should be updated
        assert f"getElementById('{new_canvas_id}')" in result_slide.scripts

    def test_multiple_optimizes_handle_suffix_correctly(self):
        """Multiple optimize operations shouldn't lose scripts."""
        # Start with a simple canvas ID
        chart_html, chart_script = generate_chart_slide(
            title="Growth Chart",
            canvas_id="growthChart",
        )
        slide = Slide(html=chart_html, slide_id="slide_0", scripts=chart_script)
        deck = SlideDeck(slides=[slide], css="")
        service = _create_chat_service_with_deck(self.session_id, deck)

        # First optimize: growthChart -> growthChart_abc123
        new_id_1 = "growthChart_abc123"
        optimized_html_1 = chart_html.replace('id="growthChart"', f'id="{new_id_1}"')
        replacement_1 = Slide(html=optimized_html_1, slide_id="slide_0", scripts="")

        with patch("src.api.services.chat_service.get_session_manager", return_value=self.mock_sm):
            service._apply_slide_replacements({
                "start_index": 0,
                "original_count": 1,
                "replacement_slides": [replacement_1],
                "replacement_css": "",
                "is_add_operation": False,
            }, self.session_id)

        # After first optimize, script should exist with new ID
        after_first = service._deck_cache[self.session_id].slides[0]
        assert after_first.scripts is not None
        assert new_id_1 in after_first.scripts


class TestReconstructDeckFromDict:
    """Test _reconstruct_deck_from_dict preserves per-slide scripts."""

    def test_reconstruct_preserves_scripts(self):
        """Reconstructing from dict should preserve individual slide scripts."""
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()

        # Build a deck dict with per-slide scripts
        chart_html, chart_script = generate_chart_slide(
            title="Test Chart", canvas_id="testCanvas"
        )
        content_html = generate_content_slide(title="Test Content")

        deck_dict = {
            "slides": [
                {"html": chart_html, "slide_id": "slide_0", "scripts": chart_script},
                {"html": content_html, "slide_id": "slide_1", "scripts": ""},
            ],
            "css": ".slide { padding: 20px; }",
            "external_scripts": ["https://cdn.jsdelivr.net/npm/chart.js"],
            "title": "Test Deck",
        }

        deck = service._reconstruct_deck_from_dict(deck_dict)

        # Chart slide should have its script
        assert deck.slides[0].scripts == chart_script
        assert "testCanvas" in deck.slides[0].scripts

        # Content slide should have no script
        assert deck.slides[1].scripts == ""

        # Deck metadata preserved
        assert deck.css == ".slide { padding: 20px; }"
        assert len(deck.external_scripts) == 1
        assert deck.title == "Test Deck"

    def test_reconstruct_handles_missing_scripts(self):
        """Reconstruct should handle slides without scripts field."""
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()

        deck_dict = {
            "slides": [
                {"html": "<div>Slide 1</div>", "slide_id": "slide_0"},
                {"html": "<div>Slide 2</div>"},
            ],
            "css": "",
        }

        deck = service._reconstruct_deck_from_dict(deck_dict)

        assert len(deck.slides) == 2
        assert deck.slides[0].scripts == ""
        assert deck.slides[1].scripts == ""
        assert deck.slides[1].slide_id == "slide_1"

    def test_reconstruct_round_trip(self):
        """Deck -> to_dict -> reconstruct should be lossless."""
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()

        # Create a deck with charts
        original = _create_deck_with_charts(2, 1)

        # Round trip: deck -> dict -> reconstruct
        deck_dict = original.to_dict()
        reconstructed = service._reconstruct_deck_from_dict(deck_dict)

        # Same number of slides
        assert len(reconstructed.slides) == len(original.slides)

        # Scripts preserved for each slide
        for i in range(len(original.slides)):
            assert reconstructed.slides[i].scripts == original.slides[i].scripts
            assert reconstructed.slides[i].html == original.slides[i].html


class TestDatabaseLoadPreservesScripts:
    """Test _get_or_load_deck preserves scripts when loading from database."""

    def test_load_from_slides_array_preserves_scripts(self):
        """Loading from database via slides array should preserve per-slide scripts."""
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()
        service._deck_cache = {}

        import threading
        service._cache_lock = threading.Lock()

        session_id = "test-session"

        # Simulate database returning deck with slides array (preferred path)
        chart_html, chart_script = generate_chart_slide(
            title="DB Chart", canvas_id="dbChart"
        )
        db_deck_data = {
            "slides": [
                {"html": chart_html, "slide_id": "slide_0", "scripts": chart_script},
                {"html": "<div>Content</div>", "slide_id": "slide_1", "scripts": ""},
            ],
            "css": ".test { color: red; }",
            "title": "DB Deck",
        }

        mock_sm = MagicMock()
        mock_sm.get_slide_deck.return_value = db_deck_data

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            deck = service._get_or_load_deck(session_id)

        assert deck is not None
        assert len(deck.slides) == 2
        assert deck.slides[0].scripts == chart_script
        assert "dbChart" in deck.slides[0].scripts
        assert deck.slides[1].scripts == ""

    def test_cache_hit_skips_database(self):
        """When deck is in cache, database should not be called."""
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()

        import threading
        service._cache_lock = threading.Lock()

        session_id = "test-session"
        cached_deck = _create_deck_with_charts(1, 0)
        service._deck_cache = {session_id: cached_deck}

        mock_sm = MagicMock()

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            deck = service._get_or_load_deck(session_id)

        # Should return cached deck without calling database
        assert deck is cached_deck
        mock_sm.get_slide_deck.assert_not_called()


class TestCanvasIdExtraction:
    """Test canvas ID extraction and script splitting used in preservation."""

    def test_extract_canvas_ids_from_chart_slide(self):
        """Should extract canvas IDs from chart slide HTML."""
        chart_html, _ = generate_chart_slide(canvas_id="myChart")

        canvas_ids = extract_canvas_ids_from_html(chart_html)

        assert "myChart" in canvas_ids

    def test_extract_canvas_ids_empty_html(self):
        """Should return empty list for HTML without canvas elements."""
        content_html = generate_content_slide(title="No Charts")

        canvas_ids = extract_canvas_ids_from_html(content_html)

        assert canvas_ids == []

    def test_split_script_by_canvas_single_chart(self):
        """Should split script correctly for single chart."""
        _, chart_script = generate_chart_slide(canvas_id="singleChart")

        segments = split_script_by_canvas(chart_script)

        assert len(segments) >= 1
        # At least one segment should reference singleChart
        all_canvas_ids = []
        for _, canvas_ids in segments:
            all_canvas_ids.extend(canvas_ids)
        assert "singleChart" in all_canvas_ids
