"""Comprehensive tests for verification persistence with content hash method.

Tests cover:
1. HTML normalization and hashing
2. Verification storage and retrieval
3. Persistence across deck regeneration
4. Edit/add/delete scenarios
5. Session restore behavior

Run with: pytest tests/test_verification_persistence.py -v
"""
import hashlib
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


# =============================================================================
# UNIT TESTS: HTML Normalization and Hashing
# =============================================================================

class TestNormalizeHtml:
    """Tests for HTML normalization function."""

    def test_normalize_strips_whitespace(self):
        """Whitespace at start/end should be stripped."""
        from src.utils.slide_hash import normalize_html
        
        html = "  <div>hello</div>  "
        result = normalize_html(html)
        
        assert result == "<div>hello</div>"

    def test_normalize_collapses_internal_whitespace(self):
        """Multiple internal spaces should collapse to single space."""
        from src.utils.slide_hash import normalize_html
        
        html = "<div>hello    world</div>"
        result = normalize_html(html)
        
        assert result == "<div>hello world</div>"

    def test_normalize_handles_newlines(self):
        """Newlines and tabs should be treated as whitespace."""
        from src.utils.slide_hash import normalize_html
        
        html = "<div>\n\thello\n\tworld\n</div>"
        result = normalize_html(html)
        
        assert result == "<div> hello world </div>"

    def test_normalize_removes_comments(self):
        """HTML comments should be removed."""
        from src.utils.slide_hash import normalize_html
        
        html = "<div><!-- comment -->text</div>"
        result = normalize_html(html)
        
        assert result == "<div>text</div>"

    def test_normalize_removes_multiline_comments(self):
        """Multiline HTML comments should be removed."""
        from src.utils.slide_hash import normalize_html
        
        html = "<div><!-- \nmultiline\ncomment\n -->text</div>"
        result = normalize_html(html)
        
        assert result == "<div>text</div>"

    def test_normalize_lowercase(self):
        """HTML should be lowercased for consistency."""
        from src.utils.slide_hash import normalize_html
        
        html = "<DIV Class='MyClass'>TEXT</DIV>"
        result = normalize_html(html)
        
        assert result == "<div class='myclass'>text</div>"

    def test_normalize_preserves_meaningful_content(self):
        """Meaningful content should be preserved."""
        from src.utils.slide_hash import normalize_html
        
        html = '<div class="slide"><h1>Title</h1><p>Revenue: $1,000,000</p></div>'
        result = normalize_html(html)
        
        assert "title" in result
        assert "revenue" in result
        assert "$1,000,000" in result.lower()

    def test_normalize_empty_string(self):
        """Empty string should return empty string."""
        from src.utils.slide_hash import normalize_html
        
        result = normalize_html("")
        
        assert result == ""

    def test_normalize_whitespace_only(self):
        """Whitespace-only string should return empty string."""
        from src.utils.slide_hash import normalize_html
        
        result = normalize_html("   \n\t   ")
        
        assert result == ""


class TestComputeSlideHash:
    """Tests for slide hash computation."""

    def test_hash_is_deterministic(self):
        """Same input should always produce same hash."""
        from src.utils.slide_hash import compute_slide_hash
        
        html = "<div>test content</div>"
        
        hash1 = compute_slide_hash(html)
        hash2 = compute_slide_hash(html)
        
        assert hash1 == hash2

    def test_hash_different_for_different_content(self):
        """Different content should produce different hashes."""
        from src.utils.slide_hash import compute_slide_hash
        
        html1 = "<div>content A</div>"
        html2 = "<div>content B</div>"
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        
        assert hash1 != hash2

    def test_hash_whitespace_invariant(self):
        """Content with extra internal whitespace should normalize to same hash."""
        from src.utils.slide_hash import compute_slide_hash
        
        # These have different whitespace WITHIN the text content
        html1 = "<div>hello    world</div>"  # Multiple spaces between words
        html2 = "<div>hello world</div>"     # Single space between words
        html3 = "<div>hello\n\tworld</div>"  # Tab and newline between words
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        hash3 = compute_slide_hash(html3)
        
        # After normalization, all should have single space between words
        assert hash1 == hash2 == hash3
    
    def test_hash_leading_trailing_whitespace_invariant(self):
        """Leading/trailing whitespace in tags should not affect hash."""
        from src.utils.slide_hash import compute_slide_hash
        
        html1 = "  <div>hello</div>  "
        html2 = "<div>hello</div>"
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        
        assert hash1 == hash2

    def test_hash_comment_invariant(self):
        """Content with/without comments should match."""
        from src.utils.slide_hash import compute_slide_hash
        
        html1 = "<div>text</div>"
        html2 = "<div><!-- comment -->text</div>"
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        
        assert hash1 == hash2

    def test_hash_case_invariant(self):
        """Same content with different case should match."""
        from src.utils.slide_hash import compute_slide_hash
        
        html1 = "<div>Text</div>"
        html2 = "<DIV>TEXT</DIV>"
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        
        assert hash1 == hash2

    def test_hash_length(self):
        """Hash should be 16 characters (first 16 of SHA256 hex)."""
        from src.utils.slide_hash import compute_slide_hash
        
        html = "<div>any content</div>"
        
        hash_value = compute_slide_hash(html)
        
        assert len(hash_value) == 16
        assert all(c in '0123456789abcdef' for c in hash_value)

    def test_hash_meaningful_change_detected(self):
        """Meaningful content changes should produce different hashes."""
        from src.utils.slide_hash import compute_slide_hash
        
        html1 = "<div>Revenue: $1,000,000</div>"
        html2 = "<div>Revenue: $2,000,000</div>"
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        
        assert hash1 != hash2


# =============================================================================
# INTEGRATION TESTS: Session Manager Verification Storage
# =============================================================================

class TestVerificationStorage:
    """Tests for verification map storage in session manager."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        with patch('src.api.services.session_manager.get_db_session') as mock:
            mock_session = MagicMock()
            mock.return_value.__enter__ = Mock(return_value=mock_session)
            mock.return_value.__exit__ = Mock(return_value=None)
            yield mock_session

    @pytest.fixture
    def sample_verification(self):
        """Sample verification result."""
        return {
            "score": 95,
            "rating": "excellent",
            "explanation": "All data accurately represents source.",
            "issues": [],
            "trace_id": "tr-abc123",
            "timestamp": "2024-12-16T10:00:00Z"
        }

    @pytest.fixture
    def sample_slide_html(self):
        """Sample slide HTML."""
        return '<div class="slide"><h1>Q4 Revenue</h1><p>$1,000,000</p></div>'

    def test_save_verification_creates_map(self, sample_verification, sample_slide_html):
        """Saving verification should create verification_map entry."""
        from src.utils.slide_hash import compute_slide_hash
        
        content_hash = compute_slide_hash(sample_slide_html)
        verification_map = {}
        
        # Simulate save
        verification_map[content_hash] = sample_verification
        
        assert content_hash in verification_map
        assert verification_map[content_hash]["score"] == 95

    def test_save_verification_updates_existing(self, sample_verification, sample_slide_html):
        """Saving new verification should update existing entry."""
        from src.utils.slide_hash import compute_slide_hash
        
        content_hash = compute_slide_hash(sample_slide_html)
        
        # Initial verification
        verification_map = {content_hash: {"score": 80, "rating": "good"}}
        
        # Update with new verification
        verification_map[content_hash] = sample_verification
        
        assert verification_map[content_hash]["score"] == 95
        assert verification_map[content_hash]["rating"] == "excellent"

    def test_load_slides_merges_verification(self, sample_verification, sample_slide_html):
        """Loading slides should merge verification from map."""
        from src.utils.slide_hash import compute_slide_hash
        
        content_hash = compute_slide_hash(sample_slide_html)
        
        # Simulated stored data
        deck_json = {
            "slides": [{"html": sample_slide_html, "slide_id": "slide_0"}]
        }
        verification_map = {content_hash: sample_verification}
        
        # Merge logic (what get_slide_deck should do)
        for slide in deck_json["slides"]:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
            slide["content_hash"] = slide_hash
        
        assert deck_json["slides"][0]["verification"] is not None
        assert deck_json["slides"][0]["verification"]["score"] == 95
        assert deck_json["slides"][0]["content_hash"] == content_hash

    def test_load_slides_no_verification_if_no_match(self, sample_slide_html):
        """Slides without matching hash should have no verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Different content, different hash
        old_hash = "abcd1234abcd1234"
        verification_map = {old_hash: {"score": 90}}
        
        deck_json = {
            "slides": [{"html": sample_slide_html, "slide_id": "slide_0"}]
        }
        
        # Merge logic
        for slide in deck_json["slides"]:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        assert deck_json["slides"][0]["verification"] is None


# =============================================================================
# SCENARIO TESTS: Real-world Usage Patterns
# =============================================================================

class TestScenarioNewSlides:
    """Tests for generating new slides scenario."""

    def test_new_slides_have_no_verification(self):
        """Freshly generated slides should have no verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Empty verification map (new session)
        verification_map = {}
        
        # New slides from LLM
        slides = [
            {"html": "<div>Slide 1</div>", "slide_id": "slide_0"},
            {"html": "<div>Slide 2</div>", "slide_id": "slide_1"},
            {"html": "<div>Slide 3</div>", "slide_id": "slide_2"},
        ]
        
        # Merge verification
        for slide in slides:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
            slide["content_hash"] = slide_hash
        
        # All slides should need verification
        unverified = [s for s in slides if s["verification"] is None]
        assert len(unverified) == 3

    def test_after_verification_all_slides_have_results(self):
        """After auto-verify, all slides should have verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [
            {"html": "<div>Slide 1</div>", "slide_id": "slide_0"},
            {"html": "<div>Slide 2</div>", "slide_id": "slide_1"},
            {"html": "<div>Slide 3</div>", "slide_id": "slide_2"},
        ]
        
        # Build verification map (simulating auto-verify)
        verification_map = {}
        for i, slide in enumerate(slides):
            slide_hash = compute_slide_hash(slide["html"])
            verification_map[slide_hash] = {
                "score": 90 + i,
                "rating": "excellent",
                "explanation": f"Slide {i+1} verified"
            }
        
        # Re-merge verification
        for slide in slides:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        # All slides should have verification
        verified = [s for s in slides if s["verification"] is not None]
        assert len(verified) == 3


class TestScenarioEditSlide:
    """Tests for editing a single slide scenario."""

    def test_edited_slide_loses_verification(self):
        """Edited slide should lose its verification (hash changes)."""
        from src.utils.slide_hash import compute_slide_hash
        
        original_html = "<div>Revenue: $1,000,000</div>"
        edited_html = "<div>Revenue: $2,000,000</div>"
        
        original_hash = compute_slide_hash(original_html)
        edited_hash = compute_slide_hash(edited_html)
        
        # Verification for original
        verification_map = {
            original_hash: {"score": 95, "rating": "excellent"}
        }
        
        # After edit, slide has new hash
        verification = verification_map.get(edited_hash)
        
        assert original_hash != edited_hash
        assert verification is None

    def test_unedited_slides_keep_verification(self):
        """Slides not edited should keep their verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Original slides
        slide1_html = "<div>Slide 1 - unchanged</div>"
        slide2_html = "<div>Slide 2 - will edit</div>"
        slide3_html = "<div>Slide 3 - unchanged</div>"
        
        # Build verification map
        verification_map = {
            compute_slide_hash(slide1_html): {"score": 90},
            compute_slide_hash(slide2_html): {"score": 85},
            compute_slide_hash(slide3_html): {"score": 95},
        }
        
        # Edit slide 2
        slide2_edited = "<div>Slide 2 - EDITED content</div>"
        
        # New slides after edit
        new_slides = [
            {"html": slide1_html},
            {"html": slide2_edited},  # Changed
            {"html": slide3_html},
        ]
        
        # Merge verification
        for slide in new_slides:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        assert new_slides[0]["verification"] is not None  # Unchanged
        assert new_slides[1]["verification"] is None      # Edited - no match
        assert new_slides[2]["verification"] is not None  # Unchanged


class TestScenarioAddSlide:
    """Tests for adding slides via chat scenario."""

    def test_new_slide_has_no_verification(self):
        """Newly added slide should have no verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Existing slides with verification
        existing_slides = [
            {"html": "<div>Existing 1</div>"},
            {"html": "<div>Existing 2</div>"},
        ]
        
        verification_map = {
            compute_slide_hash(s["html"]): {"score": 90}
            for s in existing_slides
        }
        
        # New slide added at top
        new_slide = {"html": "<div>NEW Title Slide</div>"}
        
        # All slides after addition
        all_slides = [new_slide] + existing_slides
        
        # Merge verification
        for slide in all_slides:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        assert all_slides[0]["verification"] is None      # New slide
        assert all_slides[1]["verification"] is not None  # Existing
        assert all_slides[2]["verification"] is not None  # Existing

    def test_existing_slides_keep_verification_after_add(self):
        """Existing slides should keep verification when new slide added."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Original 3 slides
        slides = [
            {"html": "<div>Revenue Overview</div>"},
            {"html": "<div>Q1 Performance</div>"},
            {"html": "<div>Q2 Performance</div>"},
        ]
        
        # Verification for all
        verification_map = {}
        for i, slide in enumerate(slides):
            slide_hash = compute_slide_hash(slide["html"])
            verification_map[slide_hash] = {"score": 90 + i, "rating": "excellent"}
        
        # Add new slide at position 1
        new_slide = {"html": "<div>Executive Summary - NEW</div>"}
        slides_after = [slides[0], new_slide, slides[1], slides[2]]
        
        # Merge verification
        for slide in slides_after:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        # Original slides keep verification (regardless of new position)
        assert slides_after[0]["verification"] is not None  # Original slide 0
        assert slides_after[1]["verification"] is None      # New slide
        assert slides_after[2]["verification"] is not None  # Original slide 1
        assert slides_after[3]["verification"] is not None  # Original slide 2


class TestScenarioDeleteSlide:
    """Tests for deleting slides scenario."""

    def test_remaining_slides_keep_verification(self):
        """Remaining slides should keep verification after delete."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Original 3 slides with verification
        slides = [
            {"html": "<div>Slide A</div>"},
            {"html": "<div>Slide B - will delete</div>"},
            {"html": "<div>Slide C</div>"},
        ]
        
        verification_map = {}
        for i, slide in enumerate(slides):
            verification_map[compute_slide_hash(slide["html"])] = {"score": 90 + i}
        
        # Delete slide 1 (index 1)
        slides_after = [slides[0], slides[2]]
        
        # Merge verification
        for slide in slides_after:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        assert slides_after[0]["verification"] is not None
        assert slides_after[1]["verification"] is not None

    def test_orphan_verification_not_returned(self):
        """Deleted slide's verification should be ignored (orphan)."""
        from src.utils.slide_hash import compute_slide_hash
        
        deleted_html = "<div>Deleted slide</div>"
        remaining_html = "<div>Remaining slide</div>"
        
        # Verification map still has deleted slide's entry
        verification_map = {
            compute_slide_hash(deleted_html): {"score": 80},
            compute_slide_hash(remaining_html): {"score": 95},
        }
        
        # Only remaining slide exists
        slides = [{"html": remaining_html}]
        
        # Merge verification
        for slide in slides:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        # Only 1 slide with verification
        assert len([s for s in slides if s["verification"]]) == 1

    def test_delete_first_slide(self):
        """Deleting first slide should preserve verification of others."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [
            {"html": "<div>First - DELETE</div>"},
            {"html": "<div>Second</div>"},
            {"html": "<div>Third</div>"},
        ]
        
        verification_map = {
            compute_slide_hash(s["html"]): {"score": 90 + i}
            for i, s in enumerate(slides)
        }
        
        # Delete first slide
        slides_after = slides[1:]  # Keep second and third
        
        for slide in slides_after:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Both remaining slides have verification
        assert slides_after[0]["verification"]["score"] == 91  # Was second
        assert slides_after[1]["verification"]["score"] == 92  # Was third

    def test_delete_last_slide(self):
        """Deleting last slide should preserve verification of others."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [
            {"html": "<div>First</div>"},
            {"html": "<div>Second</div>"},
            {"html": "<div>Third - DELETE</div>"},
        ]
        
        verification_map = {
            compute_slide_hash(s["html"]): {"score": 90 + i}
            for i, s in enumerate(slides)
        }
        
        # Delete last slide
        slides_after = slides[:-1]  # Keep first and second
        
        for slide in slides_after:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        assert slides_after[0]["verification"]["score"] == 90
        assert slides_after[1]["verification"]["score"] == 91

    def test_delete_multiple_slides(self):
        """Deleting multiple slides should preserve verification of remaining."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [
            {"html": "<div>Slide 0 - KEEP</div>"},
            {"html": "<div>Slide 1 - DELETE</div>"},
            {"html": "<div>Slide 2 - DELETE</div>"},
            {"html": "<div>Slide 3 - KEEP</div>"},
            {"html": "<div>Slide 4 - DELETE</div>"},
        ]
        
        verification_map = {
            compute_slide_hash(s["html"]): {"score": i * 10}
            for i, s in enumerate(slides)
        }
        
        # Keep only slides 0 and 3
        slides_after = [slides[0], slides[3]]
        
        for slide in slides_after:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        assert len(slides_after) == 2
        assert slides_after[0]["verification"]["score"] == 0
        assert slides_after[1]["verification"]["score"] == 30

    def test_delete_all_slides(self):
        """Deleting all slides should result in empty deck (no crash)."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [{"html": "<div>Only slide</div>"}]
        verification_map = {
            compute_slide_hash(slides[0]["html"]): {"score": 95}
        }
        
        # Delete all slides
        slides_after = []
        
        # Merge verification (on empty list)
        for slide in slides_after:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        assert len(slides_after) == 0
        # verification_map still has entry but it's orphaned

    def test_delete_then_restore_same_content(self):
        """Re-adding slide with same content should restore verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        original_html = "<div>Important slide</div>"
        
        # Original verification
        verification_map = {
            compute_slide_hash(original_html): {"score": 95, "rating": "excellent"}
        }
        
        # Slide is deleted (deck is now empty, but verification_map preserved)
        slides_after_delete = []
        
        # Later, user adds back same content (or LLM regenerates it)
        slides_after_restore = [{"html": original_html}]
        
        for slide in slides_after_restore:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Verification should be restored!
        assert slides_after_restore[0]["verification"] is not None
        assert slides_after_restore[0]["verification"]["score"] == 95

    def test_delete_verified_slide_unverified_remains(self):
        """Deleting a verified slide should not affect unverified slides."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [
            {"html": "<div>Verified slide</div>"},
            {"html": "<div>Unverified slide</div>"},
        ]
        
        # Only first slide is verified
        verification_map = {
            compute_slide_hash(slides[0]["html"]): {"score": 90}
        }
        
        # Delete the verified slide
        slides_after = [slides[1]]
        
        for slide in slides_after:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Unverified slide should still be unverified
        assert slides_after[0]["verification"] is None

    def test_delete_unverified_slide_verified_remains(self):
        """Deleting an unverified slide should not affect verified slides."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [
            {"html": "<div>Verified slide</div>"},
            {"html": "<div>Unverified slide - DELETE</div>"},
        ]
        
        # Only first slide is verified
        verification_map = {
            compute_slide_hash(slides[0]["html"]): {"score": 95}
        }
        
        # Delete the unverified slide
        slides_after = [slides[0]]
        
        for slide in slides_after:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Verified slide should still be verified
        assert slides_after[0]["verification"]["score"] == 95


class TestScenarioReorderSlides:
    """Tests for reordering slides scenario."""

    def test_reorder_preserves_verification(self):
        """Reordering slides should preserve all verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Original order
        slides = [
            {"html": "<div>First</div>"},
            {"html": "<div>Second</div>"},
            {"html": "<div>Third</div>"},
        ]
        
        # Build verification
        verification_map = {}
        for i, slide in enumerate(slides):
            verification_map[compute_slide_hash(slide["html"])] = {"score": 90 + i}
        
        # Reorder: Third, First, Second
        reordered = [slides[2], slides[0], slides[1]]
        
        # Merge verification
        for slide in reordered:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        # All should have verification (position doesn't matter)
        assert all(s["verification"] is not None for s in reordered)
        assert reordered[0]["verification"]["score"] == 92  # Was Third
        assert reordered[1]["verification"]["score"] == 90  # Was First
        assert reordered[2]["verification"]["score"] == 91  # Was Second


class TestScenarioSessionRestore:
    """Tests for restoring session scenario."""

    def test_restored_session_has_verification(self):
        """Restored session should have verification from saved map."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Simulated saved state
        saved_deck_json = {
            "slides": [
                {"html": "<div>Saved Slide 1</div>", "slide_id": "slide_0"},
                {"html": "<div>Saved Slide 2</div>", "slide_id": "slide_1"},
            ]
        }
        
        saved_verification_map = {
            compute_slide_hash("<div>Saved Slide 1</div>"): {
                "score": 95, "rating": "excellent"
            },
            compute_slide_hash("<div>Saved Slide 2</div>"): {
                "score": 88, "rating": "good"
            },
        }
        
        # Restore: merge verification
        for slide in saved_deck_json["slides"]:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = saved_verification_map.get(slide_hash)
        
        assert saved_deck_json["slides"][0]["verification"]["score"] == 95
        assert saved_deck_json["slides"][1]["verification"]["score"] == 88


class TestScenarioDeckRegeneration:
    """Tests for deck regeneration (the original bug scenario)."""

    def test_verification_survives_deck_regeneration(self):
        """Verification should survive when deck is regenerated from chat."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Original deck with verification
        slide_content = "<div>Important data: $1M revenue</div>"
        content_hash = compute_slide_hash(slide_content)
        
        verification_map = {
            content_hash: {"score": 95, "rating": "excellent"}
        }
        
        # Chat regenerates deck (overwrites deck_json)
        # But verification_map is SEPARATE and PRESERVED
        new_deck_json = {
            "slides": [
                {"html": slide_content, "slide_id": "slide_0"}  # Same content
            ]
        }
        # verification_map is NOT touched by deck regeneration
        
        # Load slides (merge verification)
        for slide in new_deck_json["slides"]:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        # Verification should be found
        assert new_deck_json["slides"][0]["verification"] is not None
        assert new_deck_json["slides"][0]["verification"]["score"] == 95

    def test_verification_lost_if_llm_changes_content(self):
        """If LLM changes content meaningfully, verification should be lost (correct behavior)."""
        from src.utils.slide_hash import compute_slide_hash
        
        original_content = "<div>Revenue: $1,000,000</div>"
        llm_changed_content = "<div>Revenue: $1,500,000</div>"  # LLM changed number
        
        verification_map = {
            compute_slide_hash(original_content): {"score": 95}
        }
        
        # LLM generates deck with changed content
        new_deck = {"slides": [{"html": llm_changed_content}]}
        
        # Merge verification
        for slide in new_deck["slides"]:
            slide_hash = compute_slide_hash(slide["html"])
            slide["verification"] = verification_map.get(slide_hash)
        
        # Verification NOT found (content changed meaningfully)
        # This is CORRECT behavior - the number changed, needs re-verification
        assert new_deck["slides"][0]["verification"] is None


# =============================================================================
# COMBINED WORKFLOW TESTS
# =============================================================================

class TestCombinedWorkflows:
    """Tests for complex multi-step workflows."""

    def test_generate_verify_add_delete_workflow(self):
        """Full workflow: Generate → Verify → Add → Delete → Check."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Step 1: Generate 3 slides
        slides = [
            {"html": "<div>Slide 1</div>"},
            {"html": "<div>Slide 2</div>"},
            {"html": "<div>Slide 3</div>"},
        ]
        verification_map = {}
        
        # Step 2: Verify all slides
        for slide in slides:
            hash_key = compute_slide_hash(slide["html"])
            verification_map[hash_key] = {"score": 90, "rating": "excellent"}
        
        # Step 3: Add new slide at beginning
        new_slide = {"html": "<div>NEW Title</div>"}
        slides = [new_slide] + slides
        
        # Step 4: Delete slide 2 (original slide 1)
        slides = [slides[0], slides[2], slides[3]]  # Keep 0, 2, 3
        
        # Merge verification
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Check results
        assert slides[0]["verification"] is None  # New slide, not verified
        assert slides[1]["verification"] is not None  # Original slide 2
        assert slides[2]["verification"] is not None  # Original slide 3

    def test_generate_verify_edit_delete_workflow(self):
        """Full workflow: Generate → Verify → Edit one → Delete another."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Step 1: Generate and verify 3 slides
        slides = [
            {"html": "<div>Slide A</div>"},
            {"html": "<div>Slide B</div>"},
            {"html": "<div>Slide C</div>"},
        ]
        verification_map = {}
        for slide in slides:
            verification_map[compute_slide_hash(slide["html"])] = {"score": 95}
        
        # Step 2: Edit slide B
        slides[1]["html"] = "<div>Slide B - EDITED</div>"
        
        # Step 3: Delete slide A
        slides = slides[1:]  # Now: [edited B, C]
        
        # Merge verification
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Check results
        assert slides[0]["verification"] is None  # Edited, hash changed
        assert slides[1]["verification"] is not None  # Original C, preserved

    def test_restore_session_delete_slide_workflow(self):
        """Workflow: Restore session with verification → Delete slide."""
        from src.utils.slide_hash import compute_slide_hash
        
        # Simulated restored state
        slides = [
            {"html": "<div>Restored 1</div>"},
            {"html": "<div>Restored 2</div>"},
            {"html": "<div>Restored 3</div>"},
        ]
        verification_map = {
            compute_slide_hash(s["html"]): {"score": 80 + i * 5}
            for i, s in enumerate(slides)
        }
        
        # User deletes middle slide
        slides = [slides[0], slides[2]]
        
        # Merge verification
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        assert slides[0]["verification"]["score"] == 80
        assert slides[1]["verification"]["score"] == 90

    def test_partial_verification_then_delete(self):
        """Some slides verified, some not, then delete verified one."""
        from src.utils.slide_hash import compute_slide_hash
        
        slides = [
            {"html": "<div>Verified A</div>"},
            {"html": "<div>Unverified B</div>"},
            {"html": "<div>Verified C</div>"},
        ]
        
        # Only A and C are verified
        verification_map = {
            compute_slide_hash(slides[0]["html"]): {"score": 95},
            compute_slide_hash(slides[2]["html"]): {"score": 85},
        }
        
        # Delete verified slide A
        slides = slides[1:]  # [B, C]
        
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        assert slides[0]["verification"] is None  # B was never verified
        assert slides[1]["verification"]["score"] == 85  # C still verified


class TestDuplicateSlides:
    """Tests for duplicate and identical content scenarios."""

    def test_duplicate_slides_share_verification(self):
        """Two slides with identical content should share verification."""
        from src.utils.slide_hash import compute_slide_hash
        
        # User duplicates a slide (identical content)
        slides = [
            {"html": "<div>Original</div>"},
            {"html": "<div>Original</div>"},  # Duplicate
        ]
        
        # Verify the original
        verification_map = {
            compute_slide_hash("<div>Original</div>"): {"score": 95}
        }
        
        # Merge verification
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Both should have verification (same hash)
        assert slides[0]["verification"] is not None
        assert slides[1]["verification"] is not None
        assert slides[0]["verification"]["score"] == 95
        assert slides[1]["verification"]["score"] == 95

    def test_edit_one_duplicate_other_keeps_verification(self):
        """Editing one duplicate should not affect the other."""
        from src.utils.slide_hash import compute_slide_hash
        
        original_html = "<div>Original content</div>"
        
        # Two identical slides, both verified
        verification_map = {
            compute_slide_hash(original_html): {"score": 90}
        }
        
        # Edit one of them
        slides = [
            {"html": original_html},  # Unchanged
            {"html": "<div>EDITED content</div>"},  # Changed
        ]
        
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        assert slides[0]["verification"] is not None  # Original, still verified
        assert slides[1]["verification"] is None  # Edited, needs re-verification

    def test_delete_one_duplicate_other_keeps_verification(self):
        """Deleting one duplicate should preserve verification for the other."""
        from src.utils.slide_hash import compute_slide_hash
        
        html = "<div>Duplicate content</div>"
        
        slides = [
            {"html": html},
            {"html": html},  # Duplicate
            {"html": html},  # Another duplicate
        ]
        
        verification_map = {
            compute_slide_hash(html): {"score": 92}
        }
        
        # Delete middle one
        slides = [slides[0], slides[2]]
        
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Both remaining still have verification
        assert slides[0]["verification"]["score"] == 92
        assert slides[1]["verification"]["score"] == 92


class TestStaleVerificationMap:
    """Tests for handling stale/orphaned entries in verification_map."""

    def test_stale_entries_ignored(self):
        """Old entries for deleted slides should be ignored."""
        from src.utils.slide_hash import compute_slide_hash
        
        # verification_map has many old entries
        verification_map = {
            "old_hash_1": {"score": 80},
            "old_hash_2": {"score": 85},
            "old_hash_3": {"score": 90},
            compute_slide_hash("<div>Current</div>"): {"score": 95},
        }
        
        # Only one current slide
        slides = [{"html": "<div>Current</div>"}]
        
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Only current slide gets verification, old entries ignored
        assert slides[0]["verification"]["score"] == 95

    def test_verification_map_accumulates_over_time(self):
        """verification_map should accumulate entries without cleanup."""
        from src.utils.slide_hash import compute_slide_hash
        
        verification_map = {}
        
        # Session 1: Verify slide A
        slide_a = "<div>Slide A</div>"
        verification_map[compute_slide_hash(slide_a)] = {"score": 90}
        
        # Session 2: Replace with slide B, verify it
        slide_b = "<div>Slide B</div>"
        verification_map[compute_slide_hash(slide_b)] = {"score": 85}
        
        # Session 3: Go back to slide A
        slides = [{"html": slide_a}]
        
        for slide in slides:
            slide["verification"] = verification_map.get(compute_slide_hash(slide["html"]))
        
        # Slide A's old verification is still there!
        assert slides[0]["verification"]["score"] == 90


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_verification_map(self):
        """Empty verification map should return None for all slides."""
        from src.utils.slide_hash import compute_slide_hash
        
        verification_map = {}
        slides = [{"html": "<div>Any content</div>"}]
        
        for slide in slides:
            slide["verification"] = verification_map.get(
                compute_slide_hash(slide["html"])
            )
        
        assert slides[0]["verification"] is None

    def test_null_verification_map(self):
        """None verification_map should be treated as empty dict."""
        verification_map = None
        
        # Should not raise error
        result = (verification_map or {}).get("any_hash")
        
        assert result is None

    def test_empty_html(self):
        """Empty HTML should produce valid hash."""
        from src.utils.slide_hash import compute_slide_hash
        
        hash_value = compute_slide_hash("")
        
        assert hash_value is not None
        assert len(hash_value) == 16

    def test_unicode_content(self):
        """Unicode content should hash correctly."""
        from src.utils.slide_hash import compute_slide_hash
        
        html1 = "<div>日本語テスト</div>"
        html2 = "<div>日本語テスト</div>"
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        
        assert hash1 == hash2

    def test_special_characters(self):
        """Special characters should hash correctly."""
        from src.utils.slide_hash import compute_slide_hash
        
        html = '<div>Revenue: $1,000,000 (±5%) & growth</div>'
        
        hash_value = compute_slide_hash(html)
        
        assert hash_value is not None
        assert len(hash_value) == 16

    def test_very_long_html(self):
        """Very long HTML should hash correctly."""
        from src.utils.slide_hash import compute_slide_hash
        
        html = "<div>" + "x" * 100000 + "</div>"
        
        hash_value = compute_slide_hash(html)
        
        assert hash_value is not None
        assert len(hash_value) == 16

    def test_script_tags_preserved(self):
        """Script tag content should be preserved (affects chart data)."""
        from src.utils.slide_hash import compute_slide_hash
        
        html1 = '<div><script>var data = [1,2,3];</script></div>'
        html2 = '<div><script>var data = [1,2,4];</script></div>'  # Different data
        
        hash1 = compute_slide_hash(html1)
        hash2 = compute_slide_hash(html2)
        
        # Different script content = different hash
        assert hash1 != hash2


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

