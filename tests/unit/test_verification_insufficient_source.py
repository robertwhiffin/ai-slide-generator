"""Tests for verification when tool source text has no substantive facts."""

from src.api.routes.verification import _source_data_insufficient_for_verification


def test_empty_or_whitespace_insufficient():
    assert _source_data_insufficient_for_verification("") is True
    assert _source_data_insufficient_for_verification("   ") is True


def test_no_images_found_only_insufficient():
    msg = "No images found matching your criteria."
    assert _source_data_insufficient_for_verification(msg) is True


def test_substantive_data_with_no_results_phrase_not_insufficient():
    """Real metrics alongside a no-match line should still run the judge."""
    blob = (
        "No images found for filter foo.\n"
        "Revenue Q1: 1000000 Q2: 1200000 Q3: 1150000"
    )
    assert _source_data_insufficient_for_verification(blob) is False


def test_long_blob_with_digits_not_short_circuited():
    s = "No rows\n" + ("x" * 9000) + "12345678"
    assert _source_data_insufficient_for_verification(s) is False
