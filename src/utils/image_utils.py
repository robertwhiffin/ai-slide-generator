"""Image placeholder substitution for generated slides."""
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from src.services import image_service

logger = logging.getLogger(__name__)

# Tokens are secrets.token_urlsafe(...) → [A-Za-z0-9_-] (SDR-4437 F-TM-7).
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"\{\{image:([A-Za-z0-9_-]+)\}\}")


def substitute_image_placeholders(
    html: str, db: Session, *, requesting_user: Optional[str] = None
) -> str:
    """
    Replace {{image:ID}} placeholders with base64 data URIs.

    Called after agent generates HTML, before returning to frontend.
    Works in both HTML img src and CSS url() contexts.

    Resolution is scoped to the acting user (F-CR-27): another user's ephemeral
    image is left as an unresolved placeholder. ``requesting_user`` defaults to
    the request-scoped identity (``image_service.resolve_requesting_user``);
    background callers without a request context must pass it explicitly.
    """
    if not html or "{{image:" not in html:
        return html
    if requesting_user is None:
        requesting_user = image_service.resolve_requesting_user()

    def replace_match(match):
        image_token = match.group(1)
        try:
            b64_data, mime_type = image_service.get_image_base64(
                db, image_token, requesting_user=requesting_user
            )
            return f"data:{mime_type};base64,{b64_data}"
        except Exception as e:
            logger.warning(f"Failed to resolve image placeholder {{{{image:{image_token}}}}}: {e}")
            return match.group(0)  # Leave placeholder if image not found

    return IMAGE_PLACEHOLDER_PATTERN.sub(replace_match, html)


# Deck-level string fields (siblings of per-slide ``html``) that can carry an
# ``{{image:ID}}`` reference — same field set as the ds-asset resolver
# (``src.utils.ds_asset_utils``): ``css`` holds ``background-image: url()``
# references, ``html_content`` is the full knitted HTML.
_DECK_IMAGE_FIELDS = ("html_content", "css")


def substitute_deck_dict_images(
    deck_dict: dict, db: Session, *, requesting_user: Optional[str] = None
) -> dict:
    """Substitute {{image:ID}} placeholders across a deck dict.

    Covers every field that can carry the placeholder: each slide's ``html``,
    the deck's ``html_content`` (full knitted HTML) and its top-level ``css``
    (backgrounds). Deck-level fields are resolved independently of the slides
    array, mirroring ``substitute_deck_dict_ds_assets`` — the css gap fixed
    there existed here too. ``requesting_user`` is as for
    ``substitute_image_placeholders``.
    """
    if not deck_dict:
        return deck_dict
    if requesting_user is None:
        requesting_user = image_service.resolve_requesting_user()
    for slide in deck_dict.get("slides") or []:
        html = slide.get("html", "")
        if "{{image:" in html:
            slide["html"] = substitute_image_placeholders(
                html, db, requesting_user=requesting_user
            )
    for field in _DECK_IMAGE_FIELDS:
        value = deck_dict.get(field)
        if value and "{{image:" in value:
            deck_dict[field] = substitute_image_placeholders(
                value, db, requesting_user=requesting_user
            )
    return deck_dict
