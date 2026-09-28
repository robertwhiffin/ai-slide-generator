"""Offloaded storage for generated slide-style previews.

Slide-style previews are model-generated sample decks that can be image-heavy.
Keeping their HTML/CSS payload inline on ``slide_style_library`` would bloat the
frequently-queried library rows (the list endpoint reads every style). Instead
the payload lives here, mirroring the app's existing binary-asset pattern
(``ImageAsset.image_data`` / ``DesignSystemAsset.data`` — Postgres ``bytea``),
while ``slide_style_library`` keeps only a pointer + manifest + status.

Referenced image bytes are NOT duplicated here: previews reference images via the
existing image library (served by its own controlled route), so this table stores
only the gzipped HTML/CSS bundle.
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)

from src.core.database import Base


class SlideStylePreviewPayload(Base):
    """Gzipped HTML/CSS bundle for one (style, fingerprint) preview.

    Uniqueness on ``(style_id, fingerprint)`` makes writes idempotent and lets a
    stale-but-known-good payload survive while a newer fingerprint regenerates.
    """

    __tablename__ = "slide_style_preview_payload"

    id = Column(Integer, primary_key=True)  # Internal only — never serialized.
    style_id = Column(Integer, nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False, index=True)

    # gzip(JSON) of {"html": str, "css": str, "assets": [...manifest...]}.
    bundle_gzip = Column(LargeBinary, nullable=False)
    total_bytes = Column(Integer, nullable=False, default=0)  # uncompressed payload size

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("style_id", "fingerprint", name="uq_slide_style_preview_fp"),
    )

    def __repr__(self):
        return (
            f"<SlideStylePreviewPayload(id={self.id}, style_id={self.style_id}, "
            f"fingerprint={self.fingerprint[:8]}…, bytes={self.total_bytes})>"
        )
