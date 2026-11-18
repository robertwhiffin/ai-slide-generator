"""Preview images: a notice for every raster, small SVGs inlined as percent-encoded text.

The MCP deck preview must never carry image bytes as base64, so
``src/utils/preview_images.py`` rewrites the image sources of slide HTML and deck CSS:

* ``{{image:T}}`` library handles are ALWAYS hidden (never looked up);
* ``{{ds-asset:N}}`` is inlined as ``svg_data_uri(svg_assets[N])`` when ``N`` is in the
  mapping, else hidden;
* a ``data:image/svg+xml;base64,...`` URI is decoded and inlined as text when the SVG is at
  most ``SVG_INLINE_MAX_BYTES``, else hidden;
* a text ``data:image/svg+xml[;params],...`` URI is kept when its percent-decoded payload is
  at most the cap, else hidden (C15);
* any other ``data:image/...`` URI is hidden; ``http(s):`` and relative URLs are untouched;
* an SVG whose text holds ``base64`` is hidden from every source (C16, R4);
* a hidden ``<img>`` ``src`` becomes ``NOTICE_IMG_SRC`` written double-quoted and its ``alt``
  becomes ``IMAGE_NOTICE``; a ``srcset`` holding ``data:`` or a handle is removed and not
  counted (C12, C14); a hidden CSS ``url(...)`` becomes ``none``;
* a final sweep hides leftover handles and base64 data URIs in any other context (C17, R3);
* everything outside the edited values comes back byte-for-byte (C13).

``design_system_service.get_small_svg_assets`` reads the small SVG assets of one design
system in one query, fail-closed on ``design_system_id=None`` and without a query when
there is nothing to read (C10).

Every oracle is written here. An inlined SVG is checked by decoding the produced value back
to the SVG text, not by looking for a prefix. HTML output is parsed only to inspect it.
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import quote, unquote

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from src.services import design_system_service

# Imported through the existing ``src.utils`` package so the import order is the same
# before and after the module exists (ruff files a missing module as third-party).
from src.utils import preview_images

IMAGE_NOTICE = preview_images.IMAGE_NOTICE
NOTICE_IMG_SRC = preview_images.NOTICE_IMG_SRC
SVG_INLINE_MAX_BYTES = preview_images.SVG_INLINE_MAX_BYTES
hide_images_in_css = preview_images.hide_images_in_css
hide_images_in_html = preview_images.hide_images_in_html
svg_data_uri = preview_images.svg_data_uri

SVG_NS = "http://www.w3.org/2000/svg"
TEXT_SVG_PREFIX = "data:image/svg+xml,"
CAP = 10_240

# The cleaned form of the brief's ds-asset SVG (prolog and comment gone).
DS_SVG_RAW = (
    '<?xml version="1.0"?><!-- c --><svg xmlns="http://www.w3.org/2000/svg">'
    '<path fill="#FF3621" d="M0 0"/></svg>'
)
DS_SVG_CLEAN = '<svg xmlns="http://www.w3.org/2000/svg"><path fill="#FF3621" d="M0 0"/></svg>'

# A percent-encoded text SVG URI: raw characters other than these, or a '%' that does not
# start an escape, would break the URI inside an HTML attribute or a CSS string.
_STRICTLY_ENCODED = re.compile(r"data:image/svg\+xml,(?:[^%#\"'<>\t\n\r\f\v]|%[0-9A-Fa-f]{2})*")
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)")


# ---------------------------------------------------------------------------
# Helpers (test-side only)
# ---------------------------------------------------------------------------


def _svg_of_size(n: int, inner: str = "", pad_char: str = "a") -> str:
    """An SVG of exactly ``n`` UTF-8 bytes with no prolog, comment or inter-tag whitespace.

    Cleaning leaves it unchanged, so its size before and after cleaning is the same.
    """
    head = '<svg xmlns="http://www.w3.org/2000/svg">' + inner + "<desc>"
    tail = "</desc></svg>"
    pad = n - len(head.encode()) - len(tail.encode())
    assert pad >= 0
    svg = head + pad_char * pad + tail
    assert len(svg.encode()) == n
    return svg


def _b64_svg_uri(svg: str, prefix: str = "data:image/svg+xml;base64,") -> str:
    return prefix + base64.b64encode(svg.encode()).decode()


def _text_svg_uri(svg: str, prefix: str = TEXT_SVG_PREFIX) -> str:
    return prefix + quote(svg, safe="")


def _assert_inlined_text_svg(value: str, expected_svg: str) -> None:
    """``value`` is ``svg_data_uri``-shaped and decodes to exactly ``expected_svg``."""
    assert value.startswith(TEXT_SVG_PREFIX), value[:60]
    assert ";base64" not in value.lower()
    for ch in "#\"'<>":
        assert ch not in value, f"raw {ch!r} left in {value[:80]!r}"
    assert _STRICTLY_ENCODED.fullmatch(value), value[:120]
    assert unquote(value[len(TEXT_SVG_PREFIX) :]) == expected_svg


def _assert_kept_text_svg(value: str, expected_svg: str) -> None:
    """A text SVG URI, kept verbatim or re-encoded, still carrying ``expected_svg``."""
    media, sep, payload = value.partition(",")
    assert sep == ","
    assert media.lower().startswith("data:image/svg+xml")
    assert "base64" not in value.lower()
    assert unquote(payload) == expected_svg


class _StartTags(HTMLParser):
    """Every start tag with its attributes as written (duplicates included)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, list[tuple[str, str | None]]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, list(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, list(attrs)))


def _tags(html: str, name: str) -> list[list[tuple[str, str | None]]]:
    parser = _StartTags()
    parser.feed(html)
    parser.close()
    return [attrs for tag, attrs in parser.tags if tag == name]


def _attr_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
    names = [name for name, _ in attrs]
    assert len(names) == len(set(names)), f"duplicate attribute in {attrs!r}"
    return dict(attrs)


def _assert_notice_img(attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
    d = _attr_dict(attrs)
    assert d.get("src") == NOTICE_IMG_SRC
    assert d.get("alt") == IMAGE_NOTICE
    return d


def _css_url_values(css: str) -> list[str]:
    return [m.group(2) for m in _CSS_URL.finditer(css)]


# ---------------------------------------------------------------------------
# SQLite fixture (copied from tests/unit/test_mcp_server.py per C18)
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_asset_session():
    """Real in-memory persistence for synthetic MCP design-system assets."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _make_synthetic_design_system(session, name, assets):
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    design_system = DesignSystem(name=name)
    for filename, mime, data, kind in assets:
        design_system.assets.append(
            DesignSystemAsset(
                kind=kind,
                filename=filename,
                mime=mime,
                data=data,
                size_bytes=len(data),
            )
        )
    session.add(design_system)
    session.commit()
    session.refresh(design_system)
    return design_system


@pytest.fixture
def unseeded_session():
    """A SQLite session with NO tables: any query against it raises (C10)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with Session(engine) as session:
        yield session
    engine.dispose()


class _StatementLog:
    """Records every SQL statement the engine sends while installed."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._record)
        return False

    @property
    def selects(self) -> list[str]:
        return [s for s in self.statements if s.lstrip().upper().startswith("SELECT")]


# ---------------------------------------------------------------------------
# Constants, svg_data_uri, NOTICE_IMG_SRC
# ---------------------------------------------------------------------------


def test_notice_copy_and_inline_cap_constants():
    assert IMAGE_NOTICE == "image not shown in preview, see full deck in tellr"
    assert SVG_INLINE_MAX_BYTES == 10_240


def test_svg_data_uri_strips_prolog_and_comments_and_encodes_specials():
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Generator: x -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%">\n'
        "  <!-- inner -->\n"
        '  <path fill="#FF3621" d="M0 0"/>\n'
        "  <text font-family=\"'DM Sans'\">café &lt; 1</text>\n"
        "</svg>\n"
    )
    expected_tight = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%">'
        '<path fill="#FF3621" d="M0 0"/>'
        "<text font-family=\"'DM Sans'\">café &lt; 1</text>"
        "</svg>"
    )

    uri = svg_data_uri(svg)

    assert uri.startswith(TEXT_SVG_PREFIX)
    assert ";base64" not in uri.lower()
    for ch in "#\"'<>":
        assert ch not in uri
    assert _STRICTLY_ENCODED.fullmatch(uri), uri
    assert "%23FF3621" in uri
    assert "100%25" in uri
    decoded = unquote(uri[len(TEXT_SVG_PREFIX) :])
    assert "<?xml" not in decoded
    assert "<!--" not in decoded and "Generator" not in decoded and "inner" not in decoded
    # leading/trailing whitespace around the root is harmless and not pinned
    assert "\n" not in decoded.strip()
    assert re.search(r">\s{2,}<", decoded) is None
    # whitespace between tags is collapsed; whether to nothing or one space is not pinned
    assert re.sub(r">\s+<", "><", decoded.strip()) == expected_tight


def test_svg_data_uri_of_the_brief_svg_decodes_to_the_cleaned_text():
    uri = svg_data_uri(DS_SVG_RAW)
    _assert_inlined_text_svg(uri, DS_SVG_CLEAN)


def test_notice_img_src_is_a_small_text_svg_drawing_the_notice():
    assert NOTICE_IMG_SRC.startswith(TEXT_SVG_PREFIX)
    assert "base64" not in NOTICE_IMG_SRC.lower()
    assert len(NOTICE_IMG_SRC.encode("utf-8")) < 600
    for ch in "#\"'<>":
        assert ch not in NOTICE_IMG_SRC
    assert _STRICTLY_ENCODED.fullmatch(NOTICE_IMG_SRC)

    decoded = unquote(NOTICE_IMG_SRC[len(TEXT_SVG_PREFIX) :])
    root = ET.fromstring(decoded)
    # an <img> renders an SVG data URI only when the root is in the SVG namespace
    assert root.tag == "{" + SVG_NS + "}svg"
    assert IMAGE_NOTICE in "".join(root.itertext())
    assert "#eef0f2" in decoded.lower()
    assert "#c8cdd2" in decoded.lower()


# ---------------------------------------------------------------------------
# hide_images_in_html — <img> src rules (brief Step 1)
# ---------------------------------------------------------------------------


def test_raster_handles_and_data_uris_become_the_notice():
    html = (
        '<img src="{{image:abc}}">'
        '<img src="data:image/png;base64,iVBORw0KGgo=">'
        '<img src="{{ds-asset:9}}">'
    )

    out, hidden = hide_images_in_html(html, {4: DS_SVG_RAW})

    assert hidden == 3
    assert "base64" not in out
    assert "{{" not in out
    assert out.count(NOTICE_IMG_SRC) == 3
    assert 'alt="image not shown in preview, see full deck in tellr"' in out
    assert out.count('alt="' + IMAGE_NOTICE + '"') == 3
    assert out.count('src="' + NOTICE_IMG_SRC + '"') == 3
    imgs = _tags(out, "img")
    assert len(imgs) == 3
    for attrs in imgs:
        assert _assert_notice_img(attrs).keys() == {"src", "alt"}


def test_small_ds_svg_is_inlined_as_text():
    html = '<img src="{{ds-asset:4}}">'

    out, hidden = hide_images_in_html(html, {4: DS_SVG_RAW})

    assert hidden == 0
    assert "data:image/svg+xml," in out
    assert "%23FF3621" in out
    assert "<?xml" not in out
    assert "<!--" not in out
    imgs = _tags(out, "img")
    assert len(imgs) == 1
    attrs = _attr_dict(imgs[0])
    # a shown image keeps its own alt (here none): the notice alt is only for hidden ones
    assert list(attrs) == ["src"]
    src = attrs["src"]
    assert "#FF3621" not in src
    _assert_inlined_text_svg(src, DS_SVG_CLEAN)
    assert out == '<img src="' + svg_data_uri(DS_SVG_RAW) + '">'


def test_base64_svg_data_uri_inlined_or_hidden_by_size():
    small = _svg_of_size(200, '<rect fill="#FF3621" width="10" height="10"/>')
    out, hidden = hide_images_in_html('<img src="' + _b64_svg_uri(small) + '">', {})
    assert hidden == 0
    assert "base64" not in out
    imgs = _tags(out, "img")
    assert len(imgs) == 1
    _assert_inlined_text_svg(_attr_dict(imgs[0])["src"], small)

    big = _svg_of_size(20 * 1024)
    out, hidden = hide_images_in_html('<img src="' + _b64_svg_uri(big) + '">', {})
    assert hidden == 1
    assert "base64" not in out
    assert "a" * 100 not in out
    imgs = _tags(out, "img")
    assert len(imgs) == 1
    _assert_notice_img(imgs[0])

    # C16: a small SVG that wraps an embedded raster is hidden, not inlined
    wraps_raster = _svg_of_size(300, '<image href="data:image/png;base64,AAAA"/>')
    out, hidden = hide_images_in_html('<img src="' + _b64_svg_uri(wraps_raster) + '">', {})
    assert hidden == 1
    assert "base64" not in out.lower()
    assert "AAAA" not in out
    imgs = _tags(out, "img")
    assert len(imgs) == 1
    _assert_notice_img(imgs[0])


def test_img_src_quote_forms_and_srcset():
    html = (
        "<img src='{{image:a}}'>"
        "<img src={{image:b}} alt=x>"
        '<img src="https://e.com/p.png" srcset="data:image/png;base64,AAAA 2x">'
    )

    out, hidden = hide_images_in_html(html, {})

    assert hidden == 2  # C14: removing the srcset is not counted
    assert "base64" not in out
    assert "srcset" not in out
    assert out.count('src="' + NOTICE_IMG_SRC + '"') == 2  # C12: always double-quoted
    imgs = _tags(out, "img")
    assert len(imgs) == 3
    assert _assert_notice_img(imgs[0]).keys() == {"src", "alt"}
    assert _assert_notice_img(imgs[1]).keys() == {"src", "alt"}  # alt=x replaced, not doubled
    assert imgs[2] == [("src", "https://e.com/p.png")]
    assert '<img src="https://e.com/p.png"' in out


def test_img_tag_matching_is_quote_aware_and_alt_is_replaced_or_added():
    """C12: a raw '>' inside a quoted src does not end the tag; alt in any quote form."""
    small_text_svg = "<svg xmlns='http://www.w3.org/2000/svg'><rect width='1' height='1'/></svg>"
    big_text_svg = "<svg xmlns='http://www.w3.org/2000/svg'><desc>" + "a" * CAP + "</desc></svg>"
    html = (
        '<img src="data:image/svg+xml,' + small_text_svg + '" '
        'srcset="data:image/png;base64,AAAA 2x" alt="logo">'
        '<img src="data:image/svg+xml,' + big_text_svg + '" alt="big">'
        "<img src={{image:b}} alt=x>"
        "<img alt='old' class=pic src='{{image:c}}'>"
        '<img src="{{image:d}}" width="40">'
    )

    out, hidden = hide_images_in_html(html, {})

    assert hidden == 4
    assert "base64" not in out
    assert "{{" not in out
    assert "a" * 100 not in out
    assert out.count('src="' + NOTICE_IMG_SRC + '"') == 4
    imgs = _tags(out, "img")
    assert len(imgs) == 5

    kept = _attr_dict(imgs[0])
    assert set(kept) == {"src", "alt"}  # srcset removed, nothing added
    assert kept["alt"] == "logo"
    _assert_kept_text_svg(kept["src"], small_text_svg)

    assert _assert_notice_img(imgs[1]).keys() == {"src", "alt"}
    assert _assert_notice_img(imgs[2]).keys() == {"src", "alt"}
    third = _assert_notice_img(imgs[3])
    assert third.keys() == {"src", "alt", "class"} and third["class"] == "pic"
    fourth = _assert_notice_img(imgs[4])
    assert fourth.keys() == {"src", "alt", "width"} and fourth["width"] == "40"
    assert "class=pic" in out
    assert 'width="40"' in out


def test_image_handle_is_never_resolved_from_svg_assets():
    """{{image:…}} and {{ds-asset:…}} are distinct namespaces; image handles always hide."""
    out, hidden = hide_images_in_html('<img src="{{image:4}}">', {4: DS_SVG_RAW})

    assert hidden == 1
    imgs = _tags(out, "img")
    assert len(imgs) == 1
    _assert_notice_img(imgs[0])
    assert "%23FF3621" not in out


def test_srcset_removal_is_not_counted_and_plain_srcsets_stay():
    plain = (
        '<img src="https://e.com/b.png" srcset="https://e.com/b.png 1x, https://e.com/b2.png 2x">'
    )
    html = (
        '<img src="https://e.com/a.png" srcset="{{image:x}} 2x">'
        + plain
        + '<img src="{{image:y}}" srcset="data:image/webp;base64,AAAA 2x, {{ds-asset:4}} 3x">'
    )

    out, hidden = hide_images_in_html(html, {4: DS_SVG_RAW})

    assert hidden == 1
    assert "base64" not in out
    assert "{{" not in out
    assert plain in out
    imgs = _tags(out, "img")
    assert len(imgs) == 3
    assert imgs[0] == [("src", "https://e.com/a.png")]
    assert _attr_dict(imgs[1]) == {
        "src": "https://e.com/b.png",
        "srcset": "https://e.com/b.png 1x, https://e.com/b2.png 2x",
    }
    assert _assert_notice_img(imgs[2]).keys() == {"src", "alt"}


def test_svg_uri_parameters_and_case_insensitive_matching():
    """C15: ;utf8 / ;charset=… are text SVG URIs; matching is case-insensitive."""
    small = _svg_of_size(200, '<rect width="10" height="10"/>')
    over = _svg_of_size(CAP + 1, pad_char="z")
    html = (
        '<img src="' + _text_svg_uri(small, "data:image/svg+xml;utf8,") + '">'
        '<img src="' + _text_svg_uri(small, "data:image/svg+xml;charset=utf-8,") + '">'
        '<img src="DATA:IMAGE/PNG;BASE64,iVBORw0KGgo=">'
        '<img src="' + _b64_svg_uri(small, "DATA:IMAGE/SVG+XML;BASE64,") + '">'
        '<img src="' + _text_svg_uri(over, "data:image/svg+xml;utf8,") + '">'
    )

    out, hidden = hide_images_in_html(html, {})

    assert hidden == 2
    assert "base64" not in out.lower()
    assert "z" * 100 not in out  # the over-cap SVG is gone
    imgs = _tags(out, "img")
    assert len(imgs) == 5
    _assert_kept_text_svg(_attr_dict(imgs[0])["src"], small)
    _assert_kept_text_svg(_attr_dict(imgs[1])["src"], small)
    _assert_notice_img(imgs[2])
    _assert_inlined_text_svg(_attr_dict(imgs[3])["src"], small)
    _assert_notice_img(imgs[4])
    for attrs in (imgs[0], imgs[1], imgs[3]):
        assert list(_attr_dict(attrs)) == ["src"]

    css = (
        ".a{background:url(DATA:IMAGE/JPEG;BASE64,/9j/)}"
        '.b{background:url("' + _text_svg_uri(small, "data:image/svg+xml;utf8,") + '")}'
    )
    out_css, hidden_css = hide_images_in_css(css, {})
    assert hidden_css == 1
    assert out_css.startswith(".a{background:none}.b{background:url(")
    assert "base64" not in out_css.lower()
    values = _css_url_values(out_css)
    assert len(values) == 1
    _assert_kept_text_svg(values[0], small)


@pytest.mark.parametrize(
    "size, encoding, expect_hidden",
    [
        (CAP, "base64", 0),
        (CAP + 1, "base64", 1),
        (CAP, "text", 0),
        (CAP + 1, "text", 1),
    ],
)
def test_svg_inline_cap_boundary_in_img_and_css(size, encoding, expect_hidden):
    """At exactly SVG_INLINE_MAX_BYTES decoded bytes an SVG shows; one byte more hides it.

    For the text rule the size is the percent-decoded payload (C15), so the encoded URI
    here is longer than the cap even when the SVG is exactly at it.
    """
    svg = _svg_of_size(size)
    uri = _b64_svg_uri(svg) if encoding == "base64" else _text_svg_uri(svg)
    if encoding == "text" and size == CAP:
        assert len(uri) - len(TEXT_SVG_PREFIX) > CAP

    out, hidden = hide_images_in_html('<img src="' + uri + '">', {})
    assert hidden == expect_hidden
    assert "base64" not in out.lower()
    imgs = _tags(out, "img")
    assert len(imgs) == 1
    if expect_hidden:
        _assert_notice_img(imgs[0])
        assert "a" * 100 not in out
    elif encoding == "base64":
        _assert_inlined_text_svg(_attr_dict(imgs[0])["src"], svg)
    else:
        _assert_kept_text_svg(_attr_dict(imgs[0])["src"], svg)

    out_css, hidden_css = hide_images_in_css('.a{background:url("' + uri + '")}', {})
    assert hidden_css == expect_hidden
    assert "base64" not in out_css.lower()
    if expect_hidden:
        assert out_css == ".a{background:none}"
    else:
        values = _css_url_values(out_css)
        assert len(values) == 1
        if encoding == "base64":
            _assert_inlined_text_svg(values[0], svg)
        else:
            _assert_kept_text_svg(values[0], svg)


def test_svg_that_embeds_base64_is_hidden_from_every_source():
    """C16 / R4: ds-asset, base64 URI and text URI SVGs holding 'base64' all hide."""
    wraps_raster = _svg_of_size(300, '<image href="data:image/png;base64,AAAA"/>')
    ds_upper = wraps_raster.replace("base64", "BASE64")
    html = (
        '<img src="{{ds-asset:5}}">'
        '<img src="' + _b64_svg_uri(wraps_raster) + '">'
        '<img src="' + _text_svg_uri(wraps_raster) + '">'
    )

    out, hidden = hide_images_in_html(html, {5: ds_upper})

    assert hidden == 3
    assert "base64" not in out.lower()
    assert "AAAA" not in out
    imgs = _tags(out, "img")
    assert len(imgs) == 3
    for attrs in imgs:
        _assert_notice_img(attrs)

    out_css, hidden_css = hide_images_in_css(".l{background:url({{ds-asset:5}})}", {5: ds_upper})
    assert (out_css, hidden_css) == (".l{background:none}", 1)


# ---------------------------------------------------------------------------
# CSS url(...) rules
# ---------------------------------------------------------------------------


def test_css_urls_hidden_become_none_and_svgs_inline():
    out, hidden = hide_images_in_css(".h{background:#fff url({{image:z}}) no-repeat}", {})
    assert out == ".h{background:#fff none no-repeat}"
    assert hidden == 1

    out, hidden = hide_images_in_css(".l{background-image:url('{{ds-asset:4}}')}", {4: DS_SVG_RAW})
    assert hidden == 0
    assert out == '.l{background-image:url("' + svg_data_uri(DS_SVG_RAW) + '")}'
    values = _css_url_values(out)
    assert len(values) == 1
    _assert_inlined_text_svg(values[0], DS_SVG_CLEAN)


def test_css_every_url_form_is_resolved_and_counted():
    css = (
        ".u{background:url({{ds-asset:4}})}"
        ".m{background:url({{image:a}}), url( data:image/png;base64,AAAA ), url('x.png')}"
        '.n{background:url("{{ds-asset:9}}") center}'
    )

    out, hidden = hide_images_in_css(css, {4: DS_SVG_RAW})

    assert hidden == 3
    assert out == (
        '.u{background:url("' + svg_data_uri(DS_SVG_RAW) + '")}'
        ".m{background:none, none, url('x.png')}"
        ".n{background:none center}"
    )
    _assert_inlined_text_svg(_css_url_values(out)[0], DS_SVG_CLEAN)


def test_css_edit_leaves_everything_else_byte_for_byte():
    css = (
        "/* brand */\n:root{ --c : #FF3621 }\n"
        '.h  {  background : #fff url( "{{image:z}}" )  no-repeat ; }\n'
        ".k{color:red}\n@media (min-width:1px){ .b { color : blue } }\n"
    )

    out, hidden = hide_images_in_css(css, {})

    assert hidden == 1
    assert out == (
        "/* brand */\n:root{ --c : #FF3621 }\n"
        ".h  {  background : #fff none  no-repeat ; }\n"
        ".k{color:red}\n@media (min-width:1px){ .b { color : blue } }\n"
    )


def test_css_without_images_comes_back_byte_for_byte():
    css = (
        "/* brand */\n:root{ --c : #FF3621 }\n"
        ".a  { background : url( 'https://e.com/a.png' ) ; }\n"
        '.b{background:url("../img/bg.svg") no-repeat}.c{background:url(//cdn.e.com/x.jpg)}\n'
        "@media (min-width:1px){ .d { color : blue } }\n"
    )

    assert hide_images_in_css(css, {4: DS_SVG_RAW}) == (css, 0)


def test_leftover_handles_and_base64_in_css_strings_are_hidden():
    """C17 in CSS: a handle or base64 URI outside url(...) is still hidden and counted."""
    css = '.a{background-image:image-set("data:image/png;base64,AAAA" 1x)}.b{--i:"{{image:q}}"}'

    out, hidden = hide_images_in_css(css, {})

    assert hidden == 2
    assert "base64" not in out.lower()
    assert "{{" not in out
    # the hidden run becomes none; whether the surrounding quotes go with it is not pinned
    assert re.sub(r'"?none"?', "X", out) == ".a{background-image:image-set(X 1x)}.b{--i:X}"


# ---------------------------------------------------------------------------
# hide_images_in_html — CSS inside HTML
# ---------------------------------------------------------------------------


def test_inline_style_background_in_html_is_hidden():
    html = '<div style="background-image:url(data:image/jpeg;base64,/9j/)">'

    out, hidden = hide_images_in_html(html, {})

    assert hidden == 1
    assert out == '<div style="background-image:none">'


def test_inline_style_svg_url_keeps_the_attribute_intact():
    html = "<div style=\"background:url('{{ds-asset:4}}')\">x</div>"

    out, hidden = hide_images_in_html(html, {4: DS_SVG_RAW})

    assert hidden == 0
    soup = BeautifulSoup(out, "html.parser")
    divs = soup.find_all("div")
    assert len(divs) == 1
    style = divs[0]["style"]
    assert "data:image/svg+xml," in style
    assert divs[0].get_text() == "x"
    # R2: the url keeps its original quote character
    assert style == "background:url('" + svg_data_uri(DS_SVG_RAW) + "')"
    values = _css_url_values(style)
    assert len(values) == 1
    _assert_inlined_text_svg(values[0], DS_SVG_CLEAN)


def test_inline_style_svg_url_quote_follows_the_original():
    """R2: unquoted url(...) in the HTML pass becomes url('…'); a "…" url stays "…"."""
    uri = svg_data_uri(DS_SVG_RAW)
    html = (
        '<div style="background:url({{ds-asset:4}}) no-repeat">x</div>'
        "<p style='background:url(\"{{ds-asset:4}}\")'>y</p>"
        "<style>.l{background:url({{ds-asset:4}})}</style>"
    )

    out, hidden = hide_images_in_html(html, {4: DS_SVG_RAW})

    assert hidden == 0
    assert "{{" not in out
    soup = BeautifulSoup(out, "html.parser")
    divs, ps, styles = soup.find_all("div"), soup.find_all("p"), soup.find_all("style")
    assert len(divs) == 1 and len(ps) == 1 and len(styles) == 1
    assert divs[0]["style"] == "background:url('" + uri + "') no-repeat"
    assert divs[0].get_text() == "x"
    assert ps[0]["style"] == 'background:url("' + uri + '")'
    assert ps[0].get_text() == "y"
    values = _css_url_values(styles[0].get_text())
    assert len(values) == 1
    _assert_inlined_text_svg(values[0], DS_SVG_CLEAN)


def test_style_block_inside_html_is_covered():
    html = "<style>.b{background:#000 url({{image:z}}) no-repeat}</style><div class='b'>x</div>"

    out, hidden = hide_images_in_html(html, {})

    assert hidden == 1
    assert out == "<style>.b{background:#000 none no-repeat}</style><div class='b'>x</div>"


# ---------------------------------------------------------------------------
# hide_images_in_html — final sweep (C17) and byte-for-byte (C13)
# ---------------------------------------------------------------------------


def test_leftover_handles_and_base64_in_other_attributes_are_hidden():
    html = '<svg><image href="data:image/png;base64,AAAA"/></svg><video poster="{{image:p}}">'

    out, hidden = hide_images_in_html(html, {})

    assert "base64" not in out
    assert "{{" not in out
    assert hidden == 2
    assert out == (
        '<svg><image href="' + NOTICE_IMG_SRC + '"/></svg><video poster="' + NOTICE_IMG_SRC + '">'
    )


def test_leftover_scoped_ds_asset_outside_img_is_inlined():
    html = '<svg><image href="{{ds-asset:4}}"/></svg>'

    out, hidden = hide_images_in_html(html, {4: DS_SVG_RAW})

    assert hidden == 0
    assert out == '<svg><image href="' + svg_data_uri(DS_SVG_RAW) + '"/></svg>'
    images = _tags(out, "image")
    assert len(images) == 1
    _assert_inlined_text_svg(_attr_dict(images[0])["href"], DS_SVG_CLEAN)


def test_entity_quoted_url_in_style_attribute_is_hidden():
    html = '<div style="background:url(&quot;{{image:q}}&quot;)">x</div>'

    out, hidden = hide_images_in_html(html, {})

    assert hidden == 1
    assert "{{" not in out
    soup = BeautifulSoup(out, "html.parser")
    divs = soup.find_all("div")
    assert len(divs) == 1
    assert divs[0].get_text() == "x"
    assert divs[0]["style"].startswith("background:")


def test_html_without_images_comes_back_byte_for_byte():
    html = (
        "<div class='slide'  data-n=1>\n"
        "  <!-- speaker note -->\n"
        "  <h1 style='color:#FF3621'>Q3   results &amp; more</h1>\n"
        '  <svg viewBox="0 0 10 10"><path fill="#fff" d="M0 0h10v10z"/></svg>\n'
        "  <p>A\tB</p>\n"
        "</div>"
    )

    assert hide_images_in_html(html, {4: DS_SVG_RAW}) == (html, 0)


def test_html_edit_leaves_everything_outside_the_edited_values_untouched():
    prefix = (
        "<div class='slide'  data-n=1>\n  <!-- c -->\n"
        "  <h1 style='color:#FF3621'>T &amp; x</h1>\n  "
    )
    img = "<img class='logo'   width=40 src='{{image:a}}' data-x=\"1\">"
    middle = "\n  <p>  spaced\ttext </p>\n  "
    div = '<div style="color:#fff;  background:#000 url({{image:z}}) no-repeat">y</div>'
    suffix = "\n</div>\n"

    out, hidden = hide_images_in_html(prefix + img + middle + div + suffix, {})

    assert hidden == 2
    assert out.startswith(prefix)
    tail = middle + '<div style="color:#fff;  background:#000 none no-repeat">y</div>' + suffix
    assert out.endswith(tail)
    new_img = out[len(prefix) : len(out) - len(tail)]
    assert new_img.startswith("<img") and new_img.endswith(">")
    for verbatim in ("class='logo'", "width=40", 'data-x="1"', 'src="' + NOTICE_IMG_SRC + '"'):
        assert verbatim in new_img
    imgs = _tags(new_img, "img")
    assert len(imgs) == 1
    attrs = _assert_notice_img(imgs[0])
    assert attrs.keys() == {"class", "width", "src", "data-x", "alt"}


def test_http_and_relative_urls_are_untouched():
    html = (
        '<img src="https://e.com/a.png" alt="a">'
        "<img src='http://e.com/b.jpg'>"
        "<img src=/static/logo.svg>"
        '<img src="img/c.png" srcset="img/c.png 1x, img/c2.png 2x">'
        '<div style="background:url(https://e.com/bg.jpg)">x</div>'
    )
    css = ".a{background:url(https://e.com/a.png)}.b{background:url('../b.svg')}"

    assert hide_images_in_html(html, {4: DS_SVG_RAW}) == (html, 0)
    assert hide_images_in_css(css, {4: DS_SVG_RAW}) == (css, 0)


# ---------------------------------------------------------------------------
# design_system_service.get_small_svg_assets
# ---------------------------------------------------------------------------

_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_get_small_svg_assets_filters_scope_mime_and_size(mcp_asset_session):
    small_svg = _svg_of_size(100, '<path fill="#FF3621" d="M0 0"/>')
    big_svg = _svg_of_size(20 * 1024)
    b_svg = _svg_of_size(120, '<circle r="1"/>')
    unrequested_svg = _svg_of_size(110, '<rect width="2"/>')
    ds_a = _make_synthetic_design_system(
        mcp_asset_session,
        "A",
        [
            ("logo.svg", "image/svg+xml", small_svg.encode(), "logo"),
            ("big.svg", "image/svg+xml", big_svg.encode(), "illustration"),
            ("photo.png", "image/png", _PNG_BYTES, "background"),
            ("brand.ttf", "font/ttf", b"\x00\x01\x00\x00" + b"\x00" * 60, "font"),
            ("bad.svg", "image/svg+xml", b"\xff\xfe<\x00s\x00v\x00g\x00/\x00>\x00", "icon"),
            ("unrequested.svg", "image/svg+xml", unrequested_svg.encode(), "icon"),
        ],
    )
    ds_b = _make_synthetic_design_system(
        mcp_asset_session, "B", [("b.svg", "image/svg+xml", b_svg.encode(), "logo")]
    )
    a_ids = {asset.filename: asset.id for asset in ds_a.assets}
    b_id = ds_b.assets[0].id
    ds_a_id, ds_b_id = ds_a.id, ds_b.id
    requested = {
        a_ids["logo.svg"],
        a_ids["big.svg"],
        a_ids["photo.png"],
        a_ids["brand.ttf"],
        a_ids["bad.svg"],
        b_id,
        999_999,
    }

    with _StatementLog(mcp_asset_session.get_bind()) as log:
        for_a = design_system_service.get_small_svg_assets(
            mcp_asset_session,
            requested,
            design_system_id=ds_a_id,
            max_bytes=SVG_INLINE_MAX_BYTES,
        )
    assert for_a == {a_ids["logo.svg"]: small_svg}
    assert len(log.selects) == 1  # one query for every id

    for_b = design_system_service.get_small_svg_assets(
        mcp_asset_session,
        requested,
        design_system_id=ds_b_id,
        max_bytes=SVG_INLINE_MAX_BYTES,
    )
    assert for_b == {b_id: b_svg}

    assert (
        design_system_service.get_small_svg_assets(
            mcp_asset_session,
            requested,
            design_system_id=None,
            max_bytes=SVG_INLINE_MAX_BYTES,
        )
        == {}
    )


def test_get_small_svg_assets_size_cap_is_inclusive_and_taken_from_max_bytes(
    mcp_asset_session,
):
    at_cap = _svg_of_size(CAP)
    over_cap = _svg_of_size(CAP + 1)
    hundred = _svg_of_size(100)
    ds = _make_synthetic_design_system(
        mcp_asset_session,
        "A",
        [
            ("at.svg", "image/svg+xml", at_cap.encode(), "logo"),
            ("over.svg", "image/svg+xml", over_cap.encode(), "logo"),
            ("hundred.svg", "image/svg+xml", hundred.encode(), "icon"),
        ],
    )
    ids = {asset.filename: asset.id for asset in ds.assets}
    ds_id = ds.id
    every = list(ids.values())

    assert design_system_service.get_small_svg_assets(
        mcp_asset_session, every, design_system_id=ds_id, max_bytes=CAP
    ) == {ids["at.svg"]: at_cap, ids["hundred.svg"]: hundred}
    assert design_system_service.get_small_svg_assets(
        mcp_asset_session, every, design_system_id=ds_id, max_bytes=100
    ) == {ids["hundred.svg"]: hundred}
    assert (
        design_system_service.get_small_svg_assets(
            mcp_asset_session, every, design_system_id=ds_id, max_bytes=99
        )
        == {}
    )


def test_get_small_svg_assets_returns_empty_without_a_query(unseeded_session):
    """C10: no ids, or no design system, returns {} without touching the database."""
    from src.database.models.design_system import DesignSystemAsset

    # the fixture is a database with no tables: a real query here raises
    with pytest.raises(OperationalError):
        unseeded_session.query(DesignSystemAsset).all()
    unseeded_session.rollback()

    with _StatementLog(unseeded_session.get_bind()) as log:
        assert (
            design_system_service.get_small_svg_assets(
                unseeded_session, [], design_system_id=1, max_bytes=CAP
            )
            == {}
        )
        assert (
            design_system_service.get_small_svg_assets(
                unseeded_session, set(), design_system_id=1, max_bytes=CAP
            )
            == {}
        )
        assert (
            design_system_service.get_small_svg_assets(
                unseeded_session, [1, 2, 3], design_system_id=None, max_bytes=CAP
            )
            == {}
        )
    assert log.statements == []
