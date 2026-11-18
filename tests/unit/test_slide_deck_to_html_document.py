"""Tests for SlideDeck.to_html_document() serializer."""

import re

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
    """CSS containing </style> must not be able to break out of the style block.

    Uses only a surgical strip of </style> tags; everything else (including
    legitimate CSS with <, and any non-</style> HTML-shaped text inside CSS
    string/data-URI contexts) must survive.
    """
    malicious_css = (
        "body { color: red; }"
        "</style>"
        "<script>alert(1)</script>"
        "<style>"
    )
    deck = SlideDeck(title="X", css=malicious_css)
    out = deck.to_html_document()

    # Legitimate CSS survives
    assert "body { color: red; }" in out

    # The </style> that would break out of our style element is stripped
    # (case-insensitive). After stripping, exactly ONE </style> remains
    # in the output — the one we emit ourselves as the closer.
    closers = len(re.findall(r"</\s*style\s*>", out, flags=re.IGNORECASE))
    assert closers == 1, f"expected exactly 1 </style>, saw {closers}"


#: Where the HTML tokenizer ends a <style> element's raw text: ``</style`` followed by
#: whitespace, ``/`` or ``>`` (any case), or at the end of the input.
_TOKENIZER_STYLE_CLOSER = re.compile(r"</style(?=[\t\n\f\r />]|\Z)", re.IGNORECASE)


@pytest.mark.parametrize(
    "closer",
    [
        pytest.param("</style>", id="plain"),
        pytest.param("</style x>", id="with-attribute"),
        pytest.param("</style/>", id="self-closing"),
        pytest.param("</STYLE\t>", id="upper-case-tab"),
        pytest.param("<</style/style>", id="re-forms-when-removed"),
        pytest.param("</sty</style>le>", id="nested-in-a-closer"),
    ],
)
def test_to_html_document_neutralises_every_style_closer_form(closer):
    """Final review M1: every form the tokenizer reads as the style end tag is
    neutralised, so the css cannot open a live <script>; the css text survives."""
    css = f"body {{ color: red; }}{closer}<script>alert(1)</script><style>"
    out = SlideDeck(title="X", css=css).to_html_document()

    assert "body { color: red; }" in out
    assert "alert(1)" in out
    # Exactly one closer remains: the one we emit ourselves, after all the css.
    closers = [m.start() for m in _TOKENIZER_STYLE_CLOSER.finditer(out)]
    assert len(closers) == 1, closers
    assert closers[0] > out.index("alert(1)")


def test_to_html_document_neutralises_a_closer_at_the_end_of_the_css():
    """``</style`` ending the css is followed by our newline: the tokenizer reads that
    as the end tag too."""
    out = SlideDeck(title="X", css="body { color: red; }</style").to_html_document()

    closers = [m.start() for m in _TOKENIZER_STYLE_CLOSER.finditer(out)]
    assert len(closers) == 1, closers
    assert "body { color: red; }" in out


def test_to_html_document_keeps_only_http_and_https_external_scripts():
    """Final review M2: the http(s)-only script src guard. ``external_scripts`` reaches
    ``to_html_document`` from a deck dict through ``SlideDeck.from_dict`` (which keeps
    the list as given; the constructor appends the Chart.js default)."""
    deck = SlideDeck.from_dict(
        {
            "title": "X",
            "external_scripts": [
                "javascript:alert(1)",
                "data:text/javascript,alert(2)",
                "//evil.example/x.js",
                "https://ok.example/a.js",
                "http://ok.example/b.js",
            ],
            "slides": [],
        }
    )

    out = deck.to_html_document()

    assert re.findall(r'<script src="([^"]*)"></script>', out) == [
        "https://ok.example/a.js",
        "http://ok.example/b.js",
        SlideDeck.CHART_JS_URL,
    ]
    assert "javascript:" not in out
    assert "alert(2)" not in out
    assert "evil.example" not in out


def test_to_html_document_preserves_legitimate_css_with_angle_brackets():
    """CSS containing <> in string literals or data URIs must be preserved."""
    legit_css = (
        "p::before { content: '<foo>'; }\n"
        "div { background: url('data:image/svg+xml,<svg></svg>'); }"
    )
    deck = SlideDeck(title="X", css=legit_css)
    out = deck.to_html_document()
    assert "content: '<foo>';" in out
    assert "data:image/svg+xml,<svg></svg>" in out


def test_to_html_document_escapes_chart_js_cdn_attribute():
    """A CDN URL that tries to break out of the src attribute must be neutralized."""
    deck = SlideDeck(title="X")
    malicious_cdn = 'https://ok.cdn/chart.js" onerror="alert(1)'
    out = deck.to_html_document(chart_js_cdn=malicious_cdn)

    # Unescaped onerror attribute must not appear
    assert 'onerror="alert(1)"' not in out

    # Escaped form (both " in the URL escaped to &quot;) appears — proving
    # we emitted the tag with the URL, just safely escaped, rather than
    # dropping it. The input URL contains two literal quotes (the attribute-
    # breakout and the opening of the injected onerror); both get escaped.
    assert "chart.js&quot; onerror=&quot;alert(1)" in out


def test_to_html_document_includes_lang_and_viewport(minimal_deck):
    """Output should declare language (a11y) and viewport (mobile)."""
    out = minimal_deck.to_html_document()
    assert 'lang="en"' in out
    assert 'name="viewport"' in out
    assert "width=device-width" in out
