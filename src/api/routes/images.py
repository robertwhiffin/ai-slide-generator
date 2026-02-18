"""Image upload and management API endpoints."""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.database.models.image import ImageAsset
from src.services import image_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/images", tags=["images"])


# --- Schemas ---

class ImageResponse(BaseModel):
    """Response schema for image metadata."""
    id: int
    filename: str
    original_filename: str
    mime_type: str
    size_bytes: int
    thumbnail_base64: Optional[str]
    tags: List[str]
    description: Optional[str]
    category: Optional[str]
    uploaded_by: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ImageListResponse(BaseModel):
    """Response for listing images."""
    images: List[ImageResponse]
    total: int


class ImageDataResponse(BaseModel):
    """Response containing image base64 data."""
    id: int
    mime_type: str
    base64_data: str
    data_uri: str  # Ready-to-use: "data:image/png;base64,..."


class ImageUpdateRequest(BaseModel):
    """Request to update image metadata."""
    tags: Optional[List[str]] = None
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)


# --- Helper ---

def _get_current_user() -> str:
    """Get current username (dev fallback to 'system')."""
    if os.getenv("ENVIRONMENT") in ("development", "test"):
        return "system"
    try:
        from src.core.databricks_client import get_user_client
        return get_user_client().current_user.me().user_name
    except Exception:
        return "system"


def _image_to_response(img: ImageAsset) -> ImageResponse:
    return ImageResponse(
        id=img.id,
        filename=img.filename,
        original_filename=img.original_filename,
        mime_type=img.mime_type,
        size_bytes=img.size_bytes,
        thumbnail_base64=img.thumbnail_base64,
        tags=img.tags or [],
        description=img.description,
        category=img.category,
        uploaded_by=img.uploaded_by,
        is_active=img.is_active,
        created_at=img.created_at.isoformat(),
        updated_at=img.updated_at.isoformat(),
    )


# --- Endpoints ---

@router.post("/upload", response_model=ImageResponse, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile = File(...),
    tags: Optional[str] = Form(None),          # JSON string: '["branding","logo"]'
    description: Optional[str] = Form(None),
    category: Optional[str] = Form("content"),
    save_to_library: Optional[str] = Form("true"),  # "true" or "false" (Form fields are strings)
    db: Session = Depends(get_db),
):
    """Upload an image file."""
    import json

    try:
        content = await file.read()
        parsed_tags = json.loads(tags) if tags else []
        user = _get_current_user()

        # Override category to ephemeral when not saving to library
        effective_category = category if save_to_library != "false" else "ephemeral"

        image = image_service.upload_image(
            db=db,
            file_content=content,
            original_filename=file.filename or "unknown",
            mime_type=file.content_type or "application/octet-stream",
            user=user,
            tags=parsed_tags,
            description=description,
            category=effective_category,
        )

        return _image_to_response(image)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error uploading image: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload image",
        )


@router.get("", response_model=ImageListResponse)
def list_images(
    category: Optional[str] = None,
    query: Optional[str] = None,
    tags: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List images with optional filtering.

    Args:
        tags: Comma-separated tag names, e.g. ``tags=branding,logo``.
    """
    try:
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        images = image_service.search_images(
            db=db, category=category, query=query, tags=parsed_tags,
        )
        return ImageListResponse(
            images=[_image_to_response(img) for img in images],
            total=len(images),
        )
    except Exception as e:
        logger.error(f"Error listing images: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list images",
        )


@router.get("/{image_id}", response_model=ImageResponse)
def get_image(image_id: int, db: Session = Depends(get_db)):
    """Get image metadata by ID."""
    try:
        image = db.query(ImageAsset).filter(
            ImageAsset.id == image_id,
            ImageAsset.is_active == True,
        ).first()
        if not image:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        return _image_to_response(image)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting image {image_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get image",
        )


@router.get("/{image_id}/data", response_model=ImageDataResponse)
def get_image_data(image_id: int, db: Session = Depends(get_db)):
    """Get full image as base64 data (for embedding in slides)."""
    try:
        b64_data, mime_type = image_service.get_image_base64(db, image_id)
        return ImageDataResponse(
            id=image_id,
            mime_type=mime_type,
            base64_data=b64_data,
            data_uri=f"data:{mime_type};base64,{b64_data}",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting image data {image_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get image data",
        )


@router.put("/{image_id}", response_model=ImageResponse)
def update_image(
    image_id: int,
    request: ImageUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update image metadata (tags, description, category)."""
    try:
        image = db.query(ImageAsset).filter(
            ImageAsset.id == image_id,
            ImageAsset.is_active == True,
        ).first()
        if not image:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

        if request.tags is not None:
            image.tags = request.tags
        if request.description is not None:
            image.description = request.description
        if request.category is not None:
            image.category = request.category

        image.updated_by = _get_current_user()
        db.commit()
        db.refresh(image)
        return _image_to_response(image)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating image {image_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update image",
        )


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(image_id: int, db: Session = Depends(get_db)):
    """Soft-delete an image."""
    try:
        user = _get_current_user()
        image_service.delete_image(db, image_id, user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting image {image_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete image",
        )
