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


def substitute_deck_dict_ds_assets(deck_dict: dict, db: Session) -> dict:
    """Substitute {{ds-asset:ID}} placeholders in all slides of a deck dict."""
    if not deck_dict or not deck_dict.get("slides"):
        return deck_dict
    for slide in deck_dict["slides"]:
        html = slide.get("html", "")
        if "{{ds-asset:" in html:
            slide["html"] = substitute_ds_asset_placeholders(html, db)
    # Also handle html_content if present (full knitted HTML)
    if deck_dict.get("html_content") and "{{ds-asset:" in deck_dict["html_content"]:
        deck_dict["html_content"] = substitute_ds_asset_placeholders(deck_dict["html_content"], db)
    return deck_dict
