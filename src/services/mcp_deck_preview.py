"""Build the HTML preview the MCP deck tools return alongside the structured deck.

The preview shows at most ``MAX_PREVIEW_SLIDES`` whole slides, with standard fonts (embedded
faces become Google Fonts imports) and no images other than small scoped SVGs, inside a UTF-8
byte budget. The page is built with ``SlideDeck.to_html_document`` so its escaping guards
still apply.
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
_BODY_OPEN = "\n<body>\n"
_BODY_CLOSE = "\n</body>"
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

    prepared: list[dict] = []
    slide_hidden: list[int] = []
    for slide in slides:
        slide_html, hidden = hide_images_in_html(slide.get("html") or "", svg_assets)
        prepared.append({**slide, "html": slide_html, "scripts": slide.get("scripts") or ""})
        slide_hidden.append(hidden)

    for k in range(min(total, max_slides), 0, -1):
        shown = prepared[:k]
        used = "\n".join(s["html"] + "\n" + s["scripts"] for s in shown)
        trimmed = trim_css(css, used)
        page_css = f"{imports}\n{trimmed}" if imports and trimmed else imports or trimmed
        page = SlideDeck.from_dict(
            {**deck, "slides": shown, "css": page_css}, title=title
        ).to_html_document()
        page = page.replace(_BODY_OPEN, _BODY_OPEN + _link_div(deck_url, _STRIP_COPY) + "\n", 1)
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
