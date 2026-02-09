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

## Testing Strategy

### Backend Unit Tests: `tests/unit/test_image_service.py`

```python
# Test upload validation
def test_upload_rejects_invalid_mime_type()
def test_upload_rejects_oversized_file()
def test_upload_accepts_valid_png()
def test_upload_accepts_valid_gif()

# Test thumbnail generation
def test_thumbnail_generates_for_png()
def test_thumbnail_generates_for_jpeg()
def test_thumbnail_extracts_gif_first_frame()
def test_thumbnail_returns_none_for_svg()

# Test search
def test_search_by_category()
def test_search_by_tags()
def test_search_by_query_text()
def test_search_excludes_inactive()

# Test base64 retrieval
def test_get_base64_from_cache()
def test_get_base64_from_storage()

# Test soft delete
def test_delete_sets_inactive()
def test_deleted_images_hidden_from_search()

# Test image placeholder substitution
def test_substitute_single_placeholder()
def test_substitute_multiple_placeholders()
def test_substitute_preserves_unresolved_placeholders()
def test_substitute_handles_missing_image_gracefully()
```

### Backend Integration Tests: `tests/integration/test_image_api.py`

```python
@pytest.mark.integration
def test_upload_and_retrieve_image()
def test_list_images_with_filters()
def test_delete_image_soft()
def test_get_image_data_returns_base64()
```

### Frontend E2E Tests: `frontend/tests/e2e/image-upload.spec.ts`

```typescript
test('upload image and verify in library')
test('search images by name')
test('insert image into slide editor')
test('delete image from library')
```

### Mocking Strategy

For unit tests, mock the storage backend:

```python
@pytest.fixture
def mock_storage(monkeypatch):
    storage = {}

    class MockStorage:
        def write(self, path, content):
            storage[path] = content
        def read(self, path):
            return storage[path]
        def delete(self, path):
            storage.pop(path, None)
        def exists(self, path):
            return path in storage

    monkeypatch.setattr(
        "src.services.image_service.get_image_storage",
        lambda: MockStorage()
    )
    return storage
```

---

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
