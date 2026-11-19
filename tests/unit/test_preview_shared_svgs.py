"""MCP deck preview: an SVG used on several slides is sent once.

Found by the devloop size evaluation: a deck with the Databricks logo (a ~6 KB SVG) on every
slide carried one full copy per slide, ~60 KB of a 75 KB preview, and Genie One retypes every
byte. ``share_repeated_svg_images`` moves each repeated SVG into one CSS background rule and
gives every ``<img>`` that used it an empty placeholder SVG of the same size and shape, so the
layout is unchanged.
"""

from __future__ import annotations

import base64
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

from src.services import mcp_deck_preview
from src.utils import preview_images

DECK_URL = "https://t.example/sessions/s1/edit"
UNLIMITED = 10**9

_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="713" height="113" viewBox="0 0 713 113">'
    + "".join(f'<path fill="#FF3621" d="M{i} 0h4v4h-4z"/>' for i in range(60))
    + "</svg>"
)


def _decoded_svg(uri: str) -> str:
    assert uri.startswith("data:image/svg+xml,")
    return unquote(uri[len("data:image/svg+xml,"):])


def test_repeated_svg_is_sent_once_as_a_css_background():
    logo = preview_images.svg_data_uri(_LOGO_SVG)
    htmls = [
        f'<div><img alt="Databricks" src="{logo}" style="height:30px;width:auto"></div>',
        f"<img class='footer-logo' src='{logo}'>",
        f'<p>no logo here</p><img src="{logo}"/>',
    ]
    shared, css = preview_images.share_repeated_svg_images(htmls)

    page = "".join(shared) + css
    assert page.count(logo) == 1, "the logo's text must appear exactly once"
    assert logo in css
    assert len(page.encode()) < len(logo) + 1200, "three uses must cost far less than three copies"

    imgs = BeautifulSoup("".join(shared), "html.parser").find_all("img")
    assert len(imgs) == 3
    classes = [set(img.get("class") or []) for img in imgs]
    shared_class = (classes[0] - {"footer-logo"}).pop()
    assert all(shared_class in c for c in classes)
    assert "footer-logo" in classes[1], "an existing class is kept"
    assert imgs[0]["alt"] == "Databricks" and imgs[0]["style"] == "height:30px;width:auto"
    rule = re.search(rf"\.{re.escape(shared_class)}\{{([^}}]*)\}}", css).group(1)
    assert "background" in rule and "100% 100%" in rule and "no-repeat" in rule
    for img in imgs:
        placeholder = _decoded_svg(img["src"])
        # Same intrinsic size and shape as the logo, nothing drawn.
        assert 'width="713"' in placeholder and 'height="113"' in placeholder
        assert 'viewBox="0 0 713 113"' in placeholder
        assert "<path" not in placeholder
        assert len(img["src"]) < 200


def test_a_single_use_or_small_svg_is_left_inline():
    logo = preview_images.svg_data_uri(_LOGO_SVG)
    tiny = preview_images.svg_data_uri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
    htmls = [f'<img src="{logo}">', f'<img src="{tiny}">', f'<img src="{tiny}">']
    shared, css = preview_images.share_repeated_svg_images(htmls)
    assert shared == htmls
    assert css == ""


def test_shared_classes_are_distinct_per_svg_and_in_first_use_order():
    a = preview_images.svg_data_uri(_LOGO_SVG)
    b = preview_images.svg_data_uri(_LOGO_SVG.replace("#FF3621", "#1B3139"))
    htmls = [f'<img src="{b}"><img src="{a}">', f'<img src="{a}"><img src="{b}">']
    shared, css = preview_images.share_repeated_svg_images(htmls)
    page = "".join(shared) + css
    assert page.count(a) == 1 and page.count(b) == 1
    names = re.findall(r"\.(tellr-pv-img-\d+)\{", css)
    assert len(names) == 2 and len(set(names)) == 2
    first = BeautifulSoup(shared[0], "html.parser").find_all("img")
    assert names[0] in first[0]["class"], "b is seen first, so it gets the first class"


def test_svg_without_size_or_viewbox_keeps_its_percent_size():
    notice = preview_images.NOTICE_IMG_SRC  # sized 100% x 100%, no viewBox
    htmls = [f'<img src="{notice}" alt="x">'] * 3
    shared, css = preview_images.share_repeated_svg_images(htmls, min_bytes=64)
    placeholder = _decoded_svg(BeautifulSoup(shared[0], "html.parser").img["src"])
    assert 'width="100%"' in placeholder and 'height="100%"' in placeholder
    assert "<text" not in placeholder
    assert ("".join(shared) + css).count(notice) == 1


def test_unquoted_class_is_rewritten_validly():
    logo = preview_images.svg_data_uri(_LOGO_SVG)
    htmls = [f'<img class=brand src="{logo}">', f'<img src="{logo}" class=brand>']
    shared, _css = preview_images.share_repeated_svg_images(htmls)
    for html in shared:
        img = BeautifulSoup(html, "html.parser").img
        assert "brand" in img["class"]
        assert any(c.startswith("tellr-pv-img-") for c in img["class"])
        assert logo not in img["src"]


def test_a_logo_on_every_slide_is_sent_once_in_the_preview():
    logo_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="713" height="113" viewBox="0 0 713 113">'
        + "".join(f'<path fill="#FF3621" d="M{i} 0h4v4h-4z"/>' for i in range(200))
        + "</svg>"
    )
    logo_b64 = base64.b64encode(logo_svg.encode()).decode()
    deck = {
        "title": "Logo deck",
        "css": ".slide{color:#123}",
        "slides": [
            {
                "html": (
                    f'<div class="slide"><img alt="Databricks" '
                    f'src="data:image/svg+xml;base64,{logo_b64}" style="height:30px">'
                    f"<p>slide {i} text</p></div>"
                ),
                "slide_id": f"s{i}",
                "scripts": "",
            }
            for i in range(8)
        ],
    }
    preview = mcp_deck_preview.build_deck_preview(
        deck, title="Logo deck", deck_url=DECK_URL, svg_assets={}, max_html_bytes=UNLIMITED
    )
    assert preview.slides_shown == 8
    assert len(preview.html.encode()) < 2 * len(logo_svg) + 12_000, (
        "eight uses of one logo must cost about one copy, not eight"
    )
    assert "base64" not in preview.html
    soup = BeautifulSoup(preview.html, "html.parser")
    imgs = soup.find_all("img")
    assert len(imgs) == 8
    shared = {c for img in imgs for c in img.get("class") or [] if c.startswith("tellr-pv-img-")}
    assert len(shared) == 1
    styles = "".join(s.get_text() for s in soup.find_all("style"))
    assert f".{shared.pop()}{{" in styles
    assert preview.images_hidden == 0
