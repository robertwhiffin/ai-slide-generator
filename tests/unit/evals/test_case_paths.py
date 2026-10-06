"""Tests for evals.harness.case path robustness (anchor to package, not cwd).

These tests verify that case.py functions work when run from any directory,
not just the repo root. The paths should be anchored to the package, not the
current working directory.
"""
import pytest

from evals.harness import case, judge


def test_case_paths_are_absolute():
    """Verify that the path constants are absolute."""
    assert case.EVALS_DIR.is_absolute()
    assert case.PACKS_DIR.is_absolute()
    assert case.MERIDIAN_DIR.is_absolute()


def test_packs_dir_same_in_both_modules():
    """Verify that judge.py reuses case.py's PACKS_DIR."""
    assert judge.PACKS_DIR == case.PACKS_DIR


def test_case_functions_work_from_different_directory(monkeypatch, tmp_path):
    """Verify that case functions work when run from a non-repo directory.

    This is the key test: change to a temporary directory that is NOT the repo
    root, then call case functions. If paths are correctly anchored, they should
    work. If paths are relative to cwd, this test will fail with FileNotFoundError.
    """
    # Change to a temporary directory that is definitely not the repo root
    monkeypatch.chdir(tmp_path)

    # These should all work despite being in a different directory
    slide_1_html = case.gold_slide(1)
    assert slide_1_html, "gold_slide(1) should return non-empty content"
    assert len(slide_1_html) > 0, "gold_slide(1) HTML should have content"

    slide_3_js = case.gold_scripts(3)
    assert slide_3_js, "gold_scripts(3) should return non-empty content"
    assert "new Chart" in slide_3_js, "gold_scripts(3) should contain 'new Chart'"

    section_css = case.meridian_section_css()
    assert section_css, "meridian_section_css() should return non-empty content"
    assert len(section_css) > 0, "section_css should have content"

    resolved_style = case.meridian_resolved_style()
    assert resolved_style, "meridian_resolved_style() should return non-empty content"
    assert len(resolved_style) > 0, "resolved_style should have content"

    deck_spec = case.gold_deck_spec()
    assert deck_spec, "gold_deck_spec() should return non-empty dict"
    assert "slides" in deck_spec, "deck_spec should have 'slides' key"
    assert len(deck_spec["slides"]) == 10, "deck_spec should have exactly 10 slides"
