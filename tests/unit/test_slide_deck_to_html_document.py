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
    assert f'<script src="{SlideDeck.CHART_JS_URL}">' in out


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


def test_to_html_document_does_not_mutate_external_scripts(minimal_deck):
    original = list(minimal_deck.external_scripts)
    minimal_deck.to_html_document(chart_js_cdn="https://other.cdn/chart.js")
    assert minimal_deck.external_scripts == original


def test_to_html_document_escapes_title():
    """Title with HTML/script content must not break out of the <title> element."""
    malicious_title = '</title><script>alert(1)</script><title>X'
    deck = SlideDeck(title=malicious_title)
    out = deck.to_html_document()
    # The exact <script> tag should NOT appear unescaped
    assert "<script>alert(1)</script>" not in out
    # Escaped form should appear (html.escape converts < > to &lt; &gt;)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_to_html_document_strips_style_closer_from_css():
    """CSS containing </style> must not be able to break out of the style block."""
    malicious_css = "body { color: red; }</style><script>alert(1)</script><style>"
    deck = SlideDeck(title="X", css=malicious_css)
    out = deck.to_html_document()
    # The injected script tag should not appear as executable markup
    assert "<script>alert(1)</script>" not in out


def test_to_html_document_escapes_chart_js_cdn_attribute():
    """A CDN URL that tries to break out of the src attribute must be neutralized."""
    deck = SlideDeck(title="X")
    out = deck.to_html_document(chart_js_cdn='https://ok.cdn/chart.js" onerror="alert(1)')
    # Unescaped onerror attribute should NOT appear
    assert 'onerror="alert(1)"' not in out
