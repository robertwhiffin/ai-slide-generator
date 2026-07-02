"""Design-system asset placeholder substitution for generated slides.

Sibling of ``src.utils.image_utils`` but a DISTINCT namespace. The Phase-2
compiler emits ``{{ds-asset:ID}}`` for brand assets stored in
``design_system_asset``; this module swaps those for base64 data URIs at the API
response boundary — exactly how ``{{image:ID}}`` is resolved for ``image_assets``.

The two resolvers are intentionally orthogonal: this one only ever touches
``{{ds-asset:ID}}`` and never ``{{image:ID}}`` (and vice-versa), because the two
tables have independent id sequences.
"""
import logging
import re

from sqlalchemy.orm import Session

from src.services import design_system_service

logger = logging.getLogger(__name__)

DS_ASSET_PLACEHOLDER_PATTERN = re.compile(r"\{\{ds-asset:(\d+)\}\}")


def substitute_ds_asset_placeholders(html: str, db: Session) -> str:
    """Replace {{ds-asset:ID}} placeholders with base64 data URIs.

    Works in both HTML ``img src`` and CSS ``url()`` contexts. Unknown ids are
    left in place (never raise), mirroring the image resolver.
    """
    if not html or "{{ds-asset:" not in html:
        return html

    def replace_match(match: "re.Match[str]") -> str:
        asset_id = int(match.group(1))
        try:
            b64_data, mime_type = design_system_service.get_asset_base64(db, asset_id)
            return f"data:{mime_type};base64,{b64_data}"
        except Exception as e:
            logger.warning(
                f"Failed to resolve ds-asset placeholder {{{{ds-asset:{asset_id}}}}}: {e}"
            )
            return match.group(0)  # Leave placeholder if asset not found

    return DS_ASSET_PLACEHOLDER_PATTERN.sub(replace_match, html)


# Deck-level string fields (siblings of per-slide ``html``) that can carry a
# ``{{ds-asset:ID}}`` reference. Per the deck_json schema — "slides array, css,
# external_scripts, scripts" (see ``database/models/session.py``) — these are the
# only asset-bearing fields: ``css`` holds @font-face ``src: url()`` fonts and
# ``background-image: url()`` backgrounds, and ``html_content`` is the full
# knitted HTML. ``scripts``/``external_scripts`` are JavaScript and never
# reference brand assets, so they are intentionally excluded.
_DECK_DS_ASSET_FIELDS = ("html_content", "css")


def substitute_deck_dict_ds_assets(deck_dict: dict, db: Session) -> dict:
    """Substitute {{ds-asset:ID}} placeholders across a deck dict.

    Covers every field that can carry the placeholder: each slide's ``html``,
    the deck's ``html_content`` (full knitted HTML) and its top-level ``css``
    (fonts + backgrounds). Deck-level fields are resolved independently of the
    slides array so a deck with no slides still has its ``css``/``html_content``
    substituted.
    """
    if not deck_dict:
        return deck_dict
    for slide in deck_dict.get("slides") or []:
        html = slide.get("html", "")
        if "{{ds-asset:" in html:
            slide["html"] = substitute_ds_asset_placeholders(html, db)
    for field in _DECK_DS_ASSET_FIELDS:
        value = deck_dict.get(field)
        if value and "{{ds-asset:" in value:
            deck_dict[field] = substitute_ds_asset_placeholders(value, db)
    return deck_dict
