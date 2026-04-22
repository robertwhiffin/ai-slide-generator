"""Tests for SlideDeck.to_html_document() serializer."""

import pytest

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck


@pytest.fixture
def minimal_deck():
    return SlideDeck(
        title="Test Deck",
        css=".slide { background: white; }",
        external_scripts=["https://cdn.jsdelivr.net/npm/chart.js"],
        slides=[
            Slide(html='<div class="slide"><h1>Slide 1</h1></div>', scripts=""),
            Slide(
                html='<div class="slide"><canvas id="c1"></canvas></div>',
                scripts='new Chart(document.getElementById("c1"), {});',
            ),
        ],
    )


def test_to_html_document_is_valid_html5(minimal_deck):
    out = minimal_deck.to_html_document()
    assert out.startswith("<!doctype html>") or out.startswith("<!DOCTYPE html>")
    assert "<html" in out
    assert "<head>" in out
    assert "<body>" in out
    assert "</html>" in out


def test_to_html_document_includes_title(minimal_deck):
    out = minimal_deck.to_html_document()
    assert "<title>Test Deck</title>" in out


def test_to_html_document_includes_deck_css(minimal_deck):
    out = minimal_deck.to_html_document()
    assert ".slide { background: white; }" in out


def test_to_html_document_includes_chart_js_cdn(minimal_deck):
    out = minimal_deck.to_html_document()
    assert "chart.js" in out


def test_to_html_document_includes_all_slide_html(minimal_deck):
    out = minimal_deck.to_html_document()
    assert "<h1>Slide 1</h1>" in out
    assert '<canvas id="c1"></canvas>' in out


def test_to_html_document_includes_slide_scripts(minimal_deck):
    out = minimal_deck.to_html_document()
    assert 'new Chart(document.getElementById("c1")' in out


def test_to_html_document_overrides_chart_js_cdn(minimal_deck):
    out = minimal_deck.to_html_document(chart_js_cdn="https://internal.cdn/chart.js")
    assert "https://internal.cdn/chart.js" in out
    # Default CDN should not appear in the output
    assert out.count("cdn.jsdelivr.net") == 0


def test_to_html_document_empty_deck():
    deck = SlideDeck(title="Empty")
    out = deck.to_html_document()
    assert "<!doctype html>" in out.lower()
    assert "<title>Empty</title>" in out


def test_to_html_document_is_deterministic(minimal_deck):
    a = minimal_deck.to_html_document()
    b = minimal_deck.to_html_document()
    assert a == b
