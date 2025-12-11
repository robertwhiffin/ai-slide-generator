"""Tests for HTML utility helpers."""

from src.utils.html_utils import extract_canvas_ids_from_script, split_script_by_canvas


def test_extract_canvas_ids_from_script_various_patterns():
    """Should capture ids from getElementById, querySelector, and Canvas comments."""
    script = """
    // Canvas: campaignsChart
    const campaignsCanvas = document . getElementById("campaignsChart");
    const territoryCanvas = document.querySelector('#territoryChart');
    const ignored = document.getElementById(templateId);
    """

    ids = extract_canvas_ids_from_script(script)

    assert ids == ["campaignsChart", "territoryChart"]


def test_extract_canvas_ids_from_script_no_matches():
    """Returns empty list when no recognizable canvas ids."""
    script = "const nothing = document.getElementById(dynamicId);"

    assert extract_canvas_ids_from_script(script) == []


def test_split_script_by_canvas_valid_scenarios():
    """Test splitting multi-canvas scripts into per-canvas segments."""
    # Multi-canvas script with Chart N: comments
    multi_chart_script = """
// Chart 1: Overall Trend
const canvas1 = document.getElementById('overallTrendChart');
if (canvas1) {
    const ctx1 = canvas1.getContext('2d');
    new Chart(ctx1, { type: 'line', data: {} });
}

// Chart 2: Growth Rate
const canvas2 = document.getElementById('growthChart');
if (canvas2) {
    const ctx2 = canvas2.getContext('2d');
    new Chart(ctx2, { type: 'bar', data: {} });
}

// Chart 3: Pie Chart
const canvas3 = document.getElementById('lobPieChart');
if (canvas3) {
    const ctx3 = canvas3.getContext('2d');
    new Chart(ctx3, { type: 'doughnut', data: {} });
}
"""
    segments = split_script_by_canvas(multi_chart_script)

    # Should split into 3 segments
    assert len(segments) == 3

    # Each segment should have exactly one canvas ID
    assert segments[0][1] == ["overallTrendChart"]
    assert segments[1][1] == ["growthChart"]
    assert segments[2][1] == ["lobPieChart"]

    # Each segment should contain only its canvas code
    assert "overallTrendChart" in segments[0][0]
    assert "growthChart" not in segments[0][0]

    assert "growthChart" in segments[1][0]
    assert "overallTrendChart" not in segments[1][0]

    # Single canvas script should not be split
    single_canvas_script = """
const canvas = document.getElementById('myChart');
if (canvas) { new Chart(canvas, {}); }
"""
    single_segments = split_script_by_canvas(single_canvas_script)
    assert len(single_segments) == 1
    assert single_segments[0][1] == ["myChart"]

    # Script with explicit Canvas: comments
    explicit_comment_script = """
// Canvas: chart1
const c1 = document.getElementById('chart1');
new Chart(c1, {});

// Canvas: chart2
const c2 = document.getElementById('chart2');
new Chart(c2, {});
"""
    explicit_segments = split_script_by_canvas(explicit_comment_script)
    assert len(explicit_segments) == 2
    assert explicit_segments[0][1] == ["chart1"]
    assert explicit_segments[1][1] == ["chart2"]


def test_split_script_by_canvas_edge_cases():
    """Test split_script_by_canvas edge cases and fallback behavior."""
    # Empty script
    assert split_script_by_canvas("") == []
    assert split_script_by_canvas("   ") == []
    assert split_script_by_canvas(None) == []

    # No canvas references - returns empty
    no_canvas = "console.log('hello');"
    segments = split_script_by_canvas(no_canvas)
    assert len(segments) == 1
    assert segments[0][1] == []

    # Script that can't be meaningfully split (same start position)
    # Falls back to single block with all canvas IDs
    unsplittable = """
const charts = ['chart1', 'chart2'].forEach(id => {
    const canvas = document.getElementById(id);
});
"""
    unsplit_segments = split_script_by_canvas(unsplittable)
    # Should fallback to single segment since we can't determine boundaries
    assert len(unsplit_segments) == 1

