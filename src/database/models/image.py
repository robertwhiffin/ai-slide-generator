"""Image asset model — metadata and binary data stored together in Lakebase."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSON

from src.core.database import Base


class ImageAsset(Base):
    """Uploaded image with binary data stored directly in PostgreSQL.

    All image data lives in this table — no external storage dependencies.
    The image_data column stores raw bytes (PostgreSQL bytea type).
    Base64 encoding is done on read when needed for HTML embedding.
    """

    __tablename__ = "image_assets"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)           # Generated: {uuid}.{ext}
    original_filename = Column(String(255), nullable=False)  # User's original filename
    mime_type = Column(String(50), nullable=False)           # image/png, image/jpeg, image/gif, image/svg+xml
    size_bytes = Column(Integer, nullable=False)

    # Raw image bytes (PostgreSQL bytea, max ~5MB enforced at application level)
    image_data = Column(LargeBinary, nullable=False)

    # Thumbnail (150x150, auto-generated on upload)
    # Stored as data URI: "data:image/jpeg;base64,..."
    # For SVGs: stores None (render as-is in UI, they scale natively)
    thumbnail_base64 = Column(Text, nullable=True)

    # Organization
    tags = Column(JSON, default=list)                        # ["branding", "logo", "chart"]
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)             # 'branding', 'content', 'background', 'ephemeral'

    # Ownership (no FK to profiles - images are independent library items)
    uploaded_by = Column(String(255), nullable=True)

    # Soft delete
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps + user tracking
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<ImageAsset(id={self.id}, filename='{self.filename}', category='{self.category}')>"
