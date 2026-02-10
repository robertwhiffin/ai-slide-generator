# Image Upload Feature - Architecture Plan

## Quick Reference (MVP Decisions)

- **Storage**: UC Volumes (binaries) + Lakebase (metadata + thumbnails)
- **Serving**: Base64 data URIs embedded in HTML (self-contained slides)
- **Thumbnails**: 150x150 base64 stored in `images.thumbnail_base64` column
- **Size Limit**: 5MB per image
- **File Types**: PNG, JPG, GIF (including animated), SVG
- **Optimization**: None for MVP (rely on size limit)
- **Branding**: Controlled via Slide Styles (single source of truth for appearance)
- **Permissions/Sharing**: Deferred (separate permissions branch in progress)

## Feature Overview

Enable users to upload, manage, and use images in presentations with two primary use cases:
1. **Branding**: Company logos on every slide, controlled via slide style CSS
2. **Content Images**: Specific images per slide via conversation or UI

---

## Critical Codebase Conventions

An implementing agent MUST follow these patterns (deviation will break consistency):

### Database Models
- **Integer primary keys** (not UUID strings) - see `ConfigProfile.id`, `SlideStyleLibrary.id`
- **Plain SQLAlchemy style**: `id = Column(Integer, primary_key=True)` (not type-annotated)
- **User tracking**: `created_by = Column(String(255))` and `updated_by = Column(String(255))`
- **Timestamps**: `created_at = Column(DateTime, default=datetime.utcnow)`, `updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)`
- **Soft deletes**: Use `is_active = Column(Boolean, default=True)` pattern (see `SlideStyleLibrary`)
- **Import in `__init__.py`**: New models MUST be added to `src/database/models/__init__.py`
- **Base class**: Import from `src.core.database import Base`

### API Routes
- **DB session via Depends**: `db: Session = Depends(get_db)` on every endpoint
- **Error handling**: try/except with `db.rollback()`, re-raise `HTTPException`
- **User tracking**: Use the `get_user_client().current_user.me().user_name` pattern with dev/test fallback to `"system"`
- **Schemas inline**: Pydantic request/response schemas defined in the same route file (see `slide_styles.py`)
- **Registration**: Add router to `src/api/routes/settings/__init__.py` and `include_router` in `src/api/main.py`

### Agent Tools
- **StructuredTool.from_function()** pattern (not class inheritance from BaseTool)
- **Pydantic input schemas** with `Field(description=...)` (see `GenieQueryInput`)
- **Plain functions** wrapped in StructuredTool (see `tools.py`)

### Database Init
- **No Alembic**: This project uses `Base.metadata.create_all(bind=engine)` in `src/core/database.py`
- **New tables auto-created on startup** if the model is imported in `__init__.py`

---

## Storage Architecture

### Primary Storage: Unity Catalog Volumes

```
/Volumes/{catalog}/{schema}/slide_images/
├── {user_id}/
│   ├── {image_id}.png
│   ├── {image_id}.jpg
│   └── {image_id}.gif
└── shared/
    └── {image_id}.{ext}
```

**Why UC Volumes (not Lakebase binary)?**
- Designed for file storage (PostgreSQL not optimized for large blobs)
- Respects Unity Catalog permissions
- Cost-effective at scale
- Databricks-native SDK integration

### Volume Path Configuration

The volume path MUST be configurable, not hardcoded. Add to `config/config.yaml`:

```yaml
images:
  volume_path: "/Volumes/catalog/schema/slide_images"
  max_file_size_bytes: 5242880  # 5MB
  allowed_types:
    - "image/png"
    - "image/jpeg"
    - "image/gif"
    - "image/svg+xml"
```

For **local development** (no UC Volumes available), use a filesystem fallback:

```python
# Environment detection
if os.getenv("ENVIRONMENT") == "development" and not is_databricks_environment():
    # Fall back to local filesystem
    storage_path = Path("./data/images")
else:
    # Use UC Volumes via Databricks SDK
    storage_path = config.images.volume_path
```

### Metadata Storage: Lakebase (PostgreSQL)

```python
# src/database/models/image.py
"""Image metadata model for uploaded images."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON

from src.core.database import Base


class ImageAsset(Base):
    """Uploaded image metadata.

    Actual image binaries are stored in UC Volumes (or local filesystem in dev).
    This table stores metadata, thumbnails, and optional base64 cache for
    frequently accessed branding images.
    """

    __tablename__ = "image_assets"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)           # Generated: {uuid}.{ext}
    original_filename = Column(String(255), nullable=False)  # User's original filename
    mime_type = Column(String(50), nullable=False)           # image/png, image/jpeg, image/gif, image/svg+xml
    size_bytes = Column(Integer, nullable=False)
    storage_path = Column(String(500), nullable=False)       # Relative path within volume/local dir

    # Thumbnail (150x150, auto-generated on upload)
    # Stored as data URI: "data:image/jpeg;base64,..."
    # For SVGs: stores the raw SVG content (small enough for inline)
    thumbnail_base64 = Column(Text, nullable=True)

    # Organization
    tags = Column(JSON, default=list)                        # ["branding", "logo", "chart"]
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)             # 'branding', 'content', 'background'

    # Ownership (no FK to profiles - images are independent library items)
    uploaded_by = Column(String(255), nullable=True)

    # Soft delete
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps + user tracking
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Optional: Full image base64 cache (for branding images used repeatedly)
    # Avoids repeated UC Volume reads during slide generation
    cached_base64 = Column(Text, nullable=True)

    def __repr__(self):
        return f"<ImageAsset(id={self.id}, filename='{self.filename}', category='{self.category}')>"
```

**Key differences from original plan:**
- `Integer` PK (not UUID string) - matches all other models
- Named `ImageAsset` (avoids collision with `PIL.Image`)
- No `profile_id` FK - images are a global library, not profile-scoped
- No `ImageCache` table - `cached_base64` column is sufficient
- `storage_path` instead of `volume_path` - works for both UC Volumes and local dev
- Follows `created_by`/`updated_by`/`is_active` patterns from `SlideStyleLibrary`

### Register the Model

Add to `src/database/models/__init__.py`:
```python
from src.database.models.image import ImageAsset

__all__ = [
    # ... existing ...
    "ImageAsset",
]
```

---

## Backend Implementation

### New Dependency: Pillow

Add to `pyproject.toml` dependencies:
```toml
"Pillow>=10.0.0",
```

### Storage Service: `src/services/image_storage.py`

Abstracts storage backend (UC Volumes vs local filesystem):

```python
"""Image storage abstraction for UC Volumes and local filesystem."""
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ImageStorageBackend(ABC):
    """Abstract base class for image storage."""

    @abstractmethod
    def write(self, path: str, content: bytes) -> None: ...

    @abstractmethod
    def read(self, path: str) -> bytes: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...


class UCVolumeStorage(ImageStorageBackend):
    """Store images in Unity Catalog Volumes via Databricks SDK."""

    def __init__(self, volume_base_path: str):
        from src.core.databricks_client import get_system_client
        self.client = get_system_client()
        self.base_path = volume_base_path

    def write(self, path: str, content: bytes) -> None:
        from io import BytesIO
        full_path = f"{self.base_path}/{path}"
        self.client.files.upload(full_path, BytesIO(content), overwrite=True)

    def read(self, path: str) -> bytes:
        full_path = f"{self.base_path}/{path}"
        response = self.client.files.download(full_path)
        return response.contents.read()

    def delete(self, path: str) -> None:
        full_path = f"{self.base_path}/{path}"
        self.client.files.delete(full_path)

    def exists(self, path: str) -> bool:
        try:
            full_path = f"{self.base_path}/{path}"
            self.client.files.get_status(full_path)
            return True
        except Exception:
            return False


class LocalFileStorage(ImageStorageBackend):
    """Store images on local filesystem (for development)."""

    def __init__(self, base_dir: str = "./data/images"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write(self, path: str, content: bytes) -> None:
        file_path = self.base_dir / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

    def read(self, path: str) -> bytes:
        return (self.base_dir / path).read_bytes()

    def delete(self, path: str) -> None:
        file_path = self.base_dir / path
        if file_path.exists():
            file_path.unlink()

    def exists(self, path: str) -> bool:
        return (self.base_dir / path).exists()


def get_image_storage() -> ImageStorageBackend:
    """Factory: returns appropriate storage backend for current environment."""
    if os.getenv("ENVIRONMENT") == "development" and not os.getenv("PGHOST"):
        return LocalFileStorage()
    else:
        # TODO: Get volume path from config
        volume_path = os.getenv("IMAGE_VOLUME_PATH", "/Volumes/catalog/schema/slide_images")
        return UCVolumeStorage(volume_path)
```

### Image Service: `src/services/image_service.py`

```python
"""Image upload, thumbnail generation, and retrieval service."""
import base64
import logging
import uuid
from io import BytesIO
from typing import List, Optional

from PIL import Image as PILImage
from sqlalchemy.orm import Session

from src.database.models.image import ImageAsset
from src.services.image_storage import get_image_storage

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
    Upload an image: validate, generate thumbnail, store binary, save metadata.

    Order of operations matters for error recovery:
    1. Validate (fail fast, no side effects)
    2. Generate thumbnail (in-memory, no side effects)
    3. Write to storage (external side effect)
    4. Write to database (if this fails, we have an orphan file - acceptable for MVP)
    """
    # 1. Validate
    if mime_type not in ALLOWED_TYPES:
        raise ValueError(f"File type not allowed: {mime_type}. Allowed: {ALLOWED_TYPES}")
    if len(file_content) > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {len(file_content)} bytes (max {MAX_FILE_SIZE})")

    # 2. Generate thumbnail
    thumbnail_b64 = _generate_thumbnail(file_content, mime_type)

    # 3. Write to storage
    image_uuid = str(uuid.uuid4())
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "bin"
    storage_path = f"{user}/{image_uuid}.{ext}"

    storage = get_image_storage()
    storage.write(storage_path, file_content)

    # 4. Save metadata to database
    image = ImageAsset(
        filename=f"{image_uuid}.{ext}",
        original_filename=original_filename,
        mime_type=mime_type,
        size_bytes=len(file_content),
        storage_path=storage_path,
        thumbnail_base64=thumbnail_b64,
        tags=tags or [],
        description=description or "",
        category=category,
        uploaded_by=user,
        created_by=user,
        updated_by=user,
        is_active=True,
    )

    # Pre-cache base64 for branding images (avoids repeated storage reads)
    if category == "branding":
        image.cached_base64 = base64.b64encode(file_content).decode("utf-8")

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

    # Use cache if available (branding images)
    if image.cached_base64:
        return image.cached_base64, image.mime_type

    # Read from storage
    storage = get_image_storage()
    content = storage.read(image.storage_path)
    b64 = base64.b64encode(content).decode("utf-8")
    return b64, image.mime_type


def search_images(
    db: Session,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    query: Optional[str] = None,
    uploaded_by: Optional[str] = None,
) -> List[ImageAsset]:
    """Search images by metadata. Returns metadata only (no base64)."""
    q = db.query(ImageAsset).filter(ImageAsset.is_active == True)

    if category:
        q = q.filter(ImageAsset.category == category)
    if uploaded_by:
        q = q.filter(ImageAsset.uploaded_by == uploaded_by)
    if query:
        # Simple text search on filename and description
        search = f"%{query}%"
        q = q.filter(
            (ImageAsset.original_filename.ilike(search))
            | (ImageAsset.description.ilike(search))
        )
    # Tag filtering: check if any requested tag exists in the JSON array
    # PostgreSQL JSON containment: tags @> '["branding"]'
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

    # Note: Don't delete from storage on soft-delete.
    # Hard delete (storage cleanup) can be a future admin operation.
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
```

**Key differences from original plan:**
- Stateless functions that receive `db: Session` (matches codebase DI pattern)
- Storage abstraction with local fallback for development
- `get_image_base64` returns `(base64, mime_type)` tuple
- `search_images` returns metadata only (no base64 in list responses)
- Soft delete pattern matching `SlideStyleLibrary`
- Proper error handling order (validate -> thumbnail -> store -> DB)

### API Routes: `src/api/routes/images.py`

```python
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
    db: Session = Depends(get_db),
):
    """Upload an image file."""
    import json

    try:
        content = await file.read()
        parsed_tags = json.loads(tags) if tags else []
        user = _get_current_user()

        image = image_service.upload_image(
            db=db,
            file_content=content,
            original_filename=file.filename or "unknown",
            mime_type=file.content_type or "application/octet-stream",
            user=user,
            tags=parsed_tags,
            description=description,
            category=category,
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
    db: Session = Depends(get_db),
):
    """List images with optional filtering."""
    try:
        images = image_service.search_images(db=db, category=category, query=query)
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
```

### Route Registration

**`src/api/main.py`** - add import and include_router:
```python
from src.api.routes import images  # Add to existing imports

app.include_router(images.router)  # Add alongside other routers
```

---

## Agent Integration

### CRITICAL: Token Context Window

**DO NOT send raw base64 image data to the LLM.** A 5MB image = ~6.6MB base64 = catastrophic token usage.

Instead, the agent works with **image metadata only** and outputs **placeholder references** that are substituted after generation:

```
Agent receives: {"id": 42, "filename": "logo.png", "description": "Company logo", "tags": ["branding"]}
Agent outputs:  <img src="{{image:42}}" alt="Company logo" />
Post-processing: Replace {{image:42}} with data:image/png;base64,iVBOR...
```

### New Tool Functions: `src/services/image_tools.py`

```python
"""Image tools for the slide generator agent."""
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
    import json

    with get_db_session() as db:
        images = image_service.search_images(
            db=db,
            query=query,
            category=category,
            tags=tags,
        )

    # Return metadata only - NEVER base64
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
```

### Register Tool in Agent: `src/services/agent.py`

Add alongside existing Genie tools in `SlideGeneratorAgent.__init__`:

```python
from src.services.image_tools import SearchImagesInput, search_images

# In the tools list (alongside existing genie tools):
image_search_tool = StructuredTool.from_function(
    func=search_images,
    name="search_images",
    description=(
        "Search for uploaded images to include in slides. "
        "Use when user mentions images, logos, or branding. "
        "Returns image metadata with IDs. "
        "To embed an image, use: <img src=\"{{image:ID}}\" alt=\"description\" />"
    ),
    args_schema=SearchImagesInput,
)
```

### Post-Processing: Image Placeholder Substitution

Add a function to substitute `{{image:ID}}` placeholders with actual base64 data URIs.
This runs AFTER the agent generates HTML, BEFORE returning to the frontend:

```python
# src/utils/image_utils.py
"""Image placeholder substitution for generated slides."""
import logging
import re

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDER_PATTERN = re.compile(r"\{\{image:(\d+)\}\}")


def substitute_image_placeholders(html: str, db: Session) -> str:
    """
    Replace {{image:ID}} placeholders with base64 data URIs.

    Called after agent generates HTML, before returning to frontend.
    """
    from src.services import image_service

    def replace_match(match):
        image_id = int(match.group(1))
        try:
            b64_data, mime_type = image_service.get_image_base64(db, image_id)
            return f"data:{mime_type};base64,{b64_data}"
        except Exception as e:
            logger.warning(f"Failed to resolve image placeholder {{image:{image_id}}}: {e}")
            return match.group(0)  # Leave placeholder if image not found

    return IMAGE_PLACEHOLDER_PATTERN.sub(replace_match, html)
```

Call this in `chat_service.py` after agent response parsing, where the raw HTML is processed.

### System Prompt Update

Add image awareness to the system prompt (in the agent's `_create_prompt` or via ConfigPrompts):

```
You have access to user-uploaded images via the search_images tool.

When the user asks for branding, logos, or specific images:
1. Use search_images to find matching images
2. Embed them using: <img src="{{image:ID}}" alt="description" />
3. The system will replace {{image:ID}} with the actual image data

DO NOT attempt to generate or guess base64 image data. Always use the search_images tool
to find real uploaded images.
```

---

## Slide Style Integration (Branding)

**Design Principle**: All slide appearance (including branding logos) is controlled via `SlideStyleLibrary`. No separate profile-level branding fields.

### How it Works

The slide style's `style_content` CSS can reference images using the same `{{image:ID}}` placeholder syntax:

```css
/* Branding logo on every slide */
section {
  position: relative;
}

section::after {
  content: '';
  background-image: url('{{image:42}}');
  background-size: contain;
  background-repeat: no-repeat;
  position: absolute;
  top: 20px;
  right: 20px;
  width: 80px;
  height: 80px;
  z-index: 1000;
  pointer-events: none;
}
```

The `substitute_image_placeholders` function handles CSS too (same regex pattern works in both HTML and CSS contexts). It should run on `style_content` when styles are applied to slides.

### Slide Style Image References (Future Enhancement)

Optionally add an `image_refs` JSON column to `SlideStyleLibrary` for a cleaner mapping:

```python
# On SlideStyleLibrary model
image_refs = Column(JSON, default=dict)
# Example: {"logo": 42, "background": 15}
```

With named references in CSS:
```css
section::after {
  background-image: url('{{image_ref:logo}}');
}
```

This is a **nice-to-have** on top of the `{{image:ID}}` pattern - implement only if needed.

---

## Frontend Implementation

### TypeScript Types: `frontend/src/types/image.ts`

```typescript
export interface ImageAsset {
  id: number;
  filename: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  thumbnail_base64: string | null;  // Data URI for gallery display
  tags: string[];
  description: string | null;
  category: string | null;
  uploaded_by: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ImageListResponse {
  images: ImageAsset[];
  total: number;
}

export interface ImageDataResponse {
  id: number;
  mime_type: string;
  base64_data: string;
  data_uri: string;  // Ready to use in src=""
}
```

Note: `storage_path` is NOT exposed to frontend (internal implementation detail).

### API Methods: Add to `frontend/src/services/api.ts`

Add methods to the existing `api` object (do NOT create a separate `imageApi`):

```typescript
// Add to existing api object:

async uploadImage(
  file: File,
  metadata: { tags?: string[]; description?: string; category?: string }
): Promise<ImageAsset> {
  const formData = new FormData();
  formData.append('file', file);
  if (metadata.tags) formData.append('tags', JSON.stringify(metadata.tags));
  if (metadata.description) formData.append('description', metadata.description);
  if (metadata.category) formData.append('category', metadata.category);

  const response = await fetch(`${API_BASE_URL}/api/images/upload`, {
    method: 'POST',
    body: formData,
    // Note: do NOT set Content-Type header - browser sets it with boundary for FormData
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, error.detail || 'Upload failed');
  }
  return response.json();
},

async listImages(params?: { category?: string; query?: string }): Promise<ImageListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.category) searchParams.set('category', params.category);
  if (params?.query) searchParams.set('query', params.query);

  const url = `${API_BASE_URL}/api/images${searchParams.toString() ? '?' + searchParams : ''}`;
  const response = await fetch(url);
  if (!response.ok) throw new ApiError(response.status, 'Failed to list images');
  return response.json();
},

async getImageData(imageId: number): Promise<ImageDataResponse> {
  const response = await fetch(`${API_BASE_URL}/api/images/${imageId}/data`);
  if (!response.ok) throw new ApiError(response.status, 'Failed to get image data');
  return response.json();
},

async updateImage(
  imageId: number,
  updates: { tags?: string[]; description?: string; category?: string }
): Promise<ImageAsset> {
  const response = await fetch(`${API_BASE_URL}/api/images/${imageId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!response.ok) throw new ApiError(response.status, 'Failed to update image');
  return response.json();
},

async deleteImage(imageId: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/images/${imageId}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new ApiError(response.status, 'Failed to delete image');
},
```

### React Components

#### 1. Image Library: `frontend/src/components/ImageLibrary/ImageLibrary.tsx`

Gallery view with thumbnails. Key features:
- Grid layout using `thumbnail_base64` for display (no lazy-loading of full images)
- Search bar (calls `api.listImages({ query })`)
- Category filter dropdown
- Upload button (opens ImageUpload)
- Click image to select (for picker mode) or view details
- Delete/edit actions

#### 2. Image Upload: `frontend/src/components/ImageLibrary/ImageUpload.tsx`

- Drag-drop zone + file picker
- Client-side validation (file type, 5MB limit) BEFORE upload
- Preview of selected file
- Tag input, description, category selector
- Progress indicator during upload
- Calls `api.uploadImage(file, metadata)`

#### 3. Image Picker Modal: `frontend/src/components/ImageLibrary/ImagePicker.tsx`

Reusable modal that wraps ImageLibrary for selection:

```typescript
interface ImagePickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (image: ImageAsset) => void;
  filterCategory?: string;
}
```

Used in:
- Slide editor toolbar (insert image into HTML)
- Slide style editor (copy image reference for CSS)

#### 4. Slide Editor Integration

Add an "Insert Image" button to the slide editor toolbar. When clicked:
1. Opens ImagePicker modal
2. User selects an image
3. Fetches full base64 via `api.getImageData(image.id)`
4. Inserts `<img src="data:..." alt="..." />` at cursor position in Monaco editor

#### 5. Slide Style Editor Integration

Add an "Insert Image Reference" helper to the CSS editor. When clicked:
1. Opens ImagePicker modal
2. User selects an image
3. Copies `{{image:ID}}` to clipboard (or inserts at cursor)
4. User places it in CSS `url(...)` value

---

## User Workflows

### Workflow 1: Branding Logo via Slide Styles
1. User uploads logo via Image Library (category: "branding", tags: ["logo"])
2. User navigates to Slide Styles settings
3. User edits CSS, adds `section::after` with `background-image: url('{{image:42}}')`
4. Saves slide style
5. All future slides generated with this profile show the logo

### Workflow 2: Conversational Image Insertion
1. User: "Add our company logo to the title slide"
2. Agent calls `search_images(category="branding", tags=["logo"])`
3. Tool returns: `[{id: 42, filename: "acme-logo.png", description: "ACME Corp logo"}]`
4. Agent generates: `<img src="{{image:42}}" alt="ACME Corp logo" />`
5. Post-processing substitutes `{{image:42}}` with actual base64 data URI
6. Slide renders with embedded logo

### Workflow 3: Manual Image in Editor
1. User opens slide in Monaco editor
2. Clicks "Insert Image" toolbar button
3. ImagePicker modal opens, user searches and selects
4. Full base64 fetched, `<img>` tag inserted at cursor
5. User saves slide

### Workflow 4: Image Library Management
1. User opens Image Library from sidebar/settings
2. Grid of thumbnails loads (from `thumbnail_base64`, no additional requests)
3. User can search, filter, upload, edit metadata, delete

---

## PowerPoint Export Compatibility

Base64-embedded images work with the existing PPTX export pipeline because:
- `html_to_pptx.py` uses Playwright to screenshot HTML slides
- Playwright renders base64 data URIs natively
- The screenshot captures the image as rendered pixels
- No special handling needed

**Note**: PPTX file sizes will increase with image-heavy presentations. This is acceptable for MVP.

---

## Testing Strategy (TDD)

**Approach**: Tests are written FIRST, before implementation code. Each phase begins by
writing failing tests that define the expected behaviour, then implementing code to make
them pass.

### Codebase Test Conventions

The implementing agent MUST follow these exact patterns (observed from existing tests):

**Database test sessions** use in-memory SQLite with `StaticPool`:
```python
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.core.database import Base

@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create tables, skipping PostgreSQL-specific ones (config_history uses JSONB)
    tables_to_create = [
        t for t in Base.metadata.sorted_tables if t.name != "config_history"
    ]
    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)

    # Create simplified config_history (TEXT instead of JSONB)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS config_history (
                id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL, action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL, changes TEXT NOT NULL,
                snapshot TEXT, timestamp DATETIME NOT NULL
            )
        """))
        conn.commit()

    yield engine

    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
    engine.dispose()

@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()
```

**API route tests** use FastAPI `TestClient` with dependency overrides:
```python
from fastapi.testclient import TestClient
from src.api.main import app
from src.core.database import get_db

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

**Autouse fixtures** (from `conftest.py`, run automatically):
- `reset_singleton_client()` — resets Databricks client singleton
- `clear_settings_cache()` — clears `get_settings` LRU cache

**Mock patterns** — use `unittest.mock.patch` at the import location:
```python
with patch("src.services.image_service.get_image_storage") as mock:
    mock.return_value = MockStorage()
```

**Note**: This codebase has NO existing file upload tests. The `UploadFile`/`Form`/
multipart patterns are new. TestClient handles multipart via the `files` parameter:
```python
response = client.post("/api/images/upload", files={"file": ("logo.png", png_bytes, "image/png")}, data={"category": "branding", "tags": '["logo"]'})
```

---

### Test Fixtures: `tests/unit/conftest_images.py`

These fixtures should be added to a new conftest or to the existing `tests/conftest.py`:

```python
"""Shared fixtures for image feature tests."""
import io
import pytest
from unittest.mock import patch
from PIL import Image as PILImage

from src.database.models.image import ImageAsset


# --- Test Image Generators ---

@pytest.fixture
def png_1x1() -> bytes:
    """Minimal valid 1x1 red PNG image (< 1KB)."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", (1, 1), color=(255, 0, 0))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png_100x100() -> bytes:
    """100x100 PNG for thumbnail tests (large enough to resize)."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", (100, 100), color=(0, 128, 255))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png_rgba_100x100() -> bytes:
    """100x100 PNG with transparency (RGBA mode)."""
    buf = io.BytesIO()
    img = PILImage.new("RGBA", (100, 100), color=(0, 128, 255, 128))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def jpeg_100x100() -> bytes:
    """100x100 JPEG image."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", (100, 100), color=(0, 255, 0))
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def gif_animated() -> bytes:
    """Animated GIF with 3 frames."""
    frames = []
    for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]:
        frames.append(PILImage.new("RGB", (50, 50), color=color))
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


@pytest.fixture
def svg_content() -> bytes:
    """Minimal SVG content."""
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect fill="red" width="100" height="100"/></svg>'


@pytest.fixture
def oversized_content() -> bytes:
    """Content exceeding 5MB limit."""
    return b"x" * (5 * 1024 * 1024 + 1)


# --- Mock Storage ---

class MockImageStorage:
    """In-memory storage backend for tests."""

    def __init__(self):
        self._store: dict[str, bytes] = {}

    def write(self, path: str, content: bytes) -> None:
        self._store[path] = content

    def read(self, path: str) -> bytes:
        if path not in self._store:
            raise FileNotFoundError(f"Mock storage: {path} not found")
        return self._store[path]

    def delete(self, path: str) -> None:
        self._store.pop(path, None)

    def exists(self, path: str) -> bool:
        return path in self._store


@pytest.fixture
def mock_storage():
    """Provide a MockImageStorage and patch get_image_storage to return it."""
    storage = MockImageStorage()
    with patch("src.services.image_service.get_image_storage", return_value=storage):
        yield storage


# --- Database Helpers ---

def create_test_image(db_session, **overrides) -> ImageAsset:
    """Helper to create an ImageAsset in the test DB with sensible defaults."""
    from datetime import datetime
    defaults = dict(
        filename="test-uuid.png",
        original_filename="test.png",
        mime_type="image/png",
        size_bytes=1234,
        storage_path="system/test-uuid.png",
        thumbnail_base64="data:image/jpeg;base64,/9j/4AAQ",
        tags=["test"],
        description="Test image",
        category="content",
        uploaded_by="system",
        is_active=True,
        created_by="system",
        updated_by="system",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    image = ImageAsset(**defaults)
    db_session.add(image)
    db_session.commit()
    db_session.refresh(image)
    return image
```

---

### Phase 1 Tests: Image Service (`tests/unit/test_image_service.py`)

Write these tests BEFORE implementing `src/services/image_service.py`.

```python
"""Unit tests for image upload, thumbnail, search, and delete service."""
import base64
import pytest
from unittest.mock import patch

from src.services import image_service
from src.database.models.image import ImageAsset
from tests.unit.conftest_images import create_test_image, MockImageStorage


# ===== Upload Validation =====

class TestUploadValidation:
    """Tests for upload_image input validation (fail-fast, no side effects)."""

    def test_rejects_invalid_mime_type(self, db_session, mock_storage, png_1x1):
        with pytest.raises(ValueError, match="File type not allowed"):
            image_service.upload_image(
                db=db_session, file_content=png_1x1,
                original_filename="test.bmp", mime_type="image/bmp",
                user="test",
            )
        # Storage should NOT have been written to
        assert len(mock_storage._store) == 0

    def test_rejects_oversized_file(self, db_session, mock_storage, oversized_content):
        with pytest.raises(ValueError, match="File too large"):
            image_service.upload_image(
                db=db_session, file_content=oversized_content,
                original_filename="big.png", mime_type="image/png",
                user="test",
            )
        assert len(mock_storage._store) == 0

    def test_accepts_png(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="testuser",
        )
        assert result.id is not None
        assert result.mime_type == "image/png"
        assert result.original_filename == "logo.png"
        assert result.size_bytes == len(png_1x1)
        assert result.uploaded_by == "testuser"
        assert result.is_active is True

    def test_accepts_jpeg(self, db_session, mock_storage, jpeg_100x100):
        result = image_service.upload_image(
            db=db_session, file_content=jpeg_100x100,
            original_filename="photo.jpg", mime_type="image/jpeg",
            user="test",
        )
        assert result.mime_type == "image/jpeg"

    def test_accepts_gif(self, db_session, mock_storage, gif_animated):
        result = image_service.upload_image(
            db=db_session, file_content=gif_animated,
            original_filename="anim.gif", mime_type="image/gif",
            user="test",
        )
        assert result.mime_type == "image/gif"

    def test_accepts_svg(self, db_session, mock_storage, svg_content):
        result = image_service.upload_image(
            db=db_session, file_content=svg_content,
            original_filename="icon.svg", mime_type="image/svg+xml",
            user="test",
        )
        assert result.mime_type == "image/svg+xml"
        assert result.thumbnail_base64 is None  # SVGs have no thumbnail


# ===== Upload Storage & Metadata =====

class TestUploadStorageAndMetadata:
    """Tests that upload correctly writes to storage and DB."""

    def test_writes_file_to_storage(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="testuser",
        )
        # File should exist in mock storage at expected path
        assert mock_storage.exists(result.storage_path)
        assert mock_storage.read(result.storage_path) == png_1x1

    def test_storage_path_contains_user_and_uuid(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="alice@example.com",
        )
        assert result.storage_path.startswith("alice@example.com/")
        assert result.storage_path.endswith(".png")

    def test_saves_tags_and_description(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test", tags=["branding", "logo"], description="Company logo",
        )
        assert result.tags == ["branding", "logo"]
        assert result.description == "Company logo"

    def test_saves_category(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test", category="branding",
        )
        assert result.category == "branding"

    def test_default_category_is_content(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test",
        )
        assert result.category == "content"

    def test_branding_category_pre_caches_base64(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test", category="branding",
        )
        assert result.cached_base64 is not None
        assert result.cached_base64 == base64.b64encode(png_1x1).decode("utf-8")

    def test_content_category_does_not_cache(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test", category="content",
        )
        assert result.cached_base64 is None

    def test_sets_created_by_and_updated_by(self, db_session, mock_storage, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="alice",
        )
        assert result.created_by == "alice"
        assert result.updated_by == "alice"


# ===== Thumbnail Generation =====

class TestThumbnailGeneration:
    """Tests for _generate_thumbnail internal function."""

    def test_generates_for_png(self, png_100x100):
        thumb = image_service._generate_thumbnail(png_100x100, "image/png")
        assert thumb is not None
        assert thumb.startswith("data:image/")
        assert ";base64," in thumb

    def test_generates_for_jpeg(self, jpeg_100x100):
        thumb = image_service._generate_thumbnail(jpeg_100x100, "image/jpeg")
        assert thumb is not None
        assert thumb.startswith("data:image/jpeg;base64,")

    def test_generates_for_rgba_png(self, png_rgba_100x100):
        thumb = image_service._generate_thumbnail(png_rgba_100x100, "image/png")
        assert thumb is not None
        # RGBA images should produce PNG thumbnails (to preserve transparency)
        assert thumb.startswith("data:image/png;base64,")

    def test_extracts_first_frame_from_animated_gif(self, gif_animated):
        thumb = image_service._generate_thumbnail(gif_animated, "image/gif")
        assert thumb is not None
        # Result should be a static image (not animated)
        assert thumb.startswith("data:image/")

    def test_returns_none_for_svg(self, svg_content):
        thumb = image_service._generate_thumbnail(svg_content, "image/svg+xml")
        assert thumb is None

    def test_thumbnail_is_reasonable_size(self, png_100x100):
        thumb = image_service._generate_thumbnail(png_100x100, "image/png")
        # Thumbnail base64 should be small (< 50KB for a 100x100 source)
        assert len(thumb) < 50_000

    def test_upload_stores_thumbnail_in_db(self, db_session, mock_storage, png_100x100):
        result = image_service.upload_image(
            db=db_session, file_content=png_100x100,
            original_filename="test.png", mime_type="image/png",
            user="test",
        )
        assert result.thumbnail_base64 is not None
        assert result.thumbnail_base64.startswith("data:image/")


# ===== get_image_base64 =====

class TestGetImageBase64:
    """Tests for retrieving full image as base64."""

    def test_returns_from_cache_when_available(self, db_session, mock_storage):
        image = create_test_image(db_session, cached_base64="CACHED_DATA", mime_type="image/png")
        b64, mime = image_service.get_image_base64(db_session, image.id)
        assert b64 == "CACHED_DATA"
        assert mime == "image/png"
        # Should NOT have read from storage
        assert len(mock_storage._store) == 0

    def test_reads_from_storage_when_no_cache(self, db_session, mock_storage, png_1x1):
        image = create_test_image(db_session, cached_base64=None, storage_path="user/img.png")
        mock_storage.write("user/img.png", png_1x1)

        b64, mime = image_service.get_image_base64(db_session, image.id)
        assert b64 == base64.b64encode(png_1x1).decode("utf-8")
        assert mime == "image/png"

    def test_raises_for_nonexistent_image(self, db_session, mock_storage):
        with pytest.raises(ValueError, match="not found"):
            image_service.get_image_base64(db_session, 99999)

    def test_raises_for_inactive_image(self, db_session, mock_storage):
        image = create_test_image(db_session, is_active=False)
        with pytest.raises(ValueError, match="not found"):
            image_service.get_image_base64(db_session, image.id)


# ===== Search =====

class TestSearchImages:
    """Tests for image search/filtering."""

    def test_returns_all_active_images(self, db_session, mock_storage):
        create_test_image(db_session, original_filename="a.png")
        create_test_image(db_session, original_filename="b.png")
        create_test_image(db_session, original_filename="c.png", is_active=False)

        results = image_service.search_images(db_session)
        assert len(results) == 2

    def test_filter_by_category(self, db_session, mock_storage):
        create_test_image(db_session, category="branding", original_filename="logo.png")
        create_test_image(db_session, category="content", original_filename="chart.png")

        results = image_service.search_images(db_session, category="branding")
        assert len(results) == 1
        assert results[0].category == "branding"

    def test_filter_by_tags(self, db_session, mock_storage):
        create_test_image(db_session, tags=["branding", "logo"], original_filename="logo.png")
        create_test_image(db_session, tags=["chart", "q4"], original_filename="chart.png")

        results = image_service.search_images(db_session, tags=["branding"])
        assert len(results) == 1
        assert "branding" in results[0].tags

    def test_filter_by_query_text_filename(self, db_session, mock_storage):
        create_test_image(db_session, original_filename="acme-logo.png")
        create_test_image(db_session, original_filename="chart-q4.png")

        results = image_service.search_images(db_session, query="acme")
        assert len(results) == 1
        assert "acme" in results[0].original_filename

    def test_filter_by_query_text_description(self, db_session, mock_storage):
        create_test_image(db_session, description="ACME Corp logo", original_filename="a.png")
        create_test_image(db_session, description="Revenue chart", original_filename="b.png")

        results = image_service.search_images(db_session, query="ACME")
        assert len(results) == 1

    def test_excludes_inactive(self, db_session, mock_storage):
        create_test_image(db_session, is_active=True, original_filename="visible.png")
        create_test_image(db_session, is_active=False, original_filename="hidden.png")

        results = image_service.search_images(db_session)
        assert all(r.is_active for r in results)

    def test_ordered_by_newest_first(self, db_session, mock_storage):
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        create_test_image(db_session, original_filename="old.png", created_at=now - timedelta(days=1))
        create_test_image(db_session, original_filename="new.png", created_at=now)

        results = image_service.search_images(db_session)
        assert results[0].original_filename == "new.png"


# ===== Soft Delete =====

class TestDeleteImage:
    """Tests for soft-delete."""

    def test_sets_inactive(self, db_session, mock_storage):
        image = create_test_image(db_session)
        image_service.delete_image(db_session, image.id, "admin")

        refreshed = db_session.query(ImageAsset).get(image.id)
        assert refreshed.is_active is False

    def test_sets_updated_by(self, db_session, mock_storage):
        image = create_test_image(db_session)
        image_service.delete_image(db_session, image.id, "admin@example.com")

        refreshed = db_session.query(ImageAsset).get(image.id)
        assert refreshed.updated_by == "admin@example.com"

    def test_raises_for_nonexistent(self, db_session, mock_storage):
        with pytest.raises(ValueError, match="not found"):
            image_service.delete_image(db_session, 99999, "admin")

    def test_does_not_delete_from_storage(self, db_session, mock_storage, png_1x1):
        image = create_test_image(db_session, storage_path="user/img.png")
        mock_storage.write("user/img.png", png_1x1)

        image_service.delete_image(db_session, image.id, "admin")

        # File should still exist in storage (soft delete only)
        assert mock_storage.exists("user/img.png")
```

---

### Phase 1 Tests: API Routes (`tests/integration/test_image_api.py`)

Write these tests BEFORE implementing `src/api/routes/images.py`.

```python
"""Integration tests for image API endpoints using TestClient."""
import json
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models.image import ImageAsset
from tests.unit.conftest_images import create_test_image, MockImageStorage


# --- Fixtures ---

@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables_to_create = [
        t for t in Base.metadata.sorted_tables if t.name != "config_history"
    ]
    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS config_history (
                id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL, action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL, changes TEXT NOT NULL,
                snapshot TEXT, timestamp DATETIME NOT NULL
            )
        """))
        conn.commit()
    yield engine
    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def mock_storage():
    storage = MockImageStorage()
    with patch("src.services.image_service.get_image_storage", return_value=storage):
        yield storage


@pytest.fixture(scope="function")
def client(db_session, mock_storage):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def png_bytes() -> bytes:
    """Minimal valid PNG for upload tests."""
    import io
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


# --- Upload Endpoint Tests ---

class TestUploadEndpoint:
    """POST /api/images/upload"""

    def test_upload_returns_201(self, client, png_bytes):
        response = client.post(
            "/api/images/upload",
            files={"file": ("logo.png", png_bytes, "image/png")},
            data={"category": "branding", "tags": '["logo"]'},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["original_filename"] == "logo.png"
        assert data["mime_type"] == "image/png"
        assert data["category"] == "branding"
        assert data["tags"] == ["logo"]
        assert data["id"] is not None
        assert data["thumbnail_base64"] is not None

    def test_upload_rejects_invalid_type(self, client):
        response = client.post(
            "/api/images/upload",
            files={"file": ("test.txt", b"not an image", "text/plain")},
        )
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_upload_rejects_oversized(self, client):
        big = b"x" * (5 * 1024 * 1024 + 1)
        response = client.post(
            "/api/images/upload",
            files={"file": ("big.png", big, "image/png")},
        )
        assert response.status_code == 400
        assert "too large" in response.json()["detail"]

    def test_upload_without_file_returns_422(self, client):
        response = client.post("/api/images/upload")
        assert response.status_code == 422

    def test_upload_default_category_is_content(self, client, png_bytes):
        response = client.post(
            "/api/images/upload",
            files={"file": ("test.png", png_bytes, "image/png")},
        )
        assert response.status_code == 201
        assert response.json()["category"] == "content"


# --- List Endpoint Tests ---

class TestListEndpoint:
    """GET /api/images"""

    def test_list_empty(self, client):
        response = client.get("/api/images")
        assert response.status_code == 200
        data = response.json()
        assert data["images"] == []
        assert data["total"] == 0

    def test_list_returns_uploaded_images(self, client, db_session):
        create_test_image(db_session, original_filename="a.png")
        create_test_image(db_session, original_filename="b.png")

        response = client.get("/api/images")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_list_filter_by_category(self, client, db_session):
        create_test_image(db_session, category="branding", original_filename="logo.png")
        create_test_image(db_session, category="content", original_filename="chart.png")

        response = client.get("/api/images?category=branding")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["images"][0]["category"] == "branding"

    def test_list_filter_by_query(self, client, db_session):
        create_test_image(db_session, original_filename="acme-logo.png")
        create_test_image(db_session, original_filename="chart-q4.png")

        response = client.get("/api/images?query=acme")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_list_excludes_inactive(self, client, db_session):
        create_test_image(db_session, is_active=True, original_filename="visible.png")
        create_test_image(db_session, is_active=False, original_filename="hidden.png")

        response = client.get("/api/images")
        assert response.json()["total"] == 1


# --- Get Single Image Tests ---

class TestGetImageEndpoint:
    """GET /api/images/{id}"""

    def test_returns_image_metadata(self, client, db_session):
        image = create_test_image(db_session, original_filename="logo.png")

        response = client.get(f"/api/images/{image.id}")
        assert response.status_code == 200
        assert response.json()["original_filename"] == "logo.png"

    def test_returns_404_for_nonexistent(self, client):
        response = client.get("/api/images/99999")
        assert response.status_code == 404

    def test_returns_404_for_inactive(self, client, db_session):
        image = create_test_image(db_session, is_active=False)
        response = client.get(f"/api/images/{image.id}")
        assert response.status_code == 404


# --- Get Image Data Tests ---

class TestGetImageDataEndpoint:
    """GET /api/images/{id}/data"""

    def test_returns_base64_data(self, client, db_session, mock_storage, png_bytes):
        image = create_test_image(
            db_session, storage_path="user/img.png", cached_base64=None,
        )
        mock_storage.write("user/img.png", png_bytes)

        response = client.get(f"/api/images/{image.id}/data")
        assert response.status_code == 200
        data = response.json()
        assert data["mime_type"] == "image/png"
        assert data["base64_data"] is not None
        assert data["data_uri"].startswith("data:image/png;base64,")

    def test_returns_404_for_nonexistent(self, client):
        response = client.get("/api/images/99999/data")
        assert response.status_code == 404


# --- Update Tests ---

class TestUpdateEndpoint:
    """PUT /api/images/{id}"""

    def test_update_tags(self, client, db_session):
        image = create_test_image(db_session, tags=["old"])

        response = client.put(
            f"/api/images/{image.id}",
            json={"tags": ["new", "tags"]},
        )
        assert response.status_code == 200
        assert response.json()["tags"] == ["new", "tags"]

    def test_update_description(self, client, db_session):
        image = create_test_image(db_session, description="old")

        response = client.put(
            f"/api/images/{image.id}",
            json={"description": "new description"},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "new description"

    def test_update_returns_404_for_nonexistent(self, client):
        response = client.put("/api/images/99999", json={"tags": ["x"]})
        assert response.status_code == 404


# --- Delete Tests ---

class TestDeleteEndpoint:
    """DELETE /api/images/{id}"""

    def test_delete_returns_204(self, client, db_session):
        image = create_test_image(db_session)

        response = client.delete(f"/api/images/{image.id}")
        assert response.status_code == 204

    def test_deleted_image_no_longer_listed(self, client, db_session):
        image = create_test_image(db_session)
        client.delete(f"/api/images/{image.id}")

        response = client.get("/api/images")
        assert response.json()["total"] == 0

    def test_delete_returns_404_for_nonexistent(self, client):
        response = client.delete("/api/images/99999")
        assert response.status_code == 404
```

---

### Phase 2 Tests: Image Placeholder Substitution (`tests/unit/test_image_utils.py`)

Write BEFORE implementing `src/utils/image_utils.py`.

```python
"""Unit tests for {{image:ID}} placeholder substitution."""
import pytest
from unittest.mock import patch

from src.utils.image_utils import substitute_image_placeholders


class TestSubstituteImagePlaceholders:
    """Tests for replacing {{image:ID}} with base64 data URIs."""

    def test_substitutes_single_placeholder(self, db_session):
        html = '<img src="{{image:42}}" alt="logo" />'
        with patch("src.services.image_service.get_image_base64") as mock:
            mock.return_value = ("BASE64DATA", "image/png")
            result = substitute_image_placeholders(html, db_session)

        assert result == '<img src="data:image/png;base64,BASE64DATA" alt="logo" />'

    def test_substitutes_multiple_placeholders(self, db_session):
        html = '<img src="{{image:1}}" /><img src="{{image:2}}" />'
        with patch("src.services.image_service.get_image_base64") as mock:
            mock.side_effect = [
                ("DATA_1", "image/png"),
                ("DATA_2", "image/jpeg"),
            ]
            result = substitute_image_placeholders(html, db_session)

        assert "data:image/png;base64,DATA_1" in result
        assert "data:image/jpeg;base64,DATA_2" in result

    def test_preserves_html_without_placeholders(self, db_session):
        html = '<h1>Hello World</h1><img src="data:image/png;base64,existing" />'
        result = substitute_image_placeholders(html, db_session)
        assert result == html

    def test_leaves_unresolved_placeholder_on_missing_image(self, db_session):
        html = '<img src="{{image:999}}" />'
        with patch("src.services.image_service.get_image_base64") as mock:
            mock.side_effect = ValueError("not found")
            result = substitute_image_placeholders(html, db_session)

        # Placeholder should remain (graceful degradation)
        assert "{{image:999}}" in result

    def test_works_in_css_url_context(self, db_session):
        css = "section::after { background-image: url('{{image:42}}'); }"
        with patch("src.services.image_service.get_image_base64") as mock:
            mock.return_value = ("BASE64", "image/png")
            result = substitute_image_placeholders(css, db_session)

        assert "url('data:image/png;base64,BASE64')" in result

    def test_handles_empty_string(self, db_session):
        assert substitute_image_placeholders("", db_session) == ""

    def test_mixed_resolved_and_unresolved(self, db_session):
        html = '<img src="{{image:1}}" /><img src="{{image:999}}" />'
        with patch("src.services.image_service.get_image_base64") as mock:
            def side_effect(db, image_id):
                if image_id == 1:
                    return ("OK_DATA", "image/png")
                raise ValueError("not found")
            mock.side_effect = side_effect
            result = substitute_image_placeholders(html, db_session)

        assert "data:image/png;base64,OK_DATA" in result
        assert "{{image:999}}" in result
```

---

### Phase 2 Tests: Agent Image Tool (`tests/unit/test_image_tools.py`)

Write BEFORE implementing `src/services/image_tools.py`.

```python
"""Unit tests for the search_images agent tool."""
import json
import pytest
from unittest.mock import patch, MagicMock

from src.services.image_tools import search_images


class TestSearchImagesTool:
    """Tests for the agent's search_images tool function."""

    def test_returns_json_string(self):
        mock_image = MagicMock()
        mock_image.id = 1
        mock_image.original_filename = "logo.png"
        mock_image.description = "Company logo"
        mock_image.tags = ["branding"]
        mock_image.category = "branding"
        mock_image.mime_type = "image/png"

        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = [mock_image]

            result = search_images(category="branding")

        parsed = json.loads(result)
        assert len(parsed["images"]) == 1
        assert parsed["images"][0]["id"] == 1
        assert parsed["images"][0]["filename"] == "logo.png"

    def test_returns_usage_hint_with_placeholder(self):
        mock_image = MagicMock()
        mock_image.id = 42
        mock_image.original_filename = "logo.png"
        mock_image.description = "Logo"
        mock_image.tags = []
        mock_image.category = "branding"
        mock_image.mime_type = "image/png"

        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = [mock_image]

            result = search_images()

        parsed = json.loads(result)
        # Tool should tell agent how to use the image
        assert "{{image:42}}" in parsed["images"][0]["usage"]

    def test_does_not_include_base64(self):
        mock_image = MagicMock()
        mock_image.id = 1
        mock_image.original_filename = "logo.png"
        mock_image.description = ""
        mock_image.tags = []
        mock_image.category = "content"
        mock_image.mime_type = "image/png"

        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = [mock_image]

            result = search_images()

        # CRITICAL: base64 data must NEVER appear in tool results
        parsed = json.loads(result)
        for img in parsed["images"]:
            assert "base64_data" not in img
            assert "cached_base64" not in img

    def test_returns_empty_message_when_no_results(self):
        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = []

            result = search_images(query="nonexistent")

        parsed = json.loads(result)
        assert parsed["images"] == []
        assert "No images found" in parsed["message"]
```

---

### Phase 3 Tests: Frontend E2E (`frontend/tests/e2e/image-library.spec.ts`)

Write BEFORE building frontend components. These use the Playwright mock patterns
established in the codebase (see `frontend/tests/fixtures/mocks.ts` and
`frontend/tests/e2e/profile-ui.spec.ts` for reference).

```typescript
import { test, expect } from '../fixtures/base-test';

// --- Mock Data ---

const mockImages = {
  images: [
    {
      id: 1,
      filename: "uuid-1.png",
      original_filename: "logo.png",
      mime_type: "image/png",
      size_bytes: 12345,
      thumbnail_base64: "data:image/jpeg;base64,/9j/4AAQ",
      tags: ["branding", "logo"],
      description: "Company logo",
      category: "branding",
      uploaded_by: "test@example.com",
      is_active: true,
      created_at: "2026-02-09T10:00:00",
      updated_at: "2026-02-09T10:00:00",
    },
    {
      id: 2,
      filename: "uuid-2.png",
      original_filename: "chart-q4.png",
      mime_type: "image/png",
      size_bytes: 54321,
      thumbnail_base64: "data:image/jpeg;base64,/9j/4BBQ",
      tags: ["chart"],
      description: "Q4 revenue chart",
      category: "content",
      uploaded_by: "test@example.com",
      is_active: true,
      created_at: "2026-02-09T11:00:00",
      updated_at: "2026-02-09T11:00:00",
    },
  ],
  total: 2,
};

const mockUploadResponse = {
  id: 3,
  filename: "uuid-3.png",
  original_filename: "new-image.png",
  mime_type: "image/png",
  size_bytes: 9999,
  thumbnail_base64: "data:image/jpeg;base64,/9j/4CCQ",
  tags: [],
  description: null,
  category: "content",
  uploaded_by: "test@example.com",
  is_active: true,
  created_at: "2026-02-09T12:00:00",
  updated_at: "2026-02-09T12:00:00",
};


// --- Mock Setup ---

async function setupImageMocks(page) {
  // Mock GET /api/images
  await page.route('**/api/images', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockImages),
      });
    }
  });

  // Mock POST /api/images/upload
  await page.route('**/api/images/upload', (route) => {
    route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(mockUploadResponse),
    });
  });

  // Mock GET /api/images/:id
  await page.route(/\/api\/images\/\d+$/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockImages.images[0]),
    });
  });

  // Mock DELETE /api/images/:id
  await page.route(/\/api\/images\/\d+$/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({ status: 204 });
    }
  });

  // Also mock existing endpoints needed for page load
  // (profiles, sessions, etc. — copy from existing mocks.ts)
}


// --- Tests ---

test.describe('Image Library', () => {
  test('displays uploaded images in gallery', async ({ page }) => {
    await setupImageMocks(page);
    await page.goto('/');
    // Navigate to image library (adjust selector based on actual UI)
    await page.click('[data-testid="image-library-nav"]');

    // Should display both images
    await expect(page.locator('[data-testid="image-grid-item"]')).toHaveCount(2);
    await expect(page).toContainText('logo.png');
    await expect(page).toContainText('chart-q4.png');
  });

  test('filters images by category', async ({ page }) => {
    await setupImageMocks(page);
    await page.goto('/');
    await page.click('[data-testid="image-library-nav"]');

    // Select branding filter
    await page.selectOption('[data-testid="category-filter"]', 'branding');

    // Mock should be called with category param (verify via route)
    // UI should show filtered results
  });

  test('searches images by name', async ({ page }) => {
    await setupImageMocks(page);
    await page.goto('/');
    await page.click('[data-testid="image-library-nav"]');

    await page.fill('[data-testid="image-search"]', 'logo');
    // Verify search triggers API call with query param
  });
});


test.describe('Image Upload', () => {
  test('uploads image via file picker', async ({ page }) => {
    await setupImageMocks(page);
    await page.goto('/');
    await page.click('[data-testid="image-library-nav"]');
    await page.click('[data-testid="upload-button"]');

    // Create a test file and upload
    const buffer = Buffer.from('fake-png-content');
    await page.setInputFiles('[data-testid="file-input"]', {
      name: 'test.png',
      mimeType: 'image/png',
      buffer,
    });

    // Should show preview and upload button
    await expect(page.locator('[data-testid="upload-preview"]')).toBeVisible();
    await page.click('[data-testid="confirm-upload"]');

    // Should show success
    await expect(page).toContainText('new-image.png');
  });

  test('rejects non-image files client-side', async ({ page }) => {
    await setupImageMocks(page);
    await page.goto('/');
    await page.click('[data-testid="image-library-nav"]');
    await page.click('[data-testid="upload-button"]');

    // Try uploading a text file
    const buffer = Buffer.from('not an image');
    await page.setInputFiles('[data-testid="file-input"]', {
      name: 'test.txt',
      mimeType: 'text/plain',
      buffer,
    });

    // Should show validation error, NOT submit to server
    await expect(page.locator('[data-testid="upload-error"]')).toBeVisible();
  });
});


test.describe('Image Deletion', () => {
  test('deletes image and removes from gallery', async ({ page }) => {
    await setupImageMocks(page);
    await page.goto('/');
    await page.click('[data-testid="image-library-nav"]');

    // Click delete on first image
    await page.click('[data-testid="image-delete-1"]');

    // Confirm deletion dialog
    await page.click('[data-testid="confirm-delete"]');

    // Image should be removed from view
  });
});
```

**Note on `data-testid` attributes**: The implementing agent should add these to
components as they're built. The selectors above are conventions — adjust to match
actual component implementation. The key is that E2E tests mock the API at the network
level (via `page.route()`) and assert on visible UI state.

---

### TDD Execution Order

For each phase, follow this cycle:

1. **Write test file** with all tests for the phase (they will all fail)
2. **Run tests** to confirm they fail for the right reason (`ImportError`, `AssertionError`, etc.)
3. **Implement the minimum code** to make tests pass
4. **Run tests** to confirm they pass
5. **Refactor** if needed (tests should still pass)
6. **Move to next phase**

```bash
# Phase 1: Service + API tests
pytest tests/unit/test_image_service.py -v      # All fail initially
pytest tests/integration/test_image_api.py -v   # All fail initially
# ... implement ... #
pytest tests/unit/test_image_service.py tests/integration/test_image_api.py -v  # All pass

# Phase 2: Tool + substitution tests
pytest tests/unit/test_image_utils.py tests/unit/test_image_tools.py -v  # All fail
# ... implement ... #
pytest tests/unit/ -v  # All pass

# Phase 3: Frontend E2E
cd frontend && npx playwright test tests/e2e/image-library.spec.ts  # All fail
# ... implement ... #
cd frontend && npx playwright test tests/e2e/image-library.spec.ts  # All pass
```

## Design Decisions (Finalized)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Image optimization | None for MVP | 5MB size limit is sufficient |
| Thumbnail storage | `thumbnail_base64` column in images table | Fast gallery (one query, no storage reads) |
| Size limit | 5MB per image | Reasonable for logos/charts |
| Animated GIFs | Supported | First frame for thumbnail, full GIF in storage |
| Branding integration | Via Slide Styles CSS | Single source of truth for appearance |
| Agent image handling | Metadata only + placeholders | Avoid blowing up LLM context window |
| Local development | Filesystem fallback | UC Volumes unavailable locally |
| Sharing/Permissions | Deferred | Separate permissions branch in progress |

---

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Add `Pillow` dependency to `pyproject.toml`
- [ ] Create `ImageAsset` model in `src/database/models/image.py`
- [ ] Register model in `src/database/models/__init__.py`
- [ ] Create storage abstraction: `src/services/image_storage.py`
- [ ] Create image service: `src/services/image_service.py`
- [ ] Create API routes: `src/api/routes/images.py`
- [ ] Register routes in `src/api/main.py`
- [ ] Write unit tests for service and routes

### Phase 2: Agent Integration
- [ ] Create image tools: `src/services/image_tools.py`
- [ ] Register `search_images` tool in `src/services/agent.py`
- [ ] Create placeholder substitution: `src/utils/image_utils.py`
- [ ] Wire substitution into `chat_service.py` post-processing
- [ ] Update system prompt with image instructions
- [ ] Write tests for tools and substitution

### Phase 3: Frontend - Image Library
- [ ] Create TypeScript types: `frontend/src/types/image.ts`
- [ ] Add API methods to `frontend/src/services/api.ts`
- [ ] Build ImageLibrary component (gallery with thumbnails)
- [ ] Build ImageUpload component (drag-drop + validation)
- [ ] Build ImagePicker modal
- [ ] Add navigation/sidebar entry for Image Library
- [ ] Write E2E tests

### Phase 4: Frontend - Editor Integration
- [ ] Add "Insert Image" button to slide editor toolbar
- [ ] Wire ImagePicker to Monaco editor insertion
- [ ] Add image reference helper to slide style CSS editor
- [ ] Verify PPTX export works with embedded images
- [ ] Write E2E tests for editor integration

### Phase 5: Polish (Post-MVP)
- [ ] Image optimization on upload (resize large images)
- [ ] Named image references in slide styles (`image_refs` column)
- [ ] Bulk upload/delete
- [ ] Image usage tracking (which slides reference which images)
- [ ] Hard delete with storage cleanup (admin operation)
