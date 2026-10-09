"""Image tools for the slide generator agent."""
import json
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from src.core.database import get_db_session
from src.services import image_service

logger = logging.getLogger(__name__)

_NO_IMAGES_MESSAGE = "No images found matching your criteria."


class SearchImagesInput(BaseModel):
    """Input schema for image search tool."""
    query: Optional[str] = Field(None, description="Search by filename or description")
    category: Optional[str] = Field(None, description="Filter by category: 'branding', 'content', or 'background'")
    tags: Optional[List[str]] = Field(None, description="Filter by tags, e.g. ['logo', 'branding']")


def search_images(
    query: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    """
    Search for uploaded images to include in slides.

    Use this when the user mentions images, logos, branding, or visual elements.
    Returns image metadata (ID, name, description) - NOT the image data itself.

    To include an image in a slide, use the image ID in an img tag:
    <img src="{{image:ID}}" alt="description" />
    The system will automatically replace this with the actual image data.

    Args:
        query: Search by filename or description
        category: Filter by 'branding', 'content', or 'background'
        tags: Filter by tags like ['logo', 'branding']

    Returns:
        JSON list of matching images with id, filename, description, and tags
    """
    # F-CR-27: chat-pasted ("ephemeral") images are private to their uploader and
    # are never discoverable through the agent tool. The user's own pastes reach
    # the agent via their message, not via search.
    if category is not None and category.strip().lower() == "ephemeral":
        logger.warning("search_images: refusing category='ephemeral' (private images)")
        return json.dumps({"message": _NO_IMAGES_MESSAGE, "images": []})

    # Scope the listing to the caller (same as GET /api/images). Fail closed when
    # no identity is bound rather than listing every user's images.
    requesting_user = image_service.resolve_requesting_user()
    if requesting_user is None:
        logger.warning("search_images: no requesting user bound; returning no images")
        return json.dumps({"message": _NO_IMAGES_MESSAGE, "images": []})

    with get_db_session() as db:
        images = image_service.search_images(
            db=db,
            query=query,
            category=category,
            tags=tags,
            uploaded_by=requesting_user,
        )

        # Return metadata only - NEVER base64
        # Must build results inside session scope to avoid DetachedInstanceError
        results = [
            {
                "id": img.token,  # Opaque token (SDR-4437 F-TM-7), never the int PK.
                "filename": img.original_filename,
                "description": img.description,
                "tags": img.tags,
                "category": img.category,
                "mime_type": img.mime_type,
                "usage": f'<img src="{{{{image:{img.token}}}}}" alt="{img.description or img.original_filename}" />',
            }
            for img in images
        ]

    if not results:
        return json.dumps({"message": _NO_IMAGES_MESSAGE, "images": []})

    return json.dumps({"message": f"Found {len(results)} image(s).", "images": results})
