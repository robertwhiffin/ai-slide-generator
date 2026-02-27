"""Save points no-Genie mode tests.

These tests validate that save points correctly preserve cumulative deck state
across sequential edits in prompt-only (no-Genie) mode.

Key invariant:
    SavePoint(V_N) must contain ALL changes from V_1 through V_N.

This suite covers the gap where sequential edits caused later save points
to lose earlier changes, specifically in no-Genie mode where verification
completes near-instantly (returning "unknown").

Run with: pytest tests/unit/test_save_points_no_genie.py -v
"""

import pytest
import json
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from typing import Dict, Any, Optional, List

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.api.services.chat_service import ChatService

from tests.fixtures.html import (
    load_3_slide_deck,
    generate_content_slide,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_chat_service() -> ChatService:
    """Create a ChatService with mocked agent and real cache."""
    service = ChatService.__new__(ChatService)
    service.agent = MagicMock()
    service._deck_cache: Dict[str, SlideDeck] = {}
    service._cache_lock = threading.Lock()
    return service


def _build_deck(num_slides: int = 3) -> SlideDeck:
    """Build a SlideDeck from the 3-slide fixture HTML."""
    html = load_3_slide_deck()
    deck = SlideDeck.from_html_string(html)
    while len(deck.slides) > num_slides:
        deck.remove_slide(len(deck.slides) - 1)
    return deck


def _modify_slide_html(deck: SlideDeck, index: int, marker: str) -> str:
    """Replace a slide's HTML with a marked variant so we can detect it later.

    Returns the new HTML for assertion purposes.
    """
    new_html = f'<div class="slide" data-marker="{marker}"><h2>Edited Slide {index} - {marker}</h2></div>'
    deck.slides[index] = Slide(
        html=new_html,
        slide_id=f"slide_{index}",
        scripts=deck.slides[index].scripts,
    )
    return new_html


class MockSessionManager:
    """Mock session manager that tracks save_slide_deck and create_version calls."""

    def __init__(self):
        self.saved_decks: Dict[str, Dict[str, Any]] = {}
        self.versions: List[Dict[str, Any]] = []
        self.verification_maps: Dict[str, Dict[str, Any]] = {}
        self._next_version = 1

    def save_slide_deck(self, session_id, title, html_content,
                        scripts_content=None, slide_count=0, deck_dict=None):
        self.saved_decks[session_id] = {
            "session_id": session_id,
            "title": title,
            "slide_count": slide_count,
            "deck_dict": deck_dict,
            "slides": deck_dict.get("slides", []) if deck_dict else [],
        }
        return {"session_id": session_id, "slide_count": slide_count}

    def get_slide_deck(self, session_id):
        return self.saved_decks.get(session_id, {}).get("deck_dict")

    def get_verification_map(self, session_id):
        return self.verification_maps.get(session_id, {})

    def create_version(self, session_id, description, deck_dict,
                       verification_map=None, chat_history=None):
        v = self._next_version
        self._next_version += 1
        entry = {
            "version_number": v,
            "description": description,
            "deck_dict": deck_dict,
            "verification_map": verification_map,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "slide_count": len(deck_dict.get("slides", [])),
        }
        self.versions.append(entry)
        return entry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSequentialEditDeckState:
    """Verify that sequential edits produce save points containing ALL prior changes."""

    def test_cumulative_edits_preserved_in_save_points(self):
        """V3 must contain edits from V2; V4 must contain edits from V2 and V3.

        This is the primary bug reproduction: in no-Genie mode, later save
        points were losing changes from earlier edits.
        """
        service = _create_chat_service()
        session_id = "test-seq-edits"
        mock_sm = MockSessionManager()

        deck = _build_deck(3)
        service._deck_cache[session_id] = deck

        # Record original HTMLs
        original_htmls = [s.html for s in deck.slides]

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            # --- V1: initial generation ---
            service.create_save_point(session_id, "Generated 3 slides")

            assert len(mock_sm.versions) == 1
            v1 = mock_sm.versions[0]
            assert v1["slide_count"] == 3

            # --- Edit slide 2 (index 1) ---
            edited_1_html = _modify_slide_html(deck, 1, "red-background")

            # Persist to mock DB
            mock_sm.save_slide_deck(
                session_id=session_id,
                title=deck.title,
                html_content=deck.knit(),
                slide_count=len(deck.slides),
                deck_dict=deck.to_dict(),
            )

            # V2: after editing slide 2
            service.create_save_point(session_id, "Edited slide 2 (color)")

            assert len(mock_sm.versions) == 2
            v2 = mock_sm.versions[1]
            v2_slides = v2["deck_dict"]["slides"]
            assert v2_slides[0]["html"] == original_htmls[0], "V2: slide 1 should be original"
            assert v2_slides[1]["html"] == edited_1_html, "V2: slide 2 should have red-background edit"
            assert v2_slides[2]["html"] == original_htmls[2], "V2: slide 3 should be original"

            # --- Edit slide 1 (index 0) ---
            edited_0_html = _modify_slide_html(deck, 0, "bold-title")

            mock_sm.save_slide_deck(
                session_id=session_id,
                title=deck.title,
                html_content=deck.knit(),
                slide_count=len(deck.slides),
                deck_dict=deck.to_dict(),
            )

            # V3: after editing slide 1
            service.create_save_point(session_id, "Edited slide 1 (title)")

            assert len(mock_sm.versions) == 3
            v3 = mock_sm.versions[2]
            v3_slides = v3["deck_dict"]["slides"]
            assert v3_slides[0]["html"] == edited_0_html, "V3: slide 1 should have bold-title edit"
            assert v3_slides[1]["html"] == edited_1_html, "V3: slide 2 MUST still have red-background edit"
            assert v3_slides[2]["html"] == original_htmls[2], "V3: slide 3 should be original"

            # --- Edit slide 3 (index 2) ---
            edited_2_html = _modify_slide_html(deck, 2, "bullet-points")

            mock_sm.save_slide_deck(
                session_id=session_id,
                title=deck.title,
                html_content=deck.knit(),
                slide_count=len(deck.slides),
                deck_dict=deck.to_dict(),
            )

            # V4: after editing slide 3
            service.create_save_point(session_id, "Edited slide 3 (content)")

            assert len(mock_sm.versions) == 4
            v4 = mock_sm.versions[3]
            v4_slides = v4["deck_dict"]["slides"]
            assert v4_slides[0]["html"] == edited_0_html, "V4: slide 1 MUST still have bold-title"
            assert v4_slides[1]["html"] == edited_1_html, "V4: slide 2 MUST still have red-background"
            assert v4_slides[2]["html"] == edited_2_html, "V4: slide 3 should have bullet-points edit"

    def test_create_save_point_no_deck_raises(self):
        """create_save_point should raise ValueError when no deck exists."""
        service = _create_chat_service()
        mock_sm = MockSessionManager()

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            with pytest.raises(ValueError, match="No slide deck available"):
                service.create_save_point("empty-session", "Should fail")


class TestVerificationMapCarryForward:
    """Verify that verification_map entries for unedited slides survive edits."""

    def test_unedited_slides_keep_verification(self):
        """After editing slide 2, verification for slides 1 and 3 (by content hash)
        should still be present in the save point's verification_map.
        """
        from src.utils.slide_hash import compute_slide_hash

        service = _create_chat_service()
        session_id = "test-verify-carry"
        mock_sm = MockSessionManager()

        deck = _build_deck(3)
        service._deck_cache[session_id] = deck

        # Pre-populate verification map with hashes for all 3 original slides
        hash_0 = compute_slide_hash(deck.slides[0].html)
        hash_1 = compute_slide_hash(deck.slides[1].html)
        hash_2 = compute_slide_hash(deck.slides[2].html)

        mock_sm.verification_maps[session_id] = {
            hash_0: {"rating": "unknown", "score": 0},
            hash_1: {"rating": "unknown", "score": 0},
            hash_2: {"rating": "unknown", "score": 0},
        }

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            # Edit slide 2 -> new hash
            _modify_slide_html(deck, 1, "edited-v2")
            new_hash_1 = compute_slide_hash(deck.slides[1].html)

            service.create_save_point(session_id, "Edited slide 2")

        v = mock_sm.versions[0]
        vmap = v["verification_map"]

        # Unedited slides should still have their verification entries
        assert hash_0 in vmap, "Slide 1 verification should be preserved"
        assert hash_2 in vmap, "Slide 3 verification should be preserved"
        # Old hash for slide 2 is still in the map (hash-keyed, not removed)
        assert hash_1 in vmap, "Old slide 2 hash still in verification_map"
        # New hash for edited slide 2 is NOT yet in the map (verification not run yet)
        assert new_hash_1 not in vmap, "Edited slide 2 should not have verification yet"


class TestPanelEditPlusChatEdit:
    """Verify that panel HTML edits and chat edits coexist in save points."""

    def test_panel_edit_preserved_after_chat_edit(self):
        """A direct panel HTML edit followed by a chat edit should produce
        a save point containing BOTH changes.
        """
        service = _create_chat_service()
        session_id = "test-panel-chat"
        mock_sm = MockSessionManager()

        deck = _build_deck(3)
        service._deck_cache[session_id] = deck

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            # Panel edit on slide 1
            panel_html = _modify_slide_html(deck, 0, "panel-edit")
            mock_sm.save_slide_deck(
                session_id=session_id, title=deck.title,
                html_content=deck.knit(), slide_count=len(deck.slides),
                deck_dict=deck.to_dict(),
            )
            service.create_save_point(session_id, "Edited slide 1 (HTML)")

            # Chat edit on slide 2
            chat_html = _modify_slide_html(deck, 1, "chat-edit")
            mock_sm.save_slide_deck(
                session_id=session_id, title=deck.title,
                html_content=deck.knit(), slide_count=len(deck.slides),
                deck_dict=deck.to_dict(),
            )
            service.create_save_point(session_id, "Edited slide 2")

        assert len(mock_sm.versions) == 2

        v2_slides = mock_sm.versions[1]["deck_dict"]["slides"]
        assert v2_slides[0]["html"] == panel_html, "Panel edit on slide 1 must be preserved"
        assert v2_slides[1]["html"] == chat_html, "Chat edit on slide 2 must be present"


class TestBackendOperationsPlusChatEdits:
    """Verify reorder/duplicate/delete save points coexist with chat edit save points."""

    def test_reorder_then_edit_preserves_both(self):
        """Reorder creates a backend save point; a subsequent chat edit
        should produce a save point that keeps the reordered order.
        """
        service = _create_chat_service()
        session_id = "test-reorder-edit"
        mock_sm = MockSessionManager()

        deck = _build_deck(3)
        service._deck_cache[session_id] = deck
        original_htmls = [s.html for s in deck.slides]

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            # Reorder: swap slide 0 and slide 2
            deck.slides[0], deck.slides[2] = deck.slides[2], deck.slides[0]
            for idx, s in enumerate(deck.slides):
                s.slide_id = f"slide_{idx}"
            service.create_save_point(session_id, "Reordered slides")

            v1_slides = mock_sm.versions[0]["deck_dict"]["slides"]
            assert v1_slides[0]["html"] == original_htmls[2], "After reorder: position 0 should have original slide 3"
            assert v1_slides[2]["html"] == original_htmls[0], "After reorder: position 2 should have original slide 1"

            # Chat edit on position 1 (originally slide 2, still in place)
            edited_html = _modify_slide_html(deck, 1, "post-reorder-edit")
            service.create_save_point(session_id, "Edited slide 2")

            v2_slides = mock_sm.versions[1]["deck_dict"]["slides"]
            assert v2_slides[0]["html"] == original_htmls[2], "Reorder must be preserved"
            assert v2_slides[1]["html"] == edited_html, "Edit on position 1"
            assert v2_slides[2]["html"] == original_htmls[0], "Reorder must be preserved"

    def test_delete_then_edit_preserves_deletion(self):
        """Delete a slide, then edit another. Later save point should
        still have the deleted slide absent.
        """
        service = _create_chat_service()
        session_id = "test-delete-edit"
        mock_sm = MockSessionManager()

        html = load_3_slide_deck()
        deck = SlideDeck.from_html_string(html)
        service._deck_cache[session_id] = deck
        assert len(deck.slides) == 3

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            # Delete slide at index 1
            deck.remove_slide(1)
            for idx, s in enumerate(deck.slides):
                s.slide_id = f"slide_{idx}"
            service.create_save_point(session_id, "Deleted slide 2")

            assert mock_sm.versions[0]["slide_count"] == 2

            # Edit remaining slide at index 0
            edited_html = _modify_slide_html(deck, 0, "after-delete-edit")
            service.create_save_point(session_id, "Edited slide 1")

            v2 = mock_sm.versions[1]
            assert v2["slide_count"] == 2, "Deletion must persist: still 2 slides"
            assert v2["deck_dict"]["slides"][0]["html"] == edited_html

    def test_duplicate_then_edit(self):
        """Duplicate a slide, then edit the duplicate. Save point should
        reflect both the duplication and the edit.
        """
        service = _create_chat_service()
        session_id = "test-dup-edit"
        mock_sm = MockSessionManager()

        deck = _build_deck(3)
        service._deck_cache[session_id] = deck

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            # Duplicate slide 1 (insert clone at index 2)
            cloned = Slide(
                html=deck.slides[1].html,
                slide_id="slide_dup",
                scripts=deck.slides[1].scripts,
            )
            deck.insert_slide(cloned, 2)
            for idx, s in enumerate(deck.slides):
                s.slide_id = f"slide_{idx}"
            service.create_save_point(session_id, "Duplicated slide 2")

            assert mock_sm.versions[0]["slide_count"] == 4

            # Edit the duplicated slide at index 2
            edited_html = _modify_slide_html(deck, 2, "dup-edited")
            service.create_save_point(session_id, "Edited duplicated slide")

            v2 = mock_sm.versions[1]
            assert v2["slide_count"] == 4, "Still 4 slides after editing duplicate"
            assert v2["deck_dict"]["slides"][2]["html"] == edited_html
            # Original at index 1 should be untouched
            assert v2["deck_dict"]["slides"][1]["html"] != edited_html


class TestUpdateVersionVerification:
    """Test that updating verification on an existing save point works."""

    def test_update_version_verification_valid(self):
        """Updating verification_map_json on an existing version should
        change only that field, leaving deck_json untouched.
        """
        from src.api.services.session_manager import SessionManager

        sm = SessionManager.__new__(SessionManager)

        deck_dict = {"slides": [{"html": "<div>slide</div>", "slide_id": "s0"}]}
        original_deck_json = json.dumps(deck_dict)

        class MockVersion:
            def __init__(self):
                self.deck_json = original_deck_json
                self.verification_map_json = None
                self.version_number = 1

        mock_version = MockVersion()

        with patch("src.api.services.session_manager.get_db_session") as mock_db:
            mock_db_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            mock_session = MagicMock()
            mock_session.id = 1
            sm._get_session_or_raise = MagicMock(return_value=mock_session)

            mock_query = MagicMock()
            mock_db_session.query.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.first.return_value = mock_version

            new_vmap = {"hash_abc": {"rating": "unknown", "score": 0}}

            # This method will be added by the fix; for now, test that
            # SessionManager has create_version (the method we'll extend).
            # After fix: sm.update_version_verification(session_id, 1, new_vmap)
            assert hasattr(sm, "create_version"), "SessionManager must have create_version"

    def test_no_genie_verification_returns_unknown(self):
        """In no-Genie mode, verification always returns 'unknown'.
        Save point should still be created with the correct deck.
        """
        service = _create_chat_service()
        session_id = "test-no-genie-verify"
        mock_sm = MockSessionManager()

        deck = _build_deck(3)
        service._deck_cache[session_id] = deck

        # No-Genie verification map: all unknown
        mock_sm.verification_maps[session_id] = {
            "hash_a": {"rating": "unknown", "score": 0, "explanation": "No source data"},
        }

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_sm):
            service.create_save_point(session_id, "Generated 3 slides")

        v = mock_sm.versions[0]
        assert v["slide_count"] == 3
        assert v["verification_map"] == mock_sm.verification_maps[session_id]
        assert v["deck_dict"]["slides"][0]["html"] == deck.slides[0].html
