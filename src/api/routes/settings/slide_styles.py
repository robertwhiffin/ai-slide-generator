"""
Slide Style Library API endpoints.

CRUD operations for the global library of slide styles.
These styles control the visual appearance of generated slides
(typography, colors, layout, etc.).
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.core.database import get_db, get_db_session
from src.database.models import SlideStyleLibrary
from src.services import slide_style_preview_fixture as preview_fixture
from src.services import slide_style_preview_storage as preview_storage

logger = logging.getLogger(__name__)

# Fields whose change invalidates a generated preview (see cache-invalidation).
_PREVIEW_AFFECTING_FIELDS = ("style_content", "image_guidelines")

router = APIRouter(prefix="/slide-styles", tags=["slide-styles"])


# Request/Response schemas

class SlideStyleBase(BaseModel):
    """Base schema for slide styles."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    style_content: str = Field(..., min_length=1)
    image_guidelines: Optional[str] = None


class SlideStyleCreate(SlideStyleBase):
    """Request to create a slide style."""
    pass


class SlideStyleUpdate(BaseModel):
    """Request to update a slide style."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    style_content: Optional[str] = Field(None, min_length=1)
    image_guidelines: Optional[str] = None


class SlideStyleResponse(SlideStyleBase):
    """Response schema for slide styles."""
    id: int
    is_active: bool
    is_system: bool  # Protected system styles cannot be edited/deleted
    is_default: bool  # Whether this is the system-wide default style
    created_by: Optional[str]
    created_at: str
    updated_by: Optional[str]
    updated_at: str

    class Config:
        from_attributes = True


class SlideStyleListResponse(BaseModel):
    """Response for listing slide styles."""
    styles: List[SlideStyleResponse]
    total: int


class SlideStylePreviewResponse(BaseModel):
    """Read-only preview state for a slide style.

    ``status`` drives the client: ``ready`` (current), ``stale`` (a usable but
    out-of-date copy while regeneration runs), ``queued``/``generating`` (in
    flight), ``failed`` (with optional last-known-good copy), ``missing`` (never
    generated). HTTP is always 200; the client polls on ``status`` rather than
    on status codes.
    """
    style_id: int
    status: str
    fingerprint: Optional[str] = None
    slides: Optional[List[str]] = None
    css: Optional[str] = None
    assets: Optional[List[dict]] = None
    generated_at: Optional[str] = None
    error_code: Optional[str] = None
    stale: bool = False


# API endpoints

@router.get("", response_model=SlideStyleListResponse)
def list_slide_styles(
    include_inactive: bool = False,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List all slide styles from the library.
    
    Args:
        include_inactive: If True, include soft-deleted styles
        category: Filter by category (optional)
        
    Returns:
        List of slide styles
    """
    try:
        query = db.query(SlideStyleLibrary)
        
        if not include_inactive:
            query = query.filter(SlideStyleLibrary.is_active == True)
        
        if category:
            query = query.filter(SlideStyleLibrary.category == category)
        
        styles = query.order_by(SlideStyleLibrary.name).all()
        
        return SlideStyleListResponse(
            styles=[
                SlideStyleResponse(
                    id=s.id,
                    name=s.name,
                    description=s.description,
                    category=s.category,
                    style_content=s.style_content,
                    image_guidelines=s.image_guidelines,
                    is_active=s.is_active,
                    is_system=s.is_system,
                    is_default=s.is_default,
                    created_by=s.created_by,
                    created_at=s.created_at.isoformat(),
                    updated_by=s.updated_by,
                    updated_at=s.updated_at.isoformat(),
                )
                for s in styles
            ],
            total=len(styles),
        )
    except Exception as e:
        logger.error(f"Error listing slide styles: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list slide styles",
        )


@router.get("/{style_id}", response_model=SlideStyleResponse)
def get_slide_style(
    style_id: int,
    db: Session = Depends(get_db),
):
    """
    Get a specific slide style by ID.
    
    Args:
        style_id: Slide style ID
        
    Returns:
        Slide style details
        
    Raises:
        404: Style not found
    """
    try:
        style = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.id == style_id
        ).first()
        
        if not style:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slide style {style_id} not found",
            )
        
        return SlideStyleResponse(
            id=style.id,
            name=style.name,
            description=style.description,
            category=style.category,
            style_content=style.style_content,
            image_guidelines=style.image_guidelines,
            is_active=style.is_active,
            is_system=style.is_system,
            is_default=style.is_default,
            created_by=style.created_by,
            created_at=style.created_at.isoformat(),
            updated_by=style.updated_by,
            updated_at=style.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get slide style",
        )


# SDR-4437 HIGH-3: workspace-global library writes are admin-only.
@router.post("", response_model=SlideStyleResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_slide_style(
    request: SlideStyleCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new slide style in the library.
    
    Args:
        request: Slide style creation request
        
    Returns:
        Created slide style
        
    Raises:
        409: Style with same name already exists
    """
    try:
        # Check for existing style with same name
        existing = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.name == request.name
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Slide style with name '{request.name}' already exists",
            )
        
        # Get current user (skip Databricks call in test/dev to avoid network timeout)
        if os.getenv("ENVIRONMENT") in ("development", "test"):
            user = "system"
        else:
            # HIGH-6 (SDR-4437): no except-Exception fallback — attribution
            # must not silently degrade to "system"; a missing OBO client or
            # empty user_name raises instead of storing a fallback identity.
            from src.core.databricks_client import UserClientRequiredError, get_user_client

            user = get_user_client().current_user.me().user_name
            if not user:
                raise UserClientRequiredError("OBO client resolved no user_name")
        
        style = SlideStyleLibrary(
            name=request.name,
            description=request.description,
            category=request.category,
            style_content=request.style_content,
            image_guidelines=request.image_guidelines,
            is_active=True,
            created_by=user,
            updated_by=user,
        )
        
        db.add(style)
        db.commit()
        db.refresh(style)
        
        logger.info(f"Created slide style: {style.name} (id={style.id})")

        # Warm the visual preview immediately so the first viewer gets a cache
        # hit instead of waiting on a cold generation. Deduplicated + best-effort.
        try:
            from src.api.services.slide_style_preview_queue import try_enqueue

            try_enqueue(style.id)
        except Exception:  # noqa: BLE001 — warming must never fail the create
            logger.warning("Preview warm-on-create failed", exc_info=True)
        
        return SlideStyleResponse(
            id=style.id,
            name=style.name,
            description=style.description,
            category=style.category,
            style_content=style.style_content,
            image_guidelines=style.image_guidelines,
            is_active=style.is_active,
            is_system=style.is_system,
            is_default=style.is_default,
            created_by=style.created_by,
            created_at=style.created_at.isoformat(),
            updated_by=style.updated_by,
            updated_at=style.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating slide style: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create slide style",
        )


# SDR-4437 HIGH-3: workspace-global library writes are admin-only.
@router.put("/{style_id}", response_model=SlideStyleResponse, dependencies=[Depends(require_admin)])
def update_slide_style(
    style_id: int,
    request: SlideStyleUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing slide style.
    
    Args:
        style_id: Slide style ID
        request: Update request (only provided fields are updated)
        
    Returns:
        Updated slide style
        
    Raises:
        404: Style not found
        409: Name conflicts with another style
    """
    try:
        style = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.id == style_id
        ).first()
        
        if not style:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slide style {style_id} not found",
            )
        
        # Protect system styles from editing
        if style.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System styles cannot be modified",
            )
        
        # Check for name conflict if name is being updated
        if request.name and request.name != style.name:
            existing = db.query(SlideStyleLibrary).filter(
                SlideStyleLibrary.name == request.name,
                SlideStyleLibrary.id != style_id,
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Slide style with name '{request.name}' already exists",
                )
            style.name = request.name
        
        if request.description is not None:
            style.description = request.description
        if request.category is not None:
            style.category = request.category

        # Detect preview-affecting changes BEFORE mutating, so we can invalidate
        # the cached preview in the SAME transaction as the edit (cache-invalidation).
        preview_affected = False
        if request.style_content is not None and request.style_content != style.style_content:
            preview_affected = True
        if (
            request.image_guidelines is not None
            and request.image_guidelines != style.image_guidelines
        ):
            preview_affected = True

        if request.style_content is not None:
            style.style_content = request.style_content
        if request.image_guidelines is not None:
            style.image_guidelines = request.image_guidelines

        if preview_affected:
            # Bump the revision (the generation write-back guard) and reset the
            # cached preview to 'missing' so it regenerates. The last-known-good
            # payload row is left in storage until the next successful prune.
            style.style_revision = (style.style_revision or 0) + 1
            style.preview_status = "missing"
            style.preview_fingerprint = None
            style.preview_payload_id = None
            style.preview_error_code = None
            style.preview_error_message = None
            logger.info(
                "Invalidated slide-style preview after edit",
                extra={"style_id": style.id, "style_revision": style.style_revision},
            )

        # Update the user (skip Databricks call in test/dev to avoid network timeout)
        if os.getenv("ENVIRONMENT") in ("development", "test"):
            style.updated_by = "system"
        else:
            # HIGH-6 (SDR-4437): no except-Exception fallback — attribution
            # must not silently degrade to "system"; a missing OBO client or
            # empty user_name raises instead of storing a fallback identity.
            from src.core.databricks_client import UserClientRequiredError, get_user_client

            user_name = get_user_client().current_user.me().user_name
            if not user_name:
                raise UserClientRequiredError("OBO client resolved no user_name")
            style.updated_by = user_name
        
        db.commit()
        db.refresh(style)
        
        logger.info(f"Updated slide style: {style.name} (id={style.id})")

        # If the edit invalidated the preview, warm it right away (against the
        # now-committed new revision) so viewers don't hit a cold regeneration.
        if preview_affected:
            try:
                from src.api.services.slide_style_preview_queue import try_enqueue

                try_enqueue(style.id)
            except Exception:  # noqa: BLE001 — warming must never fail the update
                logger.warning("Preview warm-on-update failed", exc_info=True)
        
        return SlideStyleResponse(
            id=style.id,
            name=style.name,
            description=style.description,
            category=style.category,
            style_content=style.style_content,
            image_guidelines=style.image_guidelines,
            is_active=style.is_active,
            is_system=style.is_system,
            is_default=style.is_default,
            created_by=style.created_by,
            created_at=style.created_at.isoformat(),
            updated_by=style.updated_by,
            updated_at=style.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update slide style",
        )


# SDR-4437 HIGH-3: workspace-global library writes are admin-only.
@router.delete("/{style_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_slide_style(
    style_id: int,
    hard_delete: bool = False,
    db: Session = Depends(get_db),
):
    """
    Delete a slide style (soft-delete by default).
    
    Args:
        style_id: Slide style ID
        hard_delete: If True, permanently delete. Otherwise, mark as inactive.
        
    Raises:
        404: Style not found
    """
    try:
        style = db.query(SlideStyleLibrary).filter(
            SlideStyleLibrary.id == style_id
        ).first()
        
        if not style:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slide style {style_id} not found",
            )
        
        # Protect system styles from deletion
        if style.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System styles cannot be deleted",
            )

        # If deleting the default style, reassign default to the system style
        if style.is_default:
            system_style = db.query(SlideStyleLibrary).filter(
                SlideStyleLibrary.is_system == True,  # noqa: E712
                SlideStyleLibrary.is_active == True,  # noqa: E712
            ).first()
            if system_style:
                style.is_default = False
                system_style.is_default = True
                logger.info(f"Reassigned default style to system style: {system_style.name}")

        if hard_delete:
            db.delete(style)
            logger.info(f"Hard deleted slide style: {style.name} (id={style.id})")
        else:
            style.is_active = False
            # Update the user (skip Databricks call in test/dev to avoid network timeout)
            if os.getenv("ENVIRONMENT") in ("development", "test"):
                style.updated_by = "system"
            else:
                # HIGH-6 (SDR-4437): no except-Exception fallback — attribution
                # must not silently degrade to "system"; a missing OBO client or
                # empty user_name raises instead of storing a fallback identity.
                from src.core.databricks_client import UserClientRequiredError, get_user_client

                user_name = get_user_client().current_user.me().user_name
                if not user_name:
                    raise UserClientRequiredError("OBO client resolved no user_name")
                style.updated_by = user_name
            logger.info(f"Soft deleted slide style: {style.name} (id={style.id})")
        
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete slide style",
        )


# SDR-4437 HIGH-3: workspace-global library writes are admin-only.
@router.post("/{style_id}/set-default", response_model=SlideStyleResponse, dependencies=[Depends(require_admin)])
def set_default_slide_style(style_id: int):
    """Set a slide style as the system-wide default.

    Unsets the previous default in a single transaction.
    Idempotent: setting the already-default style returns 200.
    """
    try:
        with get_db_session() as db:
            style = db.query(SlideStyleLibrary).filter(
                SlideStyleLibrary.id == style_id,
            ).first()

            if not style:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Slide style {style_id} not found",
                )

            if not style.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot set an inactive style as default",
                )

            if not style.is_default:
                # Unset previous default
                db.query(SlideStyleLibrary).filter(
                    SlideStyleLibrary.is_default == True,  # noqa: E712
                ).update({"is_default": False})

                style.is_default = True
                db.commit()
                db.refresh(style)

            logger.info(f"Set default slide style: {style.name} (id={style.id})")

            return SlideStyleResponse(
                id=style.id,
                name=style.name,
                description=style.description,
                category=style.category,
                style_content=style.style_content,
                image_guidelines=style.image_guidelines,
                is_active=style.is_active,
                is_system=style.is_system,
                is_default=style.is_default,
                created_by=style.created_by,
                created_at=style.created_at.isoformat(),
                updated_by=style.updated_by,
                updated_at=style.updated_at.isoformat(),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting default slide style {style_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default slide style",
        )


@router.get("/{style_id}/preview", response_model=SlideStylePreviewResponse)
def get_slide_style_preview(
    style_id: int,
    db: Session = Depends(get_db),
):
    """Read the cached visual preview for a slide style. NEVER generates inline.

    Visibility mirrors ``GET /{style_id}`` (404 parity). When the cached preview
    is missing or stale relative to the current generation fingerprint, this
    enqueues a deduplicated background job and returns the current state (with a
    stale copy if one exists) so the UI stays fast and crawlers/prefetch/scroll
    never trigger LLM cost.
    """
    from src.api.services.slide_style_preview_queue import try_enqueue

    style = db.query(SlideStyleLibrary).filter(SlideStyleLibrary.id == style_id).first()
    if not style:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slide style {style_id} not found",
        )

    current_fp = preview_fixture.compute_fingerprint(
        style.style_content, style.image_guidelines
    )
    status_val = style.preview_status or "missing"

    # Load any stored payload (ready OR last-known-good) once.
    payload = None
    if style.preview_payload_id:
        payload = preview_storage.load_payload(db, style.preview_payload_id)

    def _resp(status_str: str, *, include_payload: bool, stale: bool = False):
        has = include_payload and payload
        return SlideStylePreviewResponse(
            style_id=style_id,
            status=status_str,
            fingerprint=style.preview_fingerprint if include_payload else None,
            slides=(payload or {}).get("slides") if has else None,
            css=(payload or {}).get("css") if has else None,
            assets=(payload or {}).get("assets") if has else None,
            generated_at=style.preview_generated_at.isoformat()
            if (has and style.preview_generated_at)
            else None,
            error_code=style.preview_error_code,
            stale=stale,
        )

    # Ready and current (cache hit).
    if status_val == "ready" and style.preview_fingerprint == current_fp and payload:
        logger.info(
            "slide_style_preview.cache_hit",
            extra={"style_id": style_id, "status": "ready"},
        )
        return _resp("ready", include_payload=True)

    # Ready but stale (fingerprint moved). Serve the stale copy, kick a refresh.
    if status_val == "ready" and payload:
        age_s = None
        if style.preview_generated_at:
            from datetime import datetime as _dt

            age_s = (_dt.utcnow() - style.preview_generated_at).total_seconds()
        logger.info(
            "slide_style_preview.cache_stale",
            extra={"style_id": style_id, "stale_age_s": age_s},
        )
        try_enqueue(style_id)
        return _resp("stale", include_payload=True, stale=True)

    # In flight. Serve stale copy underneath if present.
    if status_val in ("queued", "generating"):
        return _resp(status_val, include_payload=bool(payload), stale=bool(payload))

    # Failed. Return last-known-good if we have one; otherwise just the error.
    if status_val == "failed":
        return _resp("failed", include_payload=bool(payload), stale=bool(payload))

    # Missing (or unknown): enqueue and report queued.
    try_enqueue(style_id)
    # Re-read status: try_enqueue may have transitioned it to 'queued'.
    return SlideStylePreviewResponse(style_id=style_id, status="queued")


# SDR-4437 HIGH-3: workspace-global library writes are admin-only.
@router.post(
    "/{style_id}/preview/regenerate",
    response_model=SlideStylePreviewResponse,
    dependencies=[Depends(require_admin)],
)
def regenerate_slide_style_preview(
    style_id: int,
    db: Session = Depends(get_db),
):
    """Explicitly (re)generate a slide-style preview. Admin-only, deduplicated.

    Enqueues a background job against the current style snapshot. Idempotent: if
    a generation is already in flight this is a no-op that returns the in-flight
    status.
    """
    from src.api.services.slide_style_preview_queue import try_enqueue

    style = db.query(SlideStyleLibrary).filter(SlideStyleLibrary.id == style_id).first()
    if not style:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slide style {style_id} not found",
        )

    # Force a re-attempt even from a 'failed'/'ready' terminal state by clearing
    # to 'missing' first (in its own committed txn), then enqueue.
    db.query(SlideStyleLibrary).filter(SlideStyleLibrary.id == style_id).update(
        {"preview_status": "missing"}, synchronize_session=False
    )
    db.commit()

    try_enqueue(style_id)
    return SlideStylePreviewResponse(style_id=style_id, status="queued")
