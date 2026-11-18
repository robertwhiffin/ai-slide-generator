"""Build the HTML preview the MCP deck tools return as the second part of their result.

The preview shows at most ``MAX_PREVIEW_SLIDES`` whole slides, with standard fonts (embedded
faces become Google Fonts imports) and no images other than small scoped SVGs, inside a UTF-8
byte budget. The page is built with ``SlideDeck.to_html_document`` so its escaping guards
still apply.

Each slide sits in its own 1280x720 host frame, as in the Tellr app (the frontend's
``slideHostFrameStyle``): design-system decks position the slide root absolutely, and
without a frame every slide would pile up at the top of the page, over the strip and the
notice. The frame rules are a separate ``<style>`` block after the deck's, so the css
trimmer never sees them and no stray text in the deck's css can swallow them.
"""

from __future__ import annotations

import copy
import html as html_lib
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from src.domain.slide_deck import SlideDeck
from src.utils.ds_asset_utils import DS_ASSET_PLACEHOLDER_PATTERN
from src.utils.preview_css import google_fonts_imports, strip_embedded_font_faces, trim_css
from src.utils.preview_images import hide_images_in_css, hide_images_in_html

MAX_PREVIEW_SLIDES = 10
MCP_RESULT_BUDGET_BYTES = 150_000

_STRIP_COPY = "preview — open the full deck in tellr"
# ``to_html_document``'s layout: the deck's style block ends with ``_STYLE_END`` and the
# head with ``_HEAD_BODY``; the body ends with the last ``_BODY_CLOSE``.
_STYLE_END = "\n  </style>\n"
_HEAD_BODY = "\n</head>\n<body>\n"
_BODY_CLOSE = "\n</body>"
_FRAME_CLASS = "tellr-preview-frame"
# Mirrors frontend/src/services/slideDocument.ts slideHostFrameStyle: the frame is the
# positioned 1280x720 box, and its direct child (the slide root) fills it. The
# ``:not(#tellr-host-frame-boost)`` arm lifts the child rule to id specificity so an
# id-scoped ``!important`` size on a slide root cannot shrink it; ``.slide-wrapper`` is
# excluded as there. Unlike the app's host (``<body>`` itself), the frames are children of
# ``<body>``, so ``flex:none`` stops a deck that lays its body out as a flex column (Legacy
# decks and the app's own HTML export do) from shrinking them to fit the window.
_FRAME_STYLE = (
    "  <style>\n"
    f".{_FRAME_CLASS}{{position:relative!important;width:1280px!important;"
    "height:720px!important;flex:none!important;overflow:hidden;margin:16px auto}\n"
    f".{_FRAME_CLASS}>:not(#tellr-host-frame-boost):not(.slide-wrapper){{"
    "position:absolute!important;inset:0!important;width:100%!important;"
    "height:100%!important;box-sizing:border-box!important;overflow:hidden}\n"
    "  </style>"
)
_BOX_STYLE = (
    "font-family:system-ui,sans-serif;font-size:14px;padding:10px 16px;"
    "background:#1B3139;color:#fff;"
)
_LINK_STYLE = "color:#FF5F46"


@dataclass(frozen=True)
class DeckPreview:
    html: Optional[str]
    slides_shown: int
    slides_total: int
    images_hidden: int
    note: str

    def as_payload(self) -> dict:
        return {
            "included": self.html is not None,
            "slides_shown": self.slides_shown,
            "slides_total": self.slides_total,
            "images_hidden": self.images_hidden,
            "note": self.note,
        }


def ds_asset_ids_in(deck_dict: dict) -> set[int]:
    """Every ``{{ds-asset:N}}`` id in the slides' html and the css minus embedded fonts."""
    css, _ = strip_embedded_font_faces(deck_dict.get("css") or "")
    texts = [css] + [slide.get("html") or "" for slide in deck_dict.get("slides") or []]
    return {int(m) for text in texts for m in DS_ASSET_PLACEHOLDER_PATTERN.findall(text)}


def _link_div(url: str, text: str) -> str:
    return (
        f'<div style="{_BOX_STYLE}"><a href="{html_lib.escape(url, quote=True)}" '
        f'style="{_LINK_STYLE}">{text}</a></div>'
    )


def _framed(slide_html: str) -> str:
    """The slide's html, verbatim, inside its host frame."""
    return f'<div class="{_FRAME_CLASS}">\n{slide_html}\n</div>'


def _add_frame_style_and_strip(page: str, strip: str, *, has_deck_style: bool) -> str:
    """Close ``<head>`` with the frame rules and open ``<body>`` with the strip.

    The deck's css cannot hold a style closer (``to_html_document`` neutralises them) and
    the title and script srcs are escaped, so the first head/body boundary after the
    deck's style block (or, with none, the first at all) is the document's own, whatever
    text the css or the slides carry.
    """
    at = page.index(_HEAD_BODY, page.index(_STYLE_END) if has_deck_style else 0)
    rest = page[at + len(_HEAD_BODY) :]
    return f"{page[:at]}\n{_FRAME_STYLE}{_HEAD_BODY}{strip}\n{rest}"


def _note(shown: int, total: int) -> str:
    tail = "(standard fonts, images not shown). Open the full deck in tellr."
    if shown == total:
        return f"Showing all {total} {'slide' if total == 1 else 'slides'} as a preview {tail}"
    return f"Showing {shown} of {total} slides as a preview {tail}"


def build_deck_preview(
    deck_dict: dict,
    *,
    title: Optional[str],
    deck_url: str,
    svg_assets: Mapping[int, str],
    max_html_bytes: int,
    max_slides: int = MAX_PREVIEW_SLIDES,
) -> DeckPreview:
    """Preview the first slides of ``deck_dict`` that fit ``max_html_bytes`` UTF-8 bytes.

    ``deck_dict`` is the persisted snapshot (slide-number tokens substituted, no image
    substitution). It is not mutated.
    """
    deck: dict[str, Any] = copy.deepcopy(deck_dict)
    slides = deck.get("slides") or []
    total = len(slides)
    if total == 0:
        return DeckPreview(None, 0, 0, 0, "This deck has no slides yet. Open it in tellr.")

    css, faces = strip_embedded_font_faces(deck.get("css") or "")
    imports = google_fonts_imports(faces)
    css, css_hidden = hide_images_in_css(css, svg_assets)

    # Only the slides that can be shown are prepared: the rest are never on the page and
    # their images are not counted.
    limit = max(0, min(total, max_slides))
    used_texts: list[str] = []
    framed: list[dict] = []
    slide_hidden: list[int] = []
    for slide in slides[:limit]:
        slide_html, hidden = hide_images_in_html(slide.get("html") or "", svg_assets)
        scripts = slide.get("scripts") or ""
        used_texts.append(slide_html + "\n" + scripts)
        framed.append({**slide, "html": _framed(slide_html), "scripts": scripts})
        slide_hidden.append(hidden)

    strip = _link_div(deck_url, _STRIP_COPY)
    for k in range(limit, 0, -1):
        trimmed = trim_css(css, "\n".join(used_texts[:k]))
        page_css = f"{imports}\n{trimmed}" if imports and trimmed else imports or trimmed
        page = SlideDeck.from_dict(
            {**deck, "slides": framed[:k], "css": page_css}, title=title
        ).to_html_document()
        page = _add_frame_style_and_strip(page, strip, has_deck_style=bool(page_css))
        if k < total:
            left = total - k
            word = "slide" if left == 1 else "slides"
            notice = _link_div(deck_url, f"{left} more {word} — see full deck in tellr")
            cut = page.rfind(_BODY_CLOSE)
            page = page[:cut] + "\n" + notice + page[cut:]
        if len(page.encode("utf-8")) <= max_html_bytes:
            return DeckPreview(page, k, total, css_hidden + sum(slide_hidden[:k]), _note(k, total))

    return DeckPreview(
        None, 0, total, 0, "This deck is too large to preview here. Open the full deck in tellr."
    )
