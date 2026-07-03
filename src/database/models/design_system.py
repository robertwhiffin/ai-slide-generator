"""Design System models — the structured "skill-with-files" brand bundle.

Phase 1 of the Design System Library feature (see
``docs/technical/design-system-library-spec.md`` §6). These are ADDITIVE tables:
they sit alongside — and do not modify — ``slide_style_library``, so the existing
free-text ``style_content`` prompt-injection path keeps working unchanged.

A design system is an org-shared company asset (everyone can view/use, matching
how slide styles work today); ``created_by`` records authorship, ``published`` +
``is_default`` mark the org default.

Four tables:
- ``design_system``        — the parent record: metadata + parsed manifest +
                             the normalized font mapping + the compiled prompt
                             artifact.
- ``design_system_asset``  — binary brand blobs (logo/font/…), bytes stored
                             in-DB following the existing ``image_assets`` pattern.
- ``design_system_token``  — normalized tokens (colors/type/spacing/shadow) for
                             cheap query/preview without parsing the manifest.
- ``design_system_file``   — retained bundle SOURCE files (README/SKILL/CSS/
                             template layout HTML) plus path-metadata REFERENCES
                             back to ``design_system_asset`` rows (v1 Phase 1).

Binary brand bytes live ONLY in ``design_system_asset``; ``design_system_file``
stores the (text) bytes of genuinely-new source files and, for assets/fonts,
only a path reference (``asset_id``, ``data`` NULL) so a bundle's binary payload
is never double-stored. The parent and token tables stay blob-free so a bundle
listing never drags large payloads along.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.core.database import Base

# --- Guardrails ------------------------------------------------------------
# Size limits enforced at the application layer during upload/import (Phase 3),
# analogous to ``image_service.MAX_FILE_SIZE``. Kept here next to the models so
# every writer shares one source of truth. Bytes are only ever persisted in the
# dedicated ``design_system_asset`` table.
MAX_ASSET_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB per individual asset
MAX_BUNDLE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MB per uploaded design-system bundle
# NOTE: bytes are persisted in-row in ``design_system_asset`` (Lakebase Postgres).
# Raising the bundle cap to 200 MB means a single import can add up to ~200 MB of
# BLOB rows; large blobs bloat the row store and every copy-on-write branch fork.
# This is a deliberate limit bump, not a storage re-architecture — revisit
# out-of-row/object-store offloading if bundles routinely approach this size.

# JSON on SQLite (tests); JSONB on PostgreSQL/Lakebase so the parsed manifest can
# later be introspected/indexed natively. Mirrors the ImageAsset.tags convention.
_ManifestColumn = JSON().with_variant(JSONB(), "postgresql")


class DesignSystem(Base):
    """Parent record for a structured design system (org-shared).

    ``compiled_style_content`` is the auto-generated prompt text and plays the
    same role that ``slide_style_library.style_content`` plays today — the
    verbatim block injected into the generation system prompt. Keeping it as a
    dedicated Text column lets the Phase 2 compiler write here and route the
    result through the identical ``build_generation_system_prompt`` seam, so the
    feature is fully backward compatible. It is nullable because a structured
    design system may exist before it has been compiled.
    """

    __tablename__ = "design_system"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)

    # Authorship + org-default flags (org-shared visibility; no per-user isolation)
    created_by = Column(String(255), nullable=True)
    published = Column(Boolean, default=False, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    # Soft-delete flag, mirroring ``slide_style_library.is_active``: DELETE marks a
    # design system inactive rather than removing it, so list/lookup/generation
    # can filter it out while authorship/history are preserved (spec §7). Added in
    # Phase 3; an idempotent ALTER in ``_run_migrations`` backfills pre-existing
    # tables that were created before this column existed. A TRUE ``server_default``
    # (not just the client-side ``default``) means the CREATE TABLE DDL and the
    # backfill ALTER agree, and any non-ORM insert defaults to active — matching
    # ``_migrate_design_system_soft_delete``'s ``DEFAULT TRUE``.
    is_active = Column(Boolean, default=True, server_default=text("true"), nullable=False)

    # Monotonic record version (bumped on structural edits). The bundle's own
    # semantic version string, if any, lives inside ``manifest_json``.
    version = Column(Integer, default=1, nullable=False)

    # Parsed ``design-system.json`` manifest (indexes of tokens/templates/assets/fonts).
    manifest_json = Column(_ManifestColumn, nullable=True)

    # Auto-compiled prompt artifact — maps to today's slide_style_library.style_content.
    compiled_style_content = Column(Text, nullable=True)

    # Normalized font mapping derived from the manifest ``fonts[]`` / ``brandFonts[]``
    # at import (family -> weight/style variants + the tokens that reference the
    # family). A flattened projection — like ``DesignSystemToken`` — so downstream
    # typography use never re-parses the raw manifest. JSON on SQLite, JSONB on
    # PostgreSQL/Lakebase. Nullable: a bundle may declare no fonts.
    font_mapping_json = Column(_ManifestColumn, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    assets = relationship(
        "DesignSystemAsset",
        back_populates="design_system",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tokens = relationship(
        "DesignSystemToken",
        back_populates="design_system",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    files = relationship(
        "DesignSystemFile",
        back_populates="design_system",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return (
            f"<DesignSystem(id={self.id}, name='{self.name}', "
            f"published={self.published}, is_default={self.is_default})>"
        )


class DesignSystemAsset(Base):
    """Binary brand asset stored in-DB (PostgreSQL bytea / SQLite BLOB).

    Follows the ``image_assets`` pattern: metadata + raw bytes in one row, no
    external storage. This is the ONLY table that holds binary payloads.
    """

    __tablename__ = "design_system_asset"

    id = Column(Integer, primary_key=True)
    design_system_id = Column(
        Integer,
        ForeignKey("design_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # logo | icon | lockup | illustration | background | font | template_shot
    kind = Column(String(50), nullable=False)
    filename = Column(String(255), nullable=False)
    mime = Column(String(100), nullable=False)

    # Raw bytes. DB column is named "bytes" per spec §6; the Python attribute is
    # ``data`` to avoid shadowing the ``bytes`` builtin.
    data = Column("bytes", LargeBinary, nullable=False)

    # Intrinsic dimensions where meaningful (images); NULL for fonts/templates.
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=False)

    design_system = relationship("DesignSystem", back_populates="assets")

    def __repr__(self):
        return (
            f"<DesignSystemAsset(id={self.id}, design_system_id={self.design_system_id}, "
            f"kind='{self.kind}', filename='{self.filename}')>"
        )


class DesignSystemToken(Base):
    """Normalized design token for query/preview (colors/type/spacing).

    The authoritative token data also lives in ``DesignSystem.manifest_json``;
    this table is a flattened projection so the picker/preview can read tokens
    without parsing the manifest.
    """

    __tablename__ = "design_system_token"

    id = Column(Integer, primary_key=True)
    design_system_id = Column(
        Integer,
        ForeignKey("design_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # core | accents | ink | tints | type | spacing.
    # ``group`` is a SQL reserved word; SQLAlchemy quotes the identifier per dialect.
    group = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    value = Column(String(255), nullable=False)

    design_system = relationship("DesignSystem", back_populates="tokens")

    def __repr__(self):
        return (
            f"<DesignSystemToken(id={self.id}, design_system_id={self.design_system_id}, "
            f"group='{self.group}', name='{self.name}')>"
        )


class DesignSystemFile(Base):
    """A retained bundle source file — the authoring/documentation layer (v1 Phase 1).

    The importer previously discarded everything except ``assets/**`` and
    ``fonts/**``. This table retains the bundle's SOURCE files so a design system
    carries its own docs and layout sources (surfaced by the later file browser).
    Two row shapes share the table:

    - SOURCE files (``kind`` in ``readme``/``skill``/``css``/``template``): text
      whose bytes live in ``data`` — genuinely-new content not stored elsewhere.
    - REFERENCE rows (``kind`` in ``asset``/``font``): a path-metadata pointer to
      a ``design_system_asset`` row (``asset_id``) whose bytes are ALREADY stored
      there; ``data`` is NULL. The bundle's binary payload is never double-stored
      (a 200 MB bundle must not be duplicated); resolve their bytes via ``asset``.

    ``path`` is the normalized, bundle-relative path. Zip-slip is rejected at
    import time: no absolute paths and no ``..`` parent-directory traversal.
    """

    __tablename__ = "design_system_file"

    id = Column(Integer, primary_key=True)
    design_system_id = Column(
        Integer,
        ForeignKey("design_system.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Normalized bundle-relative path, e.g. "README.md", "templates/x/index.html".
    path = Column(String(1024), nullable=False)

    # readme | skill | css | template | asset | font
    kind = Column(String(50), nullable=False)
    mime = Column(String(100), nullable=False)

    # Bytes for genuinely-new SOURCE files; NULL for asset/font REFERENCE rows
    # (their bytes live in design_system_asset — never double-stored). The DB
    # column is named "bytes" to match design_system_asset; the Python attribute
    # is ``data`` to avoid shadowing the ``bytes`` builtin.
    data = Column("bytes", LargeBinary, nullable=True)
    size_bytes = Column(Integer, nullable=False)

    # For asset/font reference rows: the design_system_asset holding the bytes.
    asset_id = Column(
        Integer,
        ForeignKey("design_system_asset.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    design_system = relationship("DesignSystem", back_populates="files")
    asset = relationship("DesignSystemAsset")

    def __repr__(self):
        return (
            f"<DesignSystemFile(id={self.id}, design_system_id={self.design_system_id}, "
            f"kind='{self.kind}', path='{self.path}')>"
        )
