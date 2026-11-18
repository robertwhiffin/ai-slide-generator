"""Image handling for the MCP deck preview: a notice for rasters, small SVGs as text.

The preview carries no image bytes and no base64. :func:`hide_images_in_html` and
:func:`hide_images_in_css` rewrite every image source they find with one set of rules
(:func:`_resolve_source`):

* ``{{image:T}}`` library handles are always hidden (never looked up);
* ``{{ds-asset:N}}`` is inlined as percent-encoded SVG text when ``N`` is in the supplied
  small-SVG mapping, else hidden;
* a ``data:image/svg+xml`` URI is inlined (base64) or kept (text) when its SVG is at most
  ``SVG_INLINE_MAX_BYTES``, else hidden; an SVG whose text holds ``base64`` is always hidden;
* any other ``data:image/...`` URI, or any ``;base64`` data URI, is hidden;
* ``http(s):`` and relative URLs are left alone.

Only the edited values change; everything else comes back byte-for-byte, so the text is
never parsed and re-serialised.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from typing import Optional
from urllib.parse import quote, unquote_to_bytes

from src.utils.ds_asset_utils import DS_ASSET_PLACEHOLDER_PATTERN
from src.utils.image_utils import IMAGE_PLACEHOLDER_PATTERN

IMAGE_NOTICE = "image not shown in preview, see full deck in tellr"
SVG_INLINE_MAX_BYTES = 10_240

_SVG_URI_PREFIX = "data:image/svg+xml,"
_SVG_SAFE_CHARS = " =:/;,.-_()!*~"
_XML_PROLOG = re.compile(r"<\?xml.*?\?>", re.DOTALL)
_XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BETWEEN_TAGS = re.compile(r">\s+<")


def svg_data_uri(svg_text: str) -> str:
    """A ``data:image/svg+xml,`` URI of *svg_text*, percent-encoded (never base64).

    The XML prolog and comments are removed and whitespace between tags collapses to a
    single space. ``# % " ' < >`` and ``&`` are always encoded, so the value is safe inside
    an HTML attribute, a CSS string or a ``url()`` in either quote style.
    """
    text = _XML_COMMENT.sub("", _XML_PROLOG.sub("", svg_text))
    text = _BETWEEN_TAGS.sub("> <", text).strip()
    return _SVG_URI_PREFIX + quote(text, safe=_SVG_SAFE_CHARS)


_NOTICE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">'
    '<rect width="100%" height="100%" fill="#EEF0F2" stroke="#C8CDD2" stroke-width="2"/>'
    '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" '
    'font-family="sans-serif" font-size="12" fill="#5F6B76">'
    f"{IMAGE_NOTICE}</text></svg>"
)
NOTICE_IMG_SRC = svg_data_uri(_NOTICE_SVG)

# ---------------------------------------------------------------------------
# Source-value rules (shared by the HTML and CSS passes)
# ---------------------------------------------------------------------------

_HIDE = object()  # sentinel: this source is hidden
_DATA_URI = re.compile(r"data:([^;,]*)((?:;[^;,]*)*),(.*)", re.DOTALL | re.IGNORECASE)


def _svg_text_result(svg_bytes: bytes) -> object:
    """Inline a small SVG's text, or hide it (too big, or it embeds base64)."""
    if len(svg_bytes) > SVG_INLINE_MAX_BYTES:
        return _HIDE
    text = svg_bytes.decode("utf-8", errors="replace")
    if "base64" in text.lower():
        return _HIDE
    return svg_data_uri(text)


def _resolve_source(value: str, svg_assets: Mapping[int, str]) -> object:
    """Decide what an image source becomes: a URI string, ``_HIDE`` or ``None`` (untouched)."""
    value = value.strip()
    if IMAGE_PLACEHOLDER_PATTERN.fullmatch(value):
        return _HIDE
    ds_match = DS_ASSET_PLACEHOLDER_PATTERN.fullmatch(value)
    if ds_match:
        svg = svg_assets.get(int(ds_match.group(1)))
        if svg is None:
            return _HIDE
        return _svg_text_result(svg.encode("utf-8"))
    data = _DATA_URI.fullmatch(value)
    if not data:
        return None
    mime = data.group(1).strip().lower()
    params = [p.strip().lower() for p in data.group(2).split(";") if p.strip()]
    is_base64 = "base64" in params
    if mime == "image/svg+xml":
        payload = data.group(3)
        if is_base64:
            try:
                svg_bytes = base64.b64decode(payload, validate=False)
            except (binascii.Error, ValueError):
                return _HIDE
        else:
            svg_bytes = unquote_to_bytes(payload)
        result = _svg_text_result(svg_bytes)
        # A text SVG URI that passes the rules stays exactly as written.
        return None if (result is not _HIDE and not is_base64) else result
    if mime.startswith("image/") or is_base64:
        return _HIDE
    return None


# ---------------------------------------------------------------------------
# CSS ``url()`` pass and the final sweep
# ---------------------------------------------------------------------------

_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_LEFTOVER = re.compile(
    r"\{\{image:[A-Za-z0-9_-]+\}\}"
    r"|\{\{ds-asset:\d+\}\}"
    r"|data:[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+(?:;[^;,\s\"'()]*)*;base64,[A-Za-z0-9+/=_%-]*",
    re.IGNORECASE,
)


def _css_urls(css: str, svg_assets: Mapping[int, str], *, reuse_quote: bool) -> tuple[str, int]:
    """Resolve every ``url(...)``. Hidden -> ``none``; inlined -> ``url(<q>uri<q>)``.

    ``reuse_quote`` keeps the original quote character (an unquoted url gets ``'``) so the
    edit stays valid inside a quoted HTML attribute; otherwise the quote is ``"``.
    """
    hidden = 0

    def replace(match: re.Match) -> str:
        nonlocal hidden
        result = _resolve_source(match.group(2), svg_assets)
        if result is None:
            return match.group(0)
        if result is _HIDE:
            hidden += 1
            return "none"
        quote_char = (match.group(1) or "'") if reuse_quote else '"'
        return f"url({quote_char}{result}{quote_char})"

    return _CSS_URL.sub(replace, css), hidden


def _sweep(text: str, svg_assets: Mapping[int, str], hidden_value: str) -> tuple[str, int]:
    """Resolve leftover handles and base64 data URIs anywhere in *text*."""
    hidden = 0

    def replace(match: re.Match) -> str:
        nonlocal hidden
        result = _resolve_source(match.group(0), svg_assets)
        if result is None:
            return match.group(0)
        if result is _HIDE:
            hidden += 1
            return hidden_value
        return str(result)

    return _LEFTOVER.sub(replace, text), hidden


def hide_images_in_css(css: str, svg_assets: Mapping[int, str]) -> tuple[str, int]:
    """Hide or inline every image source in *css*; returns ``(css, hidden_count)``."""
    css, hidden = _css_urls(css, svg_assets, reuse_quote=False)
    css, swept = _sweep(css, svg_assets, "none")
    return css, hidden + swept


# ---------------------------------------------------------------------------
# HTML pass
# ---------------------------------------------------------------------------

_IMG_OR_SOURCE_TAG = re.compile(r"<(img|source)\b((?:\"[^\"]*\"|'[^']*'|[^'\">])*)>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"([^\s\"'>/=]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?")
_ALT_ATTR = f' alt="{IMAGE_NOTICE}"'


def _unquote_attr(raw: str) -> str:
    return raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw


def _rewrite_tag(match: re.Match, svg_assets: Mapping[int, str]) -> tuple[str, int]:
    """Rewrite one ``<img>`` / ``<source>``: its ``src``, ``alt`` and ``srcset``."""
    tag_name, body = match.group(1), match.group(2)
    edits: list[tuple[int, int, str]] = []  # (start, end, replacement) within body
    alt_span: Optional[tuple[int, int]] = None
    src_hidden_at: Optional[int] = None
    hidden = 0
    for attr in _ATTRIBUTE.finditer(body):
        name, raw = attr.group(1).lower(), attr.group(2)
        if raw is None:
            continue
        value = _unquote_attr(raw)
        if name == "src" and tag_name.lower() == "img":
            result = _resolve_source(value, svg_assets)
            if result is None:
                continue
            if result is _HIDE:
                hidden += 1
                src_hidden_at = attr.end()
                result = NOTICE_IMG_SRC
            edits.append((attr.start(), attr.end(), f'src="{result}"'))
        elif name == "alt":
            alt_span = (attr.start(), attr.end())
        elif name == "srcset" and ("data:" in value.lower() or _LEFTOVER.search(value)):
            start = attr.start()
            while start > 0 and body[start - 1].isspace():
                start -= 1
            edits.append((start, attr.end(), ""))
    if src_hidden_at is not None:
        if alt_span:
            edits.append((*alt_span, f'alt="{IMAGE_NOTICE}"'))
        else:
            edits.append((src_hidden_at, src_hidden_at, _ALT_ATTR))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return f"<{tag_name}{body}>", hidden


def hide_images_in_html(html: str, svg_assets: Mapping[int, str]) -> tuple[str, int]:
    """Hide or inline every image source in slide *html*; returns ``(html, hidden_count)``.

    ``<img src>`` becomes ``NOTICE_IMG_SRC`` (and its ``alt`` the notice) when hidden; a
    ``srcset`` holding ``data:`` or a handle is removed (not counted); ``url(...)`` values
    in ``style`` attributes and ``<style>`` blocks are resolved; a final sweep catches
    leftover handles and base64 data URIs in any other attribute.
    """
    total = 0

    def rewrite(match: re.Match) -> str:
        nonlocal total
        text, hidden = _rewrite_tag(match, svg_assets)
        total += hidden
        return text

    html = _IMG_OR_SOURCE_TAG.sub(rewrite, html)
    html, urls = _css_urls(html, svg_assets, reuse_quote=True)
    html, swept = _sweep(html, svg_assets, NOTICE_IMG_SRC)
    return html, total + urls + swept
