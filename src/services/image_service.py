"""Image upload, thumbnail generation, and retrieval service."""
import base64
import logging
import uuid
from io import BytesIO
from typing import List, Optional

from PIL import Image as PILImage
from sqlalchemy.orm import Session

from src.database.models.image import ImageAsset

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
THUMBNAIL_SIZE = (150, 150)
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/gif", "image/svg+xml"}


def upload_image(
    db: Session,
    file_content: bytes,
    original_filename: str,
    mime_type: str,
    user: str,
    tags: Optional[List[str]] = None,
    description: Optional[str] = None,
    category: str = "content",
) -> ImageAsset:
    """
    Upload an image: validate, generate thumbnail, save to database.

    All data (metadata + raw bytes + thumbnail) stored in a single DB row.
    No external storage dependencies.
    """
    # 1. Validate (fail fast, no side effects)
    if mime_type not in ALLOWED_TYPES:
        raise ValueError(f"File type not allowed: {mime_type}. Allowed: {ALLOWED_TYPES}")
    if len(file_content) > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {len(file_content)} bytes (max {MAX_FILE_SIZE})")

    # 2. Generate thumbnail (in-memory, no side effects)
    thumbnail_b64 = _generate_thumbnail(file_content, mime_type)

    # 3. Save everything to database
    image_uuid = str(uuid.uuid4())
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "bin"

    image = ImageAsset(
        filename=f"{image_uuid}.{ext}",
        original_filename=original_filename,
        mime_type=mime_type,
        size_bytes=len(file_content),
        image_data=file_content,
        thumbnail_base64=thumbnail_b64,
        tags=tags or [],
        description=description or "",
        category=category,
        uploaded_by=user,
        created_by=user,
        updated_by=user,
        is_active=True,
    )

    db.add(image)
    db.commit()
    db.refresh(image)

    logger.info(f"Uploaded image: {image.filename} (id={image.id}, {image.size_bytes} bytes)")
    return image


def get_image_base64(db: Session, image_id: int) -> tuple[str, str]:
    """
    Get full image as base64 string.

    Returns:
        Tuple of (base64_data, mime_type)
    """
    image = db.query(ImageAsset).filter(
        ImageAsset.id == image_id,
        ImageAsset.is_active == True,
    ).first()
    if not image:
        raise ValueError(f"Image {image_id} not found")

    b64 = base64.b64encode(image.image_data).decode("utf-8")
    return b64, image.mime_type


def search_images(
    db: Session,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    query: Optional[str] = None,
    uploaded_by: Optional[str] = None,
) -> List[ImageAsset]:
    """Search images by metadata. Returns metadata only (no image_data loaded).

    Note: SQLAlchemy loads all columns by default. For list views, the caller
    should use deferred loading or column selection if performance becomes an
    issue with many large images. For MVP, this is fine.
    """
    q = db.query(ImageAsset).filter(ImageAsset.is_active == True)

    # Exclude ephemeral images from default library view
    if category:
        q = q.filter(ImageAsset.category == category)
    else:
        q = q.filter(ImageAsset.category != "ephemeral")

    if uploaded_by:
        q = q.filter(ImageAsset.uploaded_by == uploaded_by)
    if query:
        search = f"%{query}%"
        q = q.filter(
            (ImageAsset.original_filename.ilike(search))
            | (ImageAsset.description.ilike(search))
        )
    # Tag filtering: PostgreSQL JSON containment: tags @> '["branding"]'
    if tags:
        for tag in tags:
            q = q.filter(ImageAsset.tags.contains([tag]))

    return q.order_by(ImageAsset.created_at.desc()).all()


def delete_image(db: Session, image_id: int, user: str) -> None:
    """Soft-delete an image."""
    image = db.query(ImageAsset).filter(ImageAsset.id == image_id).first()
    if not image:
        raise ValueError(f"Image {image_id} not found")

    image.is_active = False
    image.updated_by = user
    db.commit()

    logger.info(f"Soft-deleted image: {image.filename} (id={image.id})")


def _generate_thumbnail(content: bytes, mime_type: str) -> Optional[str]:
    """
    Generate 150x150 thumbnail as base64 data URI.

    - For raster images: resize with Pillow, maintain aspect ratio
    - For animated GIFs: extract first frame
    - For SVGs: return None (render as-is in UI, they scale natively)
    """
    if mime_type == "image/svg+xml":
        return None

    img = PILImage.open(BytesIO(content))

    # For animated GIFs, use first frame
    if mime_type == "image/gif" and hasattr(img, "n_frames") and img.n_frames > 1:
        img.seek(0)

    # Convert palette/CMYK to RGB(A)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in (img.mode or "") else "RGB")

    # Resize maintaining aspect ratio
    img.thumbnail(THUMBNAIL_SIZE, PILImage.Resampling.LANCZOS)

    # Encode as PNG (supports transparency) or JPEG
    buffer = BytesIO()
    if img.mode == "RGBA":
        img.save(buffer, format="PNG")
        thumb_mime = "image/png"
    else:
        img.save(buffer, format="JPEG", quality=85)
        thumb_mime = "image/jpeg"

    buffer.seek(0)
    b64 = base64.b64encode(buffer.read()).decode("utf-8")
    return f"data:{thumb_mime};base64,{b64}"
