"""Unit tests for slide replacement parsing and validation."""

from pathlib import Path

import pytest

from src.api.schemas.requests import SlideContext
from src.api.services.chat_service import validate_canvas_scripts
from src.services.agent import AgentError, SlideGeneratorAgent



@pytest.fixture
def agent_stub() -> SlideGeneratorAgent:
    """Provide a SlideGeneratorAgent instance without running __init__."""
    return SlideGeneratorAgent.__new__(SlideGeneratorAgent)  # type: ignore[call-arg]


class TestSlideReplacementParsing:
    """Test slide replacement parsing logic."""

    @pytest.mark.parametrize(
        ("html_snippet", "original_indices", "expected_count"),
        [
            (
                '<div class="slide"><h1>A</h1></div><div class="slide"><h1>B</h1></div>',
                [1, 2],
                2,
            ),
            (
                '<div class="slide"><h1>A</h1></div><div class="slide"><h1>B</h1></div><div class="slide"><h1>C</h1></div>',
                [0, 1],
                3,
            ),
            (
                '<div class="slide"><h1>Summary</h1></div>',
                [2, 3, 4],
                1,
            ),
        ],
    )
    def test_parse_replacements_varied_counts(
        self,
        agent_stub: SlideGeneratorAgent,
        html_snippet: str,
        original_indices: list[int],
        expected_count: int,
    ) -> None:
        """Ensure parser handles 1:1, expansion, and condensation cases."""
        result = agent_stub._parse_slide_replacements(html_snippet, original_indices)

        assert result["original_indices"] == original_indices
        assert result["original_count"] == len(original_indices)
        assert result["replacement_count"] == expected_count
        assert len(result["replacement_slides"]) == expected_count
        assert result["success"] is True

    def test_parse_replacements_no_slides_error(
        self,
        agent_stub: SlideGeneratorAgent,
    ) -> None:
        """Ensure parser raises AgentError when no slides are returned."""
        with pytest.raises(AgentError, match="No slide divs"):
            agent_stub._parse_slide_replacements("<div>Not a slide</div>", [0])

    def test_parse_extracts_scripts_and_canvas_ids(
        self,
        agent_stub: SlideGeneratorAgent,
    ) -> None:
        """Parser should collect canvas ids and associated scripts."""

        for script_tag in ("<script data-slide-scripts>", "<script>"):
            html_response = f"""
            <div class="slide">
                <canvas id="chartA"></canvas>
            </div>
            {script_tag}
            const canvas = document.getElementById('chartA');
            if (canvas) {{
                const ctx = canvas.getContext('2d');
                new Chart(ctx, {{type: 'bar', data: {{ labels: [], datasets: [] }}}});
            }}
            </script>
            """

            result = agent_stub._parse_slide_replacements(html_response, [0])

            assert result["canvas_ids"] == ["chartA"]
            assert "chartA" in result["replacement_scripts"]
            assert "<script" not in result["replacement_scripts"]
            assert result["script_canvas_ids"] == ["chartA"]

    def test_validate_canvas_scripts_full_html_success(
        self,
        agent_stub: SlideGeneratorAgent,
    ) -> None:
        """Full deck validation passes when scripts exist."""
        html = """
        <html>
            <body>
                <canvas id="chart1"></canvas>
                <script>
                const c = document.getElementById('chart1');
                if (c) { const ctx = c.getContext('2d'); new Chart(ctx, {}); }
                </script>
            </body>
        </html>
        """
        agent_stub._validate_canvas_scripts_in_html(html)

    def test_validate_canvas_scripts_full_html_failure(
        self,
        agent_stub: SlideGeneratorAgent,
    ) -> None:
        """Full deck validation raises error when script missing."""
        html = "<canvas id='chartMissing'></canvas><script>console.log('noop');</script>"
        with pytest.raises(AgentError, match="canvas elements"):
            agent_stub._validate_canvas_scripts_in_html(html)


class TestSlideContextValidation:
    """Test slide context validation rules."""

    def test_contiguous_validation_passes(self) -> None:
        """Indices must be contiguous and lengths must match."""
        context = SlideContext(
            indices=[1, 2, 3],
            slide_htmls=[
                '<div class="slide">One</div>',
                '<div class="slide">Two</div>',
                '<div class="slide">Three</div>',
            ],
        )

        assert context.indices == [1, 2, 3]
        assert len(context.slide_htmls) == 3

    def test_non_contiguous_or_mismatched_lengths_fail(self) -> None:
        """Non-contiguous indices or mismatched HTML counts should error."""
        with pytest.raises(ValueError, match="contiguous"):
            SlideContext(
                indices=[1, 3],
                slide_htmls=[
                    '<div class="slide">One</div>',
                    '<div class="slide">Two</div>',
                ],
            )

        with pytest.raises(ValueError, match="match number of indices"):
            SlideContext(
                indices=[1, 2],
                slide_htmls=['<div class="slide">Only one</div>'],
            )


class TestCanvasScriptValidation:
    """Validate helper that enforces chart script parity."""

    def test_validation_passes_when_scripts_present(self) -> None:
        """No error when every canvas id has script coverage."""
        validate_canvas_scripts(
            canvas_ids=["chart1"],
            script_text="document.getElementById('chart1')",
            existing_scripts="",
        )

    def test_validation_fails_when_scripts_missing(self) -> None:
        """Raise ValueError when a canvas lacks initialization."""
        with pytest.raises(ValueError, match="Missing Chart.js initialization"):
            validate_canvas_scripts(
                canvas_ids=["chart2"],
                script_text="document.getElementById('chart1')",
                existing_scripts="",
            )

