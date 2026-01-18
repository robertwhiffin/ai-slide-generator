"""Comprehensive tests for slide editing robustness fixes.

Tests cover:
- RC1: LLM response validation and retry
- RC2: Add vs edit intent detection
- RC3: Deck preservation on failure
- RC4: Canvas ID deduplication
- RC5: JavaScript syntax validation
- RC6: Cache restoration from database
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from bs4 import BeautifulSoup

from src.domain.slide_deck import SlideDeck
from src.domain.slide import Slide
from src.utils.js_validator import (
    validate_javascript,
    try_fix_common_js_errors,
    validate_and_fix_javascript,
)


# =============================================================================
# RC3: Deck Preservation Tests
# =============================================================================


class TestDeckPreservation:
    """Tests for RC3: Deck should never be destroyed on editing failures."""

    @pytest.fixture
    def mock_deck(self):
        """Create a mock deck with 3 slides."""
        return SlideDeck(
            title="Test Deck",
            slides=[
                Slide(
                    html='<div class="slide"><h1>Slide 1</h1></div>', slide_id="slide_0"
                ),
                Slide(
                    html='<div class="slide"><h1>Slide 2</h1></div>', slide_id="slide_1"
                ),
                Slide(
                    html='<div class="slide"><h1>Slide 3</h1></div>', slide_id="slide_2"
                ),
            ],
        )

    def test_rc3_deck_structure_preserved(self, mock_deck):
        """RC3: Verify deck structure is maintained."""
        assert len(mock_deck.slides) == 3
        assert mock_deck.title == "Test Deck"
        assert "Slide 1" in mock_deck.slides[0].html

    def test_rc3_valid_replacement_updates_deck(self, mock_deck):
        """RC3-T4: Valid HTML edit updates deck correctly."""
        replacement_slide = Slide(
            html='<div class="slide"><h1>Updated Slide</h1></div>', slide_id="slide_0"
        )

        # Simulate replacement
        mock_deck.remove_slide(0)
        mock_deck.insert_slide(replacement_slide, 0)

        assert len(mock_deck.slides) == 3
        assert "Updated Slide" in mock_deck.slides[0].html

    def test_rc3_new_generation_creates_deck(self):
        """RC3-T5: New generation (no slides selected) creates new deck."""
        html_output = """
        <!DOCTYPE html>
        <html>
        <body>
        <div class="slide"><h1>New Slide</h1></div>
        </body>
        </html>
        """

        deck = SlideDeck.from_html_string(html_output)

        assert len(deck.slides) == 1
        assert "New Slide" in deck.slides[0].html


# =============================================================================
# RC1: LLM Response Validation Tests
# =============================================================================


class TestLLMResponseValidation:
    """Tests for RC1: Validate LLM response before processing."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked settings."""
        with patch("src.services.agent.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(
                    endpoint="test", temperature=0.7, max_tokens=1000, timeout=60
                ),
                genie=None,
                prompts={"system_prompt": "test", "slide_style": "test"},
                mlflow=MagicMock(experiment_name="/test"),
            )
            with patch("src.services.agent.get_databricks_client"):
                with patch("src.services.agent.mlflow"):
                    from src.services.agent import SlideGeneratorAgent

                    agent = SlideGeneratorAgent()
        return agent

    def test_rc1_t1_detects_delete_text(self, agent):
        """RC1-T1: Detect 'I understand you want to delete' text."""
        response = (
            "I understand you want to delete both slides. There are no slides remaining."
        )

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is False
        assert "conversational text" in error.lower()

    def test_rc1_t2_detects_cannot_modify(self, agent):
        """RC1-T2: Detect 'I cannot modify' text."""
        response = "I cannot modify these slides as requested."

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is False

    def test_rc1_t3_accepts_valid_html(self, agent):
        """RC1-T3: Accept valid HTML with slide divs."""
        response = '<div class="slide"><h1>Valid Slide</h1></div>'

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is True
        assert error == ""

    def test_rc1_t6_html_without_slide_divs(self, agent):
        """RC1-T6: HTML without slide divs triggers retry."""
        response = '<div class="container"><p>No slide here</p></div>'

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is False
        assert "No <div class='slide'>" in error

    def test_rc1_empty_response_invalid(self, agent):
        """Empty response should be invalid."""
        response = ""

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is False
        assert "Empty response" in error

    def test_rc1_whitespace_response_invalid(self, agent):
        """Whitespace-only response should be invalid."""
        response = "   \n\t  "

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is False

    def test_rc1_valid_with_multiple_slides(self, agent):
        """Multiple valid slide divs should pass."""
        response = """
        <div class="slide"><h1>Slide 1</h1></div>
        <div class="slide"><h1>Slide 2</h1></div>
        <div class="slide"><h1>Slide 3</h1></div>
        """

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is True

    def test_rc1_conversational_with_slides_is_valid(self, agent):
        """Conversational text WITH slide divs should be valid."""
        response = """
        I understand you want red colors.
        <div class="slide"><h1>Here's the updated slide</h1></div>
        """

        is_valid, error = agent._validate_editing_response(response)

        assert is_valid is True


# =============================================================================
# RC2: Add vs Edit Intent Detection Tests
# =============================================================================


class TestAddIntentDetection:
    """Tests for RC2: Detect add slide vs edit slide intent."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked settings."""
        with patch("src.services.agent.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(
                    endpoint="test", temperature=0.7, max_tokens=1000, timeout=60
                ),
                genie=None,
                prompts={"system_prompt": "test", "slide_style": "test"},
                mlflow=MagicMock(experiment_name="/test"),
            )
            with patch("src.services.agent.get_databricks_client"):
                with patch("src.services.agent.mlflow"):
                    from src.services.agent import SlideGeneratorAgent

                    agent = SlideGeneratorAgent()
        return agent

    def test_rc2_t1_add_at_bottom_detected(self, agent):
        """RC2-T1: 'add a slide at the bottom for summary' → add intent."""
        message = "add a slide at the bottom for summary"

        is_add = agent._detect_add_intent(message)

        assert is_add is True

    def test_rc2_t2_insert_new_slide_detected(self, agent):
        """RC2-T2: 'insert a new slide after this one' → add intent."""
        message = "insert a new slide after this one"

        is_add = agent._detect_add_intent(message)

        assert is_add is True

    def test_rc2_t3_change_color_is_edit(self, agent):
        """RC2-T3: 'change the color to red' → NOT add intent."""
        message = "change the color to red"

        is_add = agent._detect_add_intent(message)

        assert is_add is False

    def test_rc2_t4_make_blue_is_edit(self, agent):
        """RC2-T4: 'make this slide blue' → NOT add intent."""
        message = "make this slide blue"

        is_add = agent._detect_add_intent(message)

        assert is_add is False

    def test_rc2_t5_create_new_summary(self, agent):
        """RC2-T5: 'create a new summary slide' → add intent."""
        message = "create a new summary slide"

        is_add = agent._detect_add_intent(message)

        assert is_add is True

    def test_rc2_t6_append_slide(self, agent):
        """RC2-T6: 'append a slide' → add intent."""
        message = "append a conclusions slide"

        is_add = agent._detect_add_intent(message)

        assert is_add is True

    def test_rc2_t7_add_at_end(self, agent):
        """RC2-T7: 'add at the end' → add intent."""
        message = "add a chart at the end"

        is_add = agent._detect_add_intent(message)

        assert is_add is True

    def test_rc2_add_summary(self, agent):
        """Add summary should be detected as add intent."""
        message = "add a summary slide"

        is_add = agent._detect_add_intent(message)

        assert is_add is True

    def test_rc2_add_key_takeaway(self, agent):
        """Add key takeaway should be detected as add intent."""
        message = "add a key takeaway slide at the end"

        is_add = agent._detect_add_intent(message)

        assert is_add is True

    def test_rc2_update_existing_is_not_add(self, agent):
        """Update existing slide should not be add intent."""
        message = "update the chart colors"

        is_add = agent._detect_add_intent(message)

        assert is_add is False


# =============================================================================
# RC4: Canvas ID Deduplication Tests
# =============================================================================


class TestCanvasIdDeduplication:
    """Tests for RC4: Generate unique canvas IDs to prevent collisions."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked settings."""
        with patch("src.services.agent.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(
                    endpoint="test", temperature=0.7, max_tokens=1000, timeout=60
                ),
                genie=None,
                prompts={"system_prompt": "test", "slide_style": "test"},
                mlflow=MagicMock(experiment_name="/test"),
            )
            with patch("src.services.agent.get_databricks_client"):
                with patch("src.services.agent.mlflow"):
                    from src.services.agent import SlideGeneratorAgent

                    agent = SlideGeneratorAgent()
        return agent

    def test_rc4_t1_single_canvas_deduplicated(self, agent):
        """RC4-T1: Single canvas ID gets unique suffix."""
        html = '<div class="slide"><canvas id="chart1"></canvas></div>'
        scripts = 'const ctx = document.getElementById("chart1");'

        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)

        # Original ID should not exist
        assert 'id="chart1"' not in new_html
        # New ID should have suffix
        assert 'id="chart1_' in new_html
        # Scripts should be updated (accept either single or double quotes)
        assert "getElementById" in new_scripts and "chart1_" in new_scripts

    def test_rc4_t2_multiple_canvases_same_suffix(self, agent):
        """RC4-T2: Multiple canvases in one slide get same suffix."""
        html = """<div class="slide">
            <canvas id="chart1"></canvas>
            <canvas id="chart2"></canvas>
        </div>"""
        scripts = """
            document.getElementById("chart1");
            document.getElementById("chart2");
        """

        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)

        soup = BeautifulSoup(new_html, "html.parser")
        canvas_ids = [c.get("id") for c in soup.find_all("canvas")]

        # Both should have same suffix
        suffix1 = canvas_ids[0].split("_")[1]
        suffix2 = canvas_ids[1].split("_")[1]
        assert suffix1 == suffix2

    def test_rc4_t3_scripts_references_updated(self, agent):
        """RC4-T3: All script references to canvas IDs are updated."""
        html = '<canvas id="myChart"></canvas>'
        scripts = """
            // Canvas: myChart
            const canvas = document.getElementById("myChart");
            const ctx = canvas.getContext("2d");
        """

        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)

        assert 'getElementById("myChart")' not in new_scripts
        assert (
            "// Canvas: myChart_" in new_scripts
            or 'getElementById("myChart_' in new_scripts
        )

    def test_rc4_t4_no_canvas_unchanged(self, agent):
        """RC4-T4: Slide without canvas is unchanged."""
        html = '<div class="slide"><h1>No chart here</h1></div>'
        scripts = 'console.log("no canvas");'

        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)

        assert new_html == html
        assert new_scripts == scripts

    def test_rc4_t5_consecutive_edits_unique_suffixes(self, agent):
        """RC4-T5: Two consecutive edits get different suffixes."""
        html = '<canvas id="chart"></canvas>'
        scripts = 'document.getElementById("chart");'

        _, scripts1 = agent._deduplicate_canvas_ids(html, scripts)
        _, scripts2 = agent._deduplicate_canvas_ids(html, scripts)

        # Extract suffixes (they should be different)
        import re

        suffix1 = re.search(r"chart_(\w+)", scripts1).group(1)
        suffix2 = re.search(r"chart_(\w+)", scripts2).group(1)

        assert suffix1 != suffix2

    def test_rc4_querySelector_updated(self, agent):
        """RC4: querySelector references should also be updated."""
        html = '<canvas id="myChart"></canvas>'
        scripts = 'const canvas = document.querySelector("#myChart");'

        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)

        assert 'querySelector("#myChart")' not in new_scripts
        # Accept either single or double quotes in output
        assert "querySelector" in new_scripts and "myChart_" in new_scripts


# =============================================================================
# RC5: JavaScript Syntax Validation Tests
# =============================================================================


class TestJavaScriptValidation:
    """Tests for RC5: Validate and fix JavaScript syntax."""

    def test_rc5_t1_valid_js_passes(self):
        """RC5-T1: Valid JavaScript passes validation."""
        script = """
            const canvas = document.getElementById("chart");
            if (canvas) {
                const ctx = canvas.getContext("2d");
            }
        """

        is_valid, error = validate_javascript(script)

        assert is_valid is True
        assert error == ""

    def test_rc5_t2_missing_brace_fixed(self):
        """RC5-T2: Missing closing brace is fixed."""
        script = """
            if (true) {
                console.log("test");
        """  # Missing closing brace

        fixed = try_fix_common_js_errors(script)

        assert fixed.count("{") == fixed.count("}")

    def test_rc5_t3_missing_paren_fixed(self):
        """RC5-T3: Missing closing parenthesis is fixed."""
        script = 'console.log("test"'  # Missing closing paren

        fixed = try_fix_common_js_errors(script)

        assert fixed.count("(") == fixed.count(")")

    def test_rc5_t5_empty_script_valid(self):
        """RC5-T5: Empty script passes validation."""
        script = ""

        is_valid, error = validate_javascript(script)

        assert is_valid is True

    def test_rc5_whitespace_only_valid(self):
        """Whitespace-only script should be valid."""
        script = "   \n\t  "

        is_valid, error = validate_javascript(script)

        assert is_valid is True

    def test_rc5_validate_and_fix_returns_fixed(self):
        """validate_and_fix_javascript should return fixed script when fixable."""
        script = "if (true) { console.log('test');"  # Missing brace

        fixed_script, was_fixed, error = validate_and_fix_javascript(script)

        # If esprima is installed, it should be fixed
        # If esprima is not installed, validation is skipped and script is unchanged
        # Either way, the function should return without error
        try:
            import esprima  # noqa: F401

            assert fixed_script.count("{") == fixed_script.count("}")
        except ImportError:
            # esprima not installed, validation was skipped
            assert fixed_script == script
            assert was_fixed is False

    def test_rc5_validate_and_fix_empty_script(self):
        """validate_and_fix_javascript should handle empty script."""
        script = ""

        fixed_script, was_fixed, error = validate_and_fix_javascript(script)

        assert fixed_script == ""
        assert was_fixed is False
        assert error == ""

    def test_rc5_missing_bracket_fixed(self):
        """Missing closing bracket should be fixed."""
        script = "const arr = [1, 2, 3"

        fixed = try_fix_common_js_errors(script)

        assert fixed.count("[") == fixed.count("]")


# =============================================================================
# Integration Tests
# =============================================================================


class TestSlideEditingIntegration:
    """Integration tests for the complete slide editing flow."""

    def test_deck_from_html_string(self):
        """Test creating deck from HTML string."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test</title></head>
        <body>
        <div class="slide"><h1>Slide 1</h1></div>
        <div class="slide"><h1>Slide 2</h1></div>
        </body>
        </html>
        """

        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) == 2
        assert deck.title == "Test"

    def test_deck_slide_manipulation(self):
        """Test adding, removing, and reordering slides."""
        deck = SlideDeck(
            title="Test",
            slides=[
                Slide(html='<div class="slide"><h1>1</h1></div>', slide_id="slide_0"),
                Slide(html='<div class="slide"><h1>2</h1></div>', slide_id="slide_1"),
            ],
        )

        # Add slide
        new_slide = Slide(
            html='<div class="slide"><h1>3</h1></div>', slide_id="slide_2"
        )
        deck.append_slide(new_slide)
        assert len(deck.slides) == 3

        # Remove slide
        deck.remove_slide(1)
        assert len(deck.slides) == 2

        # Verify remaining slides
        assert "<h1>1</h1>" in deck.slides[0].html
        assert "<h1>3</h1>" in deck.slides[1].html

    def test_slide_with_scripts(self):
        """Test slide with associated JavaScript."""
        slide = Slide(
            html='<div class="slide"><canvas id="chart1"></canvas></div>',
            slide_id="slide_0",
            scripts='new Chart(document.getElementById("chart1"), {});',
        )

        assert "chart1" in slide.html
        assert "Chart" in slide.scripts

    def test_deck_knit_includes_scripts(self):
        """Test that knit() includes all slide scripts."""
        slide = Slide(
            html='<div class="slide"><canvas id="chart1"></canvas></div>',
            slide_id="slide_0",
            scripts='console.log("test");',
        )
        deck = SlideDeck(title="Test", slides=[slide])

        knitted = deck.knit()

        assert 'console.log("test");' in knitted
        assert "<script>" in knitted

    def test_format_slide_context_add_operation(self):
        """Test _format_slide_context with add operation flag."""
        with patch("src.services.agent.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(
                    endpoint="test", temperature=0.7, max_tokens=1000, timeout=60
                ),
                genie=None,
                prompts={"system_prompt": "test", "slide_style": "test"},
                mlflow=MagicMock(experiment_name="/test"),
            )
            with patch("src.services.agent.get_databricks_client"):
                with patch("src.services.agent.mlflow"):
                    from src.services.agent import SlideGeneratorAgent

                    agent = SlideGeneratorAgent()

        slide_context = {
            "indices": [0],
            "slide_htmls": ['<div class="slide"><h1>Existing</h1></div>'],
        }

        # Without add operation
        context = agent._format_slide_context(slide_context, is_add_operation=False)
        assert "IMPORTANT: The user wants to ADD" not in context

        # With add operation
        context_add = agent._format_slide_context(slide_context, is_add_operation=True)
        assert "IMPORTANT: The user wants to ADD" in context_add
        assert "Return ONLY the new slide" in context_add


# =============================================================================
# Edge Case Tests
# =============================================================================


# =============================================================================
# RC6: Cache Restoration Tests
# =============================================================================


class TestCacheRestoration:
    """Tests for RC6: Deck should be restored from database if cache is empty."""

    def test_rc6_get_or_load_deck_from_cache(self):
        """Test that _get_or_load_deck returns cached deck when available."""
        from src.api.services.chat_service import ChatService
        from unittest.mock import patch, MagicMock
        import threading

        with patch("src.api.services.chat_service.create_agent"):
            service = ChatService.__new__(ChatService)
            service._deck_cache = {}
            service._cache_lock = threading.RLock()

            # Add deck to cache
            mock_deck = SlideDeck(
                title="Cached Deck",
                slides=[Slide(html='<div class="slide">Test</div>', slide_id="slide_0")],
            )
            service._deck_cache["session-123"] = mock_deck

            # Should return cached deck
            result = service._get_or_load_deck("session-123")
            assert result is mock_deck

    def test_rc6_get_or_load_deck_from_database(self):
        """Test that _get_or_load_deck loads from database when cache is empty."""
        from src.api.services.chat_service import ChatService
        from unittest.mock import patch, MagicMock
        import threading

        with patch("src.api.services.chat_service.create_agent"):
            with patch("src.api.services.chat_service.get_session_manager") as mock_get_sm:
                service = ChatService.__new__(ChatService)
                service._deck_cache = {}
                service._cache_lock = threading.RLock()

                # Mock database returning deck data
                mock_sm = MagicMock()
                mock_sm.get_slide_deck.return_value = {
                    "html_content": '<!DOCTYPE html><html><body><div class="slide"><h1>DB Deck</h1></div></body></html>'
                }
                mock_get_sm.return_value = mock_sm

                # Should load from database
                result = service._get_or_load_deck("session-456")
                assert result is not None
                assert len(result.slides) == 1
                assert "DB Deck" in result.slides[0].html

                # Should also cache it
                assert "session-456" in service._deck_cache

    def test_rc6_get_or_load_deck_empty_database(self):
        """Test that _get_or_load_deck returns None when nothing in cache or database."""
        from src.api.services.chat_service import ChatService
        from unittest.mock import patch, MagicMock
        import threading

        with patch("src.api.services.chat_service.create_agent"):
            with patch("src.api.services.chat_service.get_session_manager") as mock_get_sm:
                service = ChatService.__new__(ChatService)
                service._deck_cache = {}
                service._cache_lock = threading.RLock()

                # Mock database returning nothing
                mock_sm = MagicMock()
                mock_sm.get_slide_deck.return_value = None
                mock_get_sm.return_value = mock_sm

                # Should return None gracefully
                result = service._get_or_load_deck("session-789")
                assert result is None


class TestEdgeCases:
    """Edge case tests for robustness."""

    def test_slide_with_special_characters(self):
        """Test slides with special characters in content."""
        html = '<div class="slide"><h1>Revenue > $1M & Growth < 50%</h1></div>'
        slide = Slide(html=html, slide_id="slide_0")

        assert "&" in slide.html or "&amp;" in slide.html
        assert "Revenue" in slide.html

    def test_slide_with_unicode(self):
        """Test slides with unicode characters."""
        html = '<div class="slide"><h1>销售额 📈 Umsatz</h1></div>'
        slide = Slide(html=html, slide_id="slide_0")

        assert "销售额" in slide.html
        assert "📈" in slide.html

    def test_empty_slide_deck(self):
        """Test behavior with empty slide deck."""
        deck = SlideDeck(title="Empty", slides=[])

        assert len(deck.slides) == 0
        assert deck.knit()  # Should still produce valid HTML

    def test_slide_clone(self):
        """Test slide cloning preserves scripts."""
        original = Slide(
            html='<div class="slide"><h1>Test</h1></div>',
            slide_id="slide_0",
            scripts="console.log('test');",
        )

        cloned = original.clone()

        assert cloned.html == original.html
        assert cloned.scripts == original.scripts
        assert cloned.slide_id == original.slide_id

    def test_deeply_nested_html(self):
        """Test parsing deeply nested HTML structure."""
        html = """
        <div class="slide">
            <div class="container">
                <div class="row">
                    <div class="col">
                        <div class="card">
                            <h1>Deep content</h1>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
        slide = Slide(html=html, slide_id="slide_0")

        assert "Deep content" in slide.html
