"""Slide Style Library model.

This model stores reusable slide styling configurations that control
the visual appearance of generated slides (typography, colors, layout,
card styling, etc.).

These are distinct from:
- Deck prompts: control WHAT content to include
- System prompts: control HOW to generate valid HTML/charts (technical)

Slide styles control HOW slides should LOOK - the visual presentation.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from src.core.database import Base


class SlideStyleLibrary(Base):
    """Global library of slide styles.
    
    Each entry represents a reusable visual style configuration for
    slide generation. Profiles can select one of these styles to
    control the look and feel of generated presentations.
    """

    __tablename__ = "slide_style_library"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)  # e.g., "Brand", "Minimal", "Bold"
    style_content = Column(Text, nullable=False)
    image_guidelines = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)  # Protected system styles cannot be edited/deleted
    
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)  # Which style is applied to new sessions by default

    # --- Generated preview cache (see docs: slide-style visual preview) ------
    # A slide style is prose the model interprets, so its "what will my slides
    # look like" preview is a generated sample deck. Generation is expensive and
    # non-deterministic, so it runs in a background job and its result is cached.
    # The HTML/CSS PAYLOAD is offloaded to slide_style_preview_payload (bytea);
    # only pointers + status + metadata live here so library reads stay light.
    #
    # preview_status lifecycle: missing -> queued -> generating -> ready|failed.
    preview_status = Column(String(16), nullable=True, default="missing")
    # Full generation fingerprint (style text + brief/prompt/generator/renderer/
    # model versions). A mismatch vs the current fingerprint means the cached
    # preview is stale and must be regenerated.
    preview_fingerprint = Column(String(64), nullable=True)
    # Hash of just the style-authored inputs (edit detection / diagnostics).
    preview_content_hash = Column(String(64), nullable=True)
    # Pointer into slide_style_preview_payload (the ready/last-known-good bundle).
    preview_payload_id = Column(Integer, nullable=True)
    # Non-secret manifest: referenced image ids/types + sizes (no bytes).
    preview_asset_manifest = Column(JSON, nullable=True)
    preview_total_bytes = Column(Integer, nullable=True)
    # Failure diagnostics (sanitized; safe to expose to clients).
    preview_error_code = Column(String(64), nullable=True)
    preview_error_message = Column(Text, nullable=True)
    preview_generated_at = Column(DateTime, nullable=True)
    preview_attempted_at = Column(DateTime, nullable=True)
    preview_failed_at = Column(DateTime, nullable=True)
    # Bumped whenever a preview-affecting field (style_content/image_guidelines)
    # changes. The generation worker only writes its result back if this value is
    # unchanged from the snapshot it generated against — preventing a slow, stale
    # generation from clobbering a freshly-edited style.
    style_revision = Column(Integer, nullable=True, default=0)

    def __repr__(self):
        return f"<SlideStyleLibrary(id={self.id}, name='{self.name}', category='{self.category}')>"
