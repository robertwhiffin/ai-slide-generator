"""Tests for HTML utility helpers."""

from src.utils.html_utils import extract_canvas_ids_from_script


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

