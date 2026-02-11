"""Image tools for the slide generator agent."""
import json
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from src.core.database import get_db_session
from src.services import image_service

logger = logging.getLogger(__name__)


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
    with get_db_session() as db:
        images = image_service.search_images(
            db=db,
            query=query,
            category=category,
            tags=tags,
        )

        # Return metadata only - NEVER base64
        # Must build results inside session scope to avoid DetachedInstanceError
        results = [
            {
                "id": img.id,
                "filename": img.original_filename,
                "description": img.description,
                "tags": img.tags,
                "category": img.category,
                "mime_type": img.mime_type,
                "usage": f'<img src="{{{{image:{img.id}}}}}" alt="{img.description or img.original_filename}" />',
            }
            for img in images
        ]

    if not results:
        return json.dumps({"message": "No images found matching your criteria.", "images": []})

    return json.dumps({"message": f"Found {len(results)} image(s).", "images": results})
