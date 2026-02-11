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
