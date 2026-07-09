"""Image placeholder substitution for generated slides."""
import logging
import re

from sqlalchemy.orm import Session

from src.services import image_service

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDER_PATTERN = re.compile(r"\{\{image:(\d+)\}\}")


def substitute_image_placeholders(html: str, db: Session) -> str:
    """
    Replace {{image:ID}} placeholders with base64 data URIs.

    Called after agent generates HTML, before returning to frontend.
    Works in both HTML img src and CSS url() contexts.
    """
    if not html or "{{image:" not in html:
        return html

    def replace_match(match):
        image_id = int(match.group(1))
        try:
            b64_data, mime_type = image_service.get_image_base64(db, image_id)
            return f"data:{mime_type};base64,{b64_data}"
        except Exception as e:
            logger.warning(f"Failed to resolve image placeholder {{{{image:{image_id}}}}}: {e}")
            return match.group(0)  # Leave placeholder if image not found

    return IMAGE_PLACEHOLDER_PATTERN.sub(replace_match, html)


# Deck-level string fields (siblings of per-slide ``html``) that can carry an
# ``{{image:ID}}`` reference — same field set as the ds-asset resolver
# (``src.utils.ds_asset_utils``): ``css`` holds ``background-image: url()``
# references, ``html_content`` is the full knitted HTML.
_DECK_IMAGE_FIELDS = ("html_content", "css")


def substitute_deck_dict_images(deck_dict: dict, db: Session) -> dict:
    """Substitute {{image:ID}} placeholders across a deck dict.

    Covers every field that can carry the placeholder: each slide's ``html``,
    the deck's ``html_content`` (full knitted HTML) and its top-level ``css``
    (backgrounds). Deck-level fields are resolved independently of the slides
    array, mirroring ``substitute_deck_dict_ds_assets`` — the css gap fixed
    there existed here too.
    """
    if not deck_dict:
        return deck_dict
    for slide in deck_dict.get("slides") or []:
        html = slide.get("html", "")
        if "{{image:" in html:
            slide["html"] = substitute_image_placeholders(html, db)
    for field in _DECK_IMAGE_FIELDS:
        value = deck_dict.get(field)
        if value and "{{image:" in value:
            deck_dict[field] = substitute_image_placeholders(value, db)
    return deck_dict
