"""MCP deck preview: at most ten whole slides, budgeted in UTF-8 bytes, no base64.

``src/services/mcp_deck_preview.py`` builds the HTML preview the MCP tools return as their
second content item (spec "The preview HTML", rules 1-9; PLAN-CORRECTIONS C19-C24, R5, R6;
Task 3 supervisor notes S1, S2):

* the first slides in deck order, at most ``MAX_PREVIEW_SLIDES`` (10), whole, each with its
  own scripts and no others; when slides are left out the page ends with
  "N more slides — see full deck in tellr" linked to ``deck_url`` (C21);
* a top strip "preview — open the full deck in tellr" linked to ``deck_url``, first in
  ``<body>``; ``deck_url`` is attribute-escaped;
* embedded ``@font-face`` rules removed and replaced by one Google Fonts ``@import`` per
  family BEFORE images are hidden (C19), so a font is never counted as an image;
* every image that is not a scoped small SVG is replaced by the notice; ``{{image:…}}`` is
  always hidden; ``images_hidden`` counts the shown slides and the deck css only (S1);
* the css is trimmed against the shown slides' html and scripts;
* the largest number of slides whose page fits ``max_html_bytes`` UTF-8 bytes is shown;
  when not even one fits there is no html;
* ``ds_asset_ids_in`` lists the ``{{ds-asset:N}}`` ids of the slides' html and the css after
  embedded font faces are removed (C23); the input deck is never mutated (C22).

Every oracle is written here from the spec, the brief, the corrections and the supervisor
notes. HTML output is parsed (BeautifulSoup, ``html.parser``) only to inspect it. An inlined
SVG is checked by decoding it back to its text. Budget oracles rebuild the same deck with a
larger ``max_slides`` and an unlimited budget to show the next larger page is over budget.
"""

from __future__ import annotations

import base64
import copy
import dataclasses
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import pytest
from bs4 import BeautifulSoup, Tag

from src.domain.slide_deck import SlideDeck

# Imported through the existing ``src.services`` package so the import sorts the same before
# and after the module exists.
from src.services import mcp_deck_preview

REPO_ROOT = Path(__file__).resolve().parents[2]

DECK_URL = "https://t.example/sessions/s1/edit"
# Unescaped inside a quoted href this closes the attribute and opens an <img onerror>.
HOSTILE_URL = "https://t.example/sessions/s1/edit?q=\"><img src=x onerror=alert(1)>&r='1'"
MEASURE_DECK_URL = "https://tellr.example/sessions/preview/edit"
UNLIMITED = 10**9

# Preview copy, exact (Global Constraints, brief).
STRIP_COPY = "preview — open the full deck in tellr"
IMAGE_NOTICE_COPY = "image not shown in preview, see full deck in tellr"
NOTE_TOO_LARGE = "This deck is too large to preview here. Open the full deck in tellr."
NOTE_NO_SLIDES = "This deck has no slides yet. Open it in tellr."

CHART_JS = "https://cdn.jsdelivr.net/npm/chart.js"
TEXT_SVG_PREFIX = "data:image/svg+xml,"
PNG_URI = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAC"
    "hwGA60e6kgAAAABJRU5ErkJggg=="
)
FONT_B64 = "AAEAAAALAIAAAwAwT1MvMg8SBfAAAAC8AAAAYGNtYXAXVtKNAAABHAAAAFRnYXNwAAAAEAAAAXAAAAAIZ2x5Zg"

# Small SVGs with no prolog, comment or whitespace between tags: cleaning leaves them as-is.
SVG_A = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<circle id="mark-a" cx="5" cy="5" r="4" fill="#FF3621"/></svg>'
)
SVG_B = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
    '<rect id="mark-b" width="4" height="4" fill="#00A972"/></svg>'
)

_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers (test-side only)
# ---------------------------------------------------------------------------


def _token(i: int) -> str:
    """Unique text of slide ``i``; zero-padded so no token is a substring of another."""
    return f"SLIDETXT{i:03d}END"


def _slide(i: int, body: str = "", *, cls: str = "", scripts: str = "") -> dict:
    classes = f"slide {cls}".strip()
    return {
        "slide_id": f"slide_{i}",
        "html": f'<div class="{classes}"><p>{_token(i)}</p>{body}</div>',
        "scripts": scripts,
    }


def _deck(slides: list[dict], *, css: str = "", title: str = "Synthetic deck") -> dict:
    return {
        "title": title,
        "css": css,
        "external_scripts": [CHART_JS],
        "slides": slides,
        "head_meta": {},
    }


def _tiny_deck(n: int) -> dict:
    return _deck([_slide(i) for i in range(n)])


def _build(
    deck: dict,
    *,
    title=None,
    deck_url: str = DECK_URL,
    svg_assets=None,
    max_html_bytes: int = 150_000,
    **kwargs,
):
    return mcp_deck_preview.build_deck_preview(
        deck,
        title=title,
        deck_url=deck_url,
        svg_assets={} if svg_assets is None else svg_assets,
        max_html_bytes=max_html_bytes,
        **kwargs,
    )


def _html(preview) -> str:
    assert isinstance(preview.html, str), f"expected preview html, got {preview!r}"
    return preview.html


def _nbytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _text(el: Tag) -> str:
    return " ".join(el.get_text().split())


def _body_children(soup: BeautifulSoup) -> list[Tag]:
    assert soup.body is not None, "no <body> in the preview"
    return [child for child in soup.body.children if isinstance(child, Tag)]


def _links(el: Tag) -> list[Tag]:
    return ([el] if el.name == "a" else []) + el.find_all("a")


def _hrefs(el: Tag) -> list:
    return [a.get("href") for a in _links(el)]


def _children_with_text(soup: BeautifulSoup, text: str) -> list[int]:
    """Positions of the ``<body>`` element children whose whole text is ``text``."""
    return [i for i, child in enumerate(_body_children(soup)) if _text(child) == text]


def _strip_links(soup: BeautifulSoup) -> list[Tag]:
    return [a for a in soup.find_all("a") if _text(a) == STRIP_COPY]


def _style_text(soup: BeautifulSoup) -> str:
    return "\n".join(style.get_text() for style in soup.find_all("style"))


def _inline_script_text(soup: BeautifulSoup) -> str:
    return "\n".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))


def _decode_text_svg_uri(value) -> str:
    """The SVG text of a percent-encoded (never base64) ``data:image/svg+xml,`` URI."""
    assert isinstance(value, str) and value.startswith(TEXT_SVG_PREFIX), str(value)[:80]
    assert "base64" not in value.lower()
    return unquote(value[len(TEXT_SVG_PREFIX) :])


def _svg_of_size(n: int) -> str:
    """An SVG of exactly ``n`` UTF-8 bytes."""
    head = '<svg xmlns="http://www.w3.org/2000/svg"><desc>'
    tail = "</desc></svg>"
    svg = head + "a" * (n - len(head) - len(tail)) + tail
    assert len(svg.encode()) == n
    return svg


def _b64_svg_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _note_all(n: int, word: str = "slides") -> str:
    return (
        f"Showing all {n} {word} as a preview (standard fonts, images not shown). "
        "Open the full deck in tellr."
    )


def _note_some(k: int, n: int) -> str:
    return (
        f"Showing {k} of {n} slides as a preview (standard fonts, images not shown). "
        "Open the full deck in tellr."
    )


# ---------------------------------------------------------------------------
# Constants and the payload
# ---------------------------------------------------------------------------


def test_constants():
    assert mcp_deck_preview.MAX_PREVIEW_SLIDES == 10
    assert mcp_deck_preview.MCP_RESULT_BUDGET_BYTES == 150_000


def test_as_payload_keys_in_order_and_included_tracks_html():
    preview = _build(_tiny_deck(12))
    payload = preview.as_payload()
    assert list(payload) == ["included", "slides_shown", "slides_total", "images_hidden", "note"]
    assert payload == {
        "included": True,
        "slides_shown": 10,
        "slides_total": 12,
        "images_hidden": 0,
        "note": _note_some(10, 12),
    }

    empty = _build({"slides": []}).as_payload()
    assert list(empty) == ["included", "slides_shown", "slides_total", "images_hidden", "note"]
    assert empty == {
        "included": False,
        "slides_shown": 0,
        "slides_total": 0,
        "images_hidden": 0,
        "note": NOTE_NO_SLIDES,
    }

    def made(html):
        return mcp_deck_preview.DeckPreview(
            html=html, slides_shown=1, slides_total=2, images_hidden=3, note="n"
        ).as_payload()

    assert made("<p>x</p>") == {
        "included": True,
        "slides_shown": 1,
        "slides_total": 2,
        "images_hidden": 3,
        "note": "n",
    }
    assert made(None)["included"] is False

    with pytest.raises(dataclasses.FrozenInstanceError):
        preview.slides_shown = 1


# ---------------------------------------------------------------------------
# Slides: the cap, the trailing notice, scripts, the strip
# ---------------------------------------------------------------------------


def test_preview_caps_at_ten_slides_with_more_notice():
    preview = _build(_tiny_deck(14))
    html = _html(preview)
    assert preview.slides_shown == 10
    assert preview.slides_total == 14
    assert preview.note == _note_some(10, 14)
    for i in range(10):
        assert _token(i) in html
    for i in range(10, 14):
        assert _token(i) not in html
    assert len(_children_with_text(_soup(html), "4 more slides — see full deck in tellr")) == 1


def test_preview_shows_every_slide_when_under_cap():
    preview = _build(_tiny_deck(3))
    html = _html(preview)
    assert preview.slides_shown == 3
    assert preview.slides_total == 3
    positions = [html.find(_token(i)) for i in range(3)]
    assert -1 not in positions
    assert positions == sorted(positions)
    assert "more slide" not in html
    assert preview.note == _note_all(3)


def test_one_more_slide_singular():
    preview = _build(_tiny_deck(11))
    html = _html(preview)
    assert preview.slides_shown == 10
    assert len(_children_with_text(_soup(html), "1 more slide — see full deck in tellr")) == 1
    assert "1 more slides" not in html
    assert preview.note == _note_some(10, 11)


def test_note_singular_for_a_one_slide_deck():
    preview = _build(_tiny_deck(1))
    assert preview.slides_shown == 1
    assert preview.note == _note_all(1, "slide")
    assert "more slide" not in _html(preview)


def test_top_strip_links_to_deck_url():
    links = _strip_links(_soup(_html(_build(_tiny_deck(2)))))
    assert [a.get("href") for a in links] == [DECK_URL]

    soup = _soup(_html(_build(_tiny_deck(2), deck_url=HOSTILE_URL)))
    assert soup.find_all(attrs={"onerror": True}) == []
    assert soup.find_all("img") == []
    assert [a.get("href") for a in _strip_links(soup)] == [HOSTILE_URL]


def test_strip_is_first_in_body_and_notice_follows_the_last_shown_slide():
    deck = _deck([_slide(i, scripts=f"new Chart('c{i}')") for i in range(12)])
    soup = _soup(_html(_build(deck, deck_url=HOSTILE_URL)))
    assert soup.find_all(attrs={"onerror": True}) == []
    children = _body_children(soup)
    assert children, "empty <body>"

    assert _text(children[0]) == STRIP_COPY
    assert _hrefs(children[0]) == [HOSTILE_URL]

    notices = _children_with_text(soup, "2 more slides — see full deck in tellr")
    assert len(notices) == 1
    slide_positions = [
        i
        for i, child in enumerate(children)
        if any(_token(k) in child.get_text() for k in range(12))
    ]
    assert slide_positions
    assert notices[0] > max(slide_positions)
    assert _hrefs(children[notices[0]]) == [HOSTILE_URL]


def _declarations(style: str, selector: str) -> str:
    """The declarations of the rule written for exactly ``selector`` (whitespace removed)."""
    flat = re.sub(r"\s+", "", style)
    match = re.search(re.escape(selector) + r"\{([^{}]*)\}", flat)
    assert match, f"no rule for {selector} in {flat[:300]!r}"
    return match.group(1)


def test_each_shown_slide_sits_in_its_own_frame_with_the_strip_and_notice_outside():
    """Final review C1: a design-system deck styles the slide root
    ``.slide{position:absolute;inset:0}``. As in the Tellr app (``slideHostFrameStyle``),
    each slide sits in its own positioned 1280x720 frame, whose direct child fills it, so
    the slides stay in flow and never cover the strip or the notice."""
    css = ".slide{position:absolute;inset:0;background:#0B2026;color:#fff}"
    deck = _deck([_slide(i) for i in range(12)], css=css)
    soup = _soup(_html(_build(deck)))
    children = _body_children(soup)

    frames = [c for c in children if any(_token(i) in c.get_text() for i in range(12))]
    assert len(frames) == 10
    for i, frame in enumerate(frames):
        assert [k for k in range(12) if _token(k) in frame.get_text()] == [i]
        [root] = [c for c in frame.children if isinstance(c, Tag)]
        assert "slide" in root.get("class")
        assert _token(i) in root.get_text()
    assert len({tuple(f.get("class") or ()) for f in frames}) == 1
    [frame_class] = frames[0].get("class")
    assert frame_class != "slide"

    style = _style_text(soup)
    frame_rule = _declarations(style, f".{frame_class}")
    for declaration in (
        "position:relative!important",
        "width:1280px!important",
        "height:720px!important",
        "overflow:hidden",
        "margin:",
    ):
        assert declaration in frame_rule, declaration
    child_rule = _declarations(
        style, f".{frame_class}>:not(#tellr-host-frame-boost):not(.slide-wrapper)"
    )
    for declaration in (
        "position:absolute!important",
        "inset:0!important",
        "width:100%!important",
        "height:100%!important",
        "box-sizing:border-box!important",
        "overflow:hidden",
    ):
        assert declaration in child_rule, declaration

    # The strip and the notice are body-level siblings of the frames, outside them.
    assert _text(children[0]) == STRIP_COPY
    [notice] = _children_with_text(soup, "2 more slides — see full deck in tellr")
    assert notice > children.index(frames[-1])
    for frame in frames:
        assert STRIP_COPY not in frame.get_text()
        assert "see full deck in tellr" not in frame.get_text()


def test_a_slide_is_verbatim_inside_its_frame():
    """The frame wraps the slide's html and changes nothing in it (C13)."""
    legacy = "<div class='slide'  data-n=1>\n  <h1 style='color:#FF3621'>T &amp; x</h1>\n</div>"
    deck = _deck([{"slide_id": "slide_0", "html": legacy, "scripts": ""}])
    html = _html(_build(deck))
    assert legacy in html
    soup = _soup(html)
    [frame] = [c for c in _body_children(soup) if "T & x" in c.get_text()]
    # The body-level element is the frame, and the slide root is its only element child.
    assert "slide" not in (frame.get("class") or [])
    [root] = [c for c in frame.children if isinstance(c, Tag)]
    assert root.get("class") == ["slide"]
    assert root.find("h1").get_text() == "T & x"


@pytest.mark.parametrize(
    ("css", "slide_body"),
    [
        pytest.param(
            '.slide{position:absolute}.slide::after{content:"\n</head>\n<body>\n"}',
            "",
            id="css-string-holds-the-head-body-boundary",
        ),
        pytest.param(
            "",
            "<style>\n.x{color:red}\n  </style>\n<p>x</p>\n</head>\n<body>\n",
            id="no-deck-css-and-a-slide-style-block",
        ),
    ],
)
def test_the_strip_and_frame_rules_land_at_the_documents_own_head_and_body(css, slide_body):
    """The strip is the first child of the real ``<body>`` and the frame rules are a
    ``<style>`` of the real ``<head>``, whatever text the css or a slide carries."""
    preview = _build(_deck([_slide(0, slide_body)], css=css))
    soup = _soup(_html(preview))

    assert _text(_body_children(soup)[0]) == STRIP_COPY
    head_styles = [s.get_text() for s in soup.head.find_all("style")]
    assert any(".tellr-preview-frame{" in re.sub(r"\s+", "", s) for s in head_styles)
    [frame] = [c for c in _body_children(soup) if _token(0) in c.get_text()]
    assert frame.get("class") == ["tellr-preview-frame"]


def test_scripts_only_for_shown_slides():
    slides = [_slide(i, f'<canvas id="cv{i}"></canvas>') for i in range(12)]
    for i in (0, 9, 10, 11):
        slides[i]["scripts"] = f"new Chart('c{i}')"
    deck = _deck(slides)
    # A persisted snapshot also carries every slide's scripts at deck level.
    deck["scripts"] = "\n".join(s["scripts"] for s in slides if s["scripts"])
    html = _html(_build(deck))
    soup = _soup(html)
    inline_js = _inline_script_text(soup)
    assert "new Chart('c0')" in inline_js
    assert "new Chart('c9')" in inline_js
    assert "'c10'" not in html
    assert "'c11'" not in html
    assert soup.find("script", src=CHART_JS) is not None


# ---------------------------------------------------------------------------
# Fonts and images
# ---------------------------------------------------------------------------


def test_preview_drops_fonts_and_adds_google_import():
    css = (
        "@font-face{font-family:'DM Sans';font-weight:400;"
        f"src:url(data:font/ttf;base64,{FONT_B64}) format('truetype')}}"
        "@font-face{font-family:'DM Sans';font-style:italic;font-weight:700;"
        f"src:url('data:font/ttf;base64,{FONT_B64}') format('truetype')}}"
        ".s-body{font-family:'DM Sans',system-ui,sans-serif}"
    )
    preview = _build(_deck([_slide(0, cls="s-body")], css=css))
    html = _html(preview)
    assert "base64" not in html.lower()
    assert "@font-face" not in html
    style = _style_text(_soup(html)).strip()
    # An @import is only honoured before every other rule.
    assert style.startswith(
        "@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;1,700"
        "&display=swap');"
    ), style[:200]
    assert ".s-body{font-family:'DM Sans',system-ui,sans-serif}" in style
    # A removed font face is not an image.
    assert preview.images_hidden == 0


def test_preview_of_inline_data_uri_deck_has_no_base64():
    big_svg = _svg_of_size(15_000)
    css = (
        "@font-face{font-family:'Brand Sans';"
        f"src:url(data:font/woff2;base64,{FONT_B64}) format('woff2')}}"
    )
    slides = [
        _slide(0, f'<img src="{PNG_URI}" alt="chart">'),
        _slide(1, f'<img src="{_b64_svg_uri(big_svg)}">'),
    ]
    preview = _build(_deck(slides, css=css))
    html = _html(preview)
    assert "base64" not in html.lower()
    assert preview.images_hidden == 2
    imgs = _soup(html).find_all("img")
    assert len(imgs) == 2
    assert [img.get("alt") for img in imgs] == [IMAGE_NOTICE_COPY, IMAGE_NOTICE_COPY]


def _svg_deck() -> dict:
    slide = _slide(
        0, '<img class="logo" src="{{ds-asset:7}}" alt="logo"><div class="brand-band">band</div>'
    )
    css = ".brand-band{height:8px;background:#fff url({{ds-asset:8}}) no-repeat}"
    return _deck([slide], css=css)


def test_scoped_small_svgs_are_inlined_as_text_in_slides_and_css():
    preview = _build(_svg_deck(), svg_assets={7: SVG_A, 8: SVG_B})
    html = _html(preview)
    assert "{{ds-asset:" not in html
    assert preview.images_hidden == 0
    soup = _soup(html)
    imgs = soup.find_all("img")
    assert len(imgs) == 1
    assert _decode_text_svg_uri(imgs[0].get("src")) == SVG_A
    css_urls = [m.group(2) for m in _CSS_URL.finditer(_style_text(soup))]
    assert len(css_urls) == 1, css_urls
    assert _decode_text_svg_uri(css_urls[0]) == SVG_B


def test_without_scoped_svgs_the_same_handles_are_hidden():
    preview = _build(_svg_deck(), svg_assets={})
    html = _html(preview)
    assert "{{ds-asset:" not in html
    assert preview.images_hidden == 2
    assert "mark-a" not in html
    assert "mark-b" not in html
    soup = _soup(html)
    imgs = soup.find_all("img")
    assert len(imgs) == 1
    assert imgs[0].get("alt") == IMAGE_NOTICE_COPY
    style = _style_text(soup)
    assert ".brand-band{" in style
    assert "url(" not in style


def test_image_and_unscoped_handles_never_survive():
    slides = [
        _slide(0, '<img src="{{image:abc}}">'),
        _slide(1, "<div style=\"background:url('{{ds-asset:9}}')\">bg</div>"),
        _slide(2, cls="hero"),
    ]
    css = ".hero{background:#0B2026 url({{image:bg1}}) center/cover}"
    preview = _build(_deck(slides, css=css), svg_assets={7: SVG_A})
    html = _html(preview)
    assert "{{" not in html
    assert preview.images_hidden == 3


def test_images_hidden_counts_only_shown_slides_and_css():
    slides = [_slide(i) for i in range(12)]
    slides[0] = _slide(0, '<img src="{{image:first}}">')
    slides[1] = _slide(1, cls="hero")
    slides[11] = _slide(11, f'<img src="{{{{image:late}}}}"><img src="{PNG_URI}">')
    css = f".hero{{background:#123 url({PNG_URI})}}"
    preview = _build(_deck(slides, css=css))
    assert preview.slides_shown == 10
    # slide 1's <img> + the .hero background; slide 12's two images are not in the preview.
    assert preview.images_hidden == 2


# ---------------------------------------------------------------------------
# CSS trim
# ---------------------------------------------------------------------------


def test_css_trimmed_to_shown_slides():
    slides = [_slide(i) for i in range(12)]
    slides[0]["scripts"] = "document.querySelector('.slide').classList.add('lit-by-script')"
    slides[11] = _slide(
        11, cls="only-on-slide-12", scripts="document.body.classList.add('lit-late')"
    )
    css = ".only-on-slide-12{x:1}.lit-by-script{y:2}.lit-late{w:4}"

    style = _style_text(_soup(_html(_build(_deck(slides, css=css)))))
    assert "only-on-slide-12" not in style
    assert "lit-late" not in style
    # Named only by a shown slide's script: still styles something.
    assert ".lit-by-script{y:2}" in style

    every = _build(_deck(slides, css=css), max_slides=12)
    assert every.slides_shown == 12
    style = _style_text(_soup(_html(every)))
    assert ".only-on-slide-12{x:1}" in style
    assert ".lit-by-script{y:2}" in style
    assert ".lit-late{w:4}" in style


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_budget_stops_before_the_slide_that_would_cross():
    filler = "abcdefghij" * 3_000  # 30_000 ASCII bytes per slide
    deck = _deck([_slide(i, f"<p>{filler}</p>") for i in range(6)])
    preview = _build(deck, max_html_bytes=100_000)
    html = _html(preview)
    assert _nbytes(html) <= 100_000
    # Three 30 KB slides and the page around them fit in 100 KB; a fourth cannot.
    assert preview.slides_shown == 3
    assert preview.slides_total == 6
    assert preview.note == _note_some(3, 6)
    assert html.count(filler) == 3  # whole slides only
    for i in range(3):
        assert _token(i) in html
    for i in range(3, 6):
        assert _token(i) not in html
    assert len(_children_with_text(_soup(html), "3 more slides — see full deck in tellr")) == 1
    # "Largest k": every larger preview of the same deck is over the budget.
    for k in range(4, 7):
        bigger = _build(deck, max_html_bytes=UNLIMITED, max_slides=k)
        assert bigger.slides_shown == k
        assert _nbytes(_html(bigger)) > 100_000


def test_budget_counts_utf8_bytes():
    payload = "é—😀" * 3_000  # 9_000 characters, 27_000 UTF-8 bytes
    deck = _deck([_slide(i, f"<p>{payload}</p>") for i in range(4)])
    budget = 60_000
    preview = _build(deck, max_html_bytes=budget)
    html = _html(preview)
    assert _nbytes(html) <= budget
    assert preview.slides_shown == 2
    assert html.count(payload) == 2
    # The three-slide page fits by characters but not by bytes ...
    three = _html(_build(deck, max_html_bytes=UNLIMITED, max_slides=3))
    assert len(three) <= budget < _nbytes(three)
    # ... and by characters even all four slides would fit.
    four = _html(_build(deck, max_html_bytes=UNLIMITED))
    assert len(four) <= budget


def test_budget_takes_the_largest_fitting_k_even_when_a_smaller_one_does_not_fit():
    deck = _deck(
        [
            _slide(0, "<p>" + "x" * 2_000 + "</p>"),
            {"slide_id": "slide_1", "html": '<div class="slide"></div>', "scripts": ""},
        ]
    )
    one = _html(_build(deck, max_html_bytes=UNLIMITED, max_slides=1))
    both = _html(_build(deck, max_html_bytes=UNLIMITED))
    # Premise: the one-slide page carries the "1 more slide" notice, which outweighs the
    # empty second slide, so the whole deck is the smaller page.
    assert _nbytes(one) > _nbytes(both)
    preview = _build(deck, max_html_bytes=_nbytes(both))
    assert preview.slides_shown == 2
    assert preview.note == _note_all(2)
    assert _nbytes(_html(preview)) <= _nbytes(both)


def test_nothing_fits_gives_no_html():
    single = _deck([_slide(0, '<img src="{{image:big}}"><p>' + "x" * 5_000 + "</p>")])
    preview = _build(single, max_html_bytes=2_000)
    assert preview.html is None
    assert preview.slides_shown == 0
    assert preview.slides_total == 1
    assert preview.images_hidden == 0
    assert preview.note == NOTE_TOO_LARGE
    assert preview.as_payload()["included"] is False

    first_too_big = _deck([_slide(0, "<p>" + "x" * 5_000 + "</p>"), _slide(1), _slide(2)])
    preview = _build(first_too_big, max_html_bytes=2_000)
    assert preview.html is None
    assert preview.slides_shown == 0
    assert preview.slides_total == 3
    assert preview.note == NOTE_TOO_LARGE


def test_empty_deck():
    for deck in ({"slides": []}, {"css": ".x{background:url({{image:q}})}", "slides": []}):
        preview = _build(deck)
        assert preview.html is None
        assert preview.slides_shown == 0
        assert preview.slides_total == 0
        assert preview.images_hidden == 0
        assert preview.note == NOTE_NO_SLIDES


# ---------------------------------------------------------------------------
# Title, robustness, input safety
# ---------------------------------------------------------------------------


def test_title_is_escaped_and_falls_back_to_the_deck_title():
    deck = _deck([_slide(0)], title="Stored <deck>")
    html = _html(_build(deck, title="A & B"))
    assert "<title>A &amp; B</title>" in html
    assert _soup(html).title.get_text() == "A & B"
    html = _html(_build(deck, title=None))
    assert "<title>Stored &lt;deck&gt;</title>" in html


def test_missing_css_none_html_and_missing_scripts_do_not_raise():
    no_css = {"slides": [{"html": None}, {"html": '<div class="slide">B-TEXT</div>'}]}
    preview = _build(no_css)
    html = _html(preview)
    assert "B-TEXT" in html
    assert preview.slides_shown == 2
    assert preview.slides_total == 2
    assert "more slide" not in html
    assert mcp_deck_preview.ds_asset_ids_in(no_css) == set()

    none_css = {
        "title": "T",
        "css": None,
        "slides": [{"html": '<div class="slide">A-TEXT</div>', "scripts": None}],
    }
    preview = _build(none_css)
    assert "A-TEXT" in _html(preview)
    assert preview.slides_shown == 1
    assert mcp_deck_preview.ds_asset_ids_in(none_css) == set()


_HUGE = 100_000


def _repeated(atom: str) -> str:
    """About ``_HUGE`` characters of ``atom``, never closed."""
    return atom * (_HUGE // len(atom))


def _unclosed_slide(atom: str) -> dict:
    """Slide 0 whose html ENDS in the unclosed atoms: no later ``>`` or ``)`` closes them
    (``_slide``'s closing ``</div>`` would give the old tag pattern one long match)."""
    return {"slide_id": "slide_0", "html": f"<p>{_token(0)}</p>" + _repeated(atom), "scripts": ""}


@pytest.mark.parametrize(
    "deck",
    [
        pytest.param(_deck([_slide(0)], css=_repeated("url(")), id="css-unclosed-url"),
        pytest.param(_deck([_unclosed_slide('<img src="x" ')]), id="slide-unclosed-img"),
        pytest.param(
            _deck([_unclosed_slide('<div style="background:url(')]),
            id="slide-unclosed-style-url",
        ),
    ],
)
def test_unclosed_markup_does_not_stall_the_preview(deck):
    """Final review I1: the preview is built inline on the event loop, so ~100 KB of
    unclosed atoms must cost milliseconds, not the seconds the old patterns took."""
    started = time.perf_counter()
    preview = _build(deck, max_html_bytes=UNLIMITED)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"{elapsed:.2f} s"
    assert preview.slides_shown == 1
    assert _token(0) in _html(preview)


def test_only_the_slides_that_can_be_shown_go_through_the_image_pass():
    """Images on slides past the cap are never counted (S1), so they are not processed
    either: the image pass sees the first ``min(total, max_slides)`` slides only."""
    seen: list[str] = []
    real = mcp_deck_preview.hide_images_in_html

    def recording(html, svg_assets):
        seen.append(html)
        return real(html, svg_assets)

    deck = _tiny_deck(14)
    with patch.object(mcp_deck_preview, "hide_images_in_html", side_effect=recording):
        preview = _build(deck)
        assert preview.slides_shown == 10
        assert seen == [s["html"] for s in deck["slides"][:10]]

        seen.clear()
        assert _build(deck, max_slides=3).slides_shown == 3
        assert seen == [s["html"] for s in deck["slides"][:3]]


def _outside_style_blocks(html: str) -> str:
    """``html`` with every ``<style>`` element's raw text removed, ending each where the
    HTML tokenizer does: at ``</style`` followed by whitespace, ``/`` or ``>``."""
    return re.sub(r"<style\b[^>]*>.*?(?:</style(?=[\t\n\f\r />])|\Z)", "", html, flags=re.S | re.I)


def test_rule_9_guards_hold_in_the_preview():
    """Final review M2 (spec rule 9): the preview page is built by ``to_html_document``,
    so its guards apply: the title is escaped, no ``</style`` closer in the deck css ends
    the style block early, and only http(s) script srcs are kept, attribute-escaped."""
    title = "</title><script>alert('title')</script>"
    css = (
        ".slide{color:red}</style><script>alert('css1')</script><style>"
        ".q{a:b}</style x><script>alert('css2')</script>"
    )
    hostile_src = "https://e.com/x.js\"><script>alert('src')</script>"
    deck = _deck([_slide(0)], css=css)
    deck["external_scripts"] = ["javascript:alert('js')", hostile_src]

    html = _html(_build(deck, title=title))
    soup = _soup(html)

    # title escaped
    assert soup.title.get_text() == title
    assert "<script>alert('title')" not in html
    # the css stays inside its style block, whatever closer it carries
    assert "alert('css1')" in html and "alert('css2')" in html
    outside = _outside_style_blocks(html)
    assert "alert('css" not in outside, outside[:400]
    # scripts: no javascript: src, the quote-breaking src never opens a script
    srcs = [s.get("src") for s in soup.find_all("script") if s.get("src")]
    assert not [s for s in srcs if s.lower().startswith("javascript:")]
    assert set(srcs) <= {CHART_JS, hostile_src}
    assert "alert('src')" not in "".join(s.get_text() for s in soup.find_all("script"))
    assert "<script>alert('src')" not in html


def test_ds_asset_ids_skip_font_faces():
    deck = {
        "css": (
            "@font-face{font-family:'Brand';src:url({{ds-asset:1}}) format('woff2')}"
            ".l{background:url({{ds-asset:2}})}"
            "@media print{@font-face{font-family:'Brand';font-weight:700;"
            "src:url('{{ds-asset:6}}')}}"
        ),
        "html_content": '<html><body><img src="{{ds-asset:5}}"></body></html>',
        "scripts": "var logo = '{{ds-asset:4}}';",
        "slides": [
            {
                "html": '<div class="slide l"><img src="{{ds-asset:3}}"></div>',
                "scripts": "img.src = '{{ds-asset:4}}';",
            },
            {"html": '<div class="slide" style="background:url({{ds-asset:10}})">x</div>'},
        ],
    }
    ids = mcp_deck_preview.ds_asset_ids_in(deck)
    assert isinstance(ids, set)
    assert ids == {2, 3, 10}


def test_input_deck_not_mutated():
    css = (
        f"@font-face{{font-family:'DM Sans';src:url(data:font/ttf;base64,{FONT_B64})}}"
        "@font-face{font-family:'Brand';src:url({{ds-asset:3}})}"
        ".hero{background:url({{image:bg}})}"
    )
    slides = [_slide(i, scripts=f"new Chart('c{i}')") for i in range(12)]
    slides[0] = _slide(0, '<img src="{{ds-asset:7}}">', cls="hero")
    slides[1] = _slide(1, '<img src="{{image:abc}}">')
    slides[2] = _slide(2, f'<img src="{PNG_URI}">')
    slides[3] = _slide(3, '<div style="background:url({{ds-asset:9}})">x</div>')
    deck = _deck(slides, css=css)
    deck["html_content"] = '<html><body><img src="{{ds-asset:7}}"></body></html>'
    before = copy.deepcopy(deck)

    preview = _build(deck, svg_assets={7: SVG_A})
    ids = mcp_deck_preview.ds_asset_ids_in(deck)

    assert deck == before
    # The work that must not happen in place did happen on the preview.
    html = _html(preview)
    assert preview.slides_shown == 10
    assert "base64" not in html.lower()
    assert "{{" not in html
    assert ids == {7, 9}


# ---------------------------------------------------------------------------
# Measuring script (CLI only)
# ---------------------------------------------------------------------------


def test_measuring_script_writes_a_base64_free_preview_per_input(tmp_path):
    font_css = (
        "@font-face{font-family:'DM Sans';"
        f"src:url(data:font/ttf;base64,{FONT_B64}) format('truetype')}}"
    )
    export_deck = _deck([_slide(0, f'<img src="{PNG_URI}">'), _slide(1)], css=font_css)
    export = tmp_path / "export_deck.html"
    export.write_text(SlideDeck.from_dict(export_deck).to_html_document(), encoding="utf-8")

    probe_deck = _deck([_slide(20 + i) for i in range(3)])
    probe_deck["slides"][0] = _slide(20, f'<img src="{_b64_svg_uri(_svg_of_size(15_000))}">')
    probe_text = json.dumps({"deck": probe_deck})
    probe = tmp_path / "probe_get_deck.json"
    probe.write_text(
        json.dumps({"body": {"result": {"content": [{"type": "text", "text": probe_text}]}}}),
        encoding="utf-8",
    )

    out = tmp_path / "preview-out"  # not created beforehand
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.measure_mcp_preview",
            str(export),
            str(probe),
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "ENVIRONMENT": "test"},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    for name in ("export_deck.html", "probe_get_deck.json"):
        assert sum(name in line for line in lines) == 1, result.stdout

    for stem, tokens in (("export_deck", (0, 1)), ("probe_get_deck", (20, 21, 22))):
        path = out / f"{stem}.preview.html"
        assert path.exists(), f"{path.name} not written; stdout: {result.stdout}"
        preview = path.read_text(encoding="utf-8")
        assert "base64" not in preview.lower()
        soup = _soup(preview)
        assert [a.get("href") for a in _strip_links(soup)] == [MEASURE_DECK_URL]
        for i in tokens:
            assert _token(i) in preview
