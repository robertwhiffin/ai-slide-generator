"""Design System Library API endpoints (Phase 3).

CRUD + bundle import for org-shared design systems. Mirrors the slide-styles
router (``slide_styles.py``): design systems are company-wide assets (everyone
can view/use), ``created_by`` records authorship, and a single ``is_default``
marks the org default. A design system compiles to ``compiled_style_content`` —
the drop-in equivalent of ``slide_style_library.style_content`` — so it flows
through the existing generation seam (see ``agent_factory._get_prompt_content``).

Name uniqueness: creation/import return **409 Conflict** on a duplicate name
(``design_system.name`` is unique, spec §6), matching the slide-styles
convention. This is deliberately non-destructive — an org-shared asset is never
silently overwritten; the caller supplies a different name (import accepts a
``name`` form field) to import a copy.
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.database.models.design_system import (
    MAX_BUNDLE_SIZE_BYTES,
    DesignSystem,
    DesignSystemAsset,
    DesignSystemToken,
)
from src.services import design_system_service
from src.services.design_system_compiler import recompute_compiled_style_content
from src.services.design_system_service import (
    DesignSystemImportError,
    DesignSystemNameConflictError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design-systems", tags=["design-systems"])


# --- Schemas ---------------------------------------------------------------


class TokenIn(BaseModel):
    group: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=1, max_length=255)


class TokenOut(TokenIn):
    id: int


class AssetOut(BaseModel):
    id: int
    kind: str
    filename: str
    mime: str
    size_bytes: int
    width: Optional[int]
    height: Optional[int]
    url: str  # served-asset endpoint (bytes are never inlined in listings)


class DesignSystemSummary(BaseModel):
    """List/picker view — counts only, no binary payloads."""
    id: int
    name: str
    description: Optional[str]
    created_by: Optional[str]
    published: bool
    is_default: bool
    is_active: bool
    version: int
    token_count: int
    asset_count: int
    template_count: int
    created_at: str
    updated_at: str


class DesignSystemListResponse(BaseModel):
    design_systems: List[DesignSystemSummary]
    total: int


class DesignSystemDetail(DesignSystemSummary):
    manifest_json: Optional[dict]
    compiled_style_content: Optional[str]
    tokens: List[TokenOut]
    assets: List[AssetOut]


class DesignSystemCreate(BaseModel):
    """Structured (in-app) create — thin. Assets arrive via /import."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tokens: Optional[List[TokenIn]] = None
    manifest_json: Optional[dict] = None


class DesignSystemUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    tokens: Optional[List[TokenIn]] = None
    manifest_json: Optional[dict] = None


# --- Helpers ---------------------------------------------------------------


def _current_user() -> str:
    """Current username (dev/test fallback to 'system'). Mirrors images.py."""
    if os.getenv("ENVIRONMENT") in ("development", "test"):
        return "system"
    try:
        from src.core.databricks_client import get_user_client

        return get_user_client().current_user.me().user_name or "system"
    except Exception:
        return "system"


def _template_count(manifest_json: Optional[dict]) -> int:
    if isinstance(manifest_json, dict) and isinstance(manifest_json.get("templates"), list):
        return len(manifest_json["templates"])
    return 0


def _asset_url(ds_id: int, asset_id: int) -> str:
    return f"/api/settings/design-systems/{ds_id}/assets/{asset_id}"


def _summary(
    ds: DesignSystem, *, token_count: int, asset_count: int
) -> DesignSystemSummary:
    return DesignSystemSummary(
        id=ds.id,
        name=ds.name,
        description=ds.description,
        created_by=ds.created_by,
        published=ds.published,
        is_default=ds.is_default,
        is_active=ds.is_active,
        version=ds.version,
        token_count=token_count,
        asset_count=asset_count,
        template_count=_template_count(ds.manifest_json),
        created_at=ds.created_at.isoformat(),
        updated_at=ds.updated_at.isoformat(),
    )


def _detail(ds: DesignSystem) -> DesignSystemDetail:
    tokens = sorted(ds.tokens, key=lambda t: (t.group, t.name))
    assets = sorted(ds.assets, key=lambda a: (a.kind, a.filename, a.id))
    return DesignSystemDetail(
        **_summary(ds, token_count=len(tokens), asset_count=len(assets)).model_dump(),
        manifest_json=ds.manifest_json,
        compiled_style_content=ds.compiled_style_content,
        tokens=[
            TokenOut(id=t.id, group=t.group, name=t.name, value=t.value) for t in tokens
        ],
        assets=[
            AssetOut(
                id=a.id,
                kind=a.kind,
                filename=a.filename,
                mime=a.mime,
                size_bytes=a.size_bytes,
                width=a.width,
                height=a.height,
                url=_asset_url(ds.id, a.id),
            )
            for a in assets
        ],
    )


# --- Endpoints -------------------------------------------------------------


@router.get("", response_model=DesignSystemListResponse)
def list_design_systems(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    """List org-shared design systems with token/asset counts for the picker."""
    try:
        query = db.query(DesignSystem)
        if not include_inactive:
            query = query.filter(DesignSystem.is_active == True)  # noqa: E712
        systems = query.order_by(DesignSystem.name).all()

        # Aggregate counts without loading token rows or asset bytea payloads.
        token_counts: dict[int, int] = dict(
            db.query(DesignSystemToken.design_system_id, func.count(DesignSystemToken.id))
            .group_by(DesignSystemToken.design_system_id)
            .all()
        )
        asset_counts: dict[int, int] = dict(
            db.query(DesignSystemAsset.design_system_id, func.count(DesignSystemAsset.id))
            .group_by(DesignSystemAsset.design_system_id)
            .all()
        )

        return DesignSystemListResponse(
            design_systems=[
                _summary(
                    ds,
                    token_count=token_counts.get(ds.id, 0),
                    asset_count=asset_counts.get(ds.id, 0),
                )
                for ds in systems
            ],
            total=len(systems),
        )
    except Exception as e:
        logger.error(f"Error listing design systems: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list design systems",
        )


@router.post("/import", response_model=DesignSystemDetail, status_code=status.HTTP_201_CREATED)
async def import_design_system(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Import a .zip design-system bundle: validate, store assets/tokens, compile."""
    content = await file.read()
    if len(content) > MAX_BUNDLE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload exceeds the maximum bundle size of {MAX_BUNDLE_SIZE_BYTES} bytes",
        )
    try:
        ds = design_system_service.import_bundle(
            db, zip_bytes=content, user=_current_user(), name_override=name
        )
        return _detail(ds)
    except DesignSystemNameConflictError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except DesignSystemImportError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error importing design system: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to import design system",
        )


@router.post("", response_model=DesignSystemDetail, status_code=status.HTTP_201_CREATED)
def create_design_system(
    request: DesignSystemCreate,
    db: Session = Depends(get_db),
):
    """Create a design system from structured input (assets arrive via /import)."""
    try:
        existing = db.query(DesignSystem).filter(DesignSystem.name == request.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Design system with name '{request.name}' already exists",
            )
        user = _current_user()
        ds = DesignSystem(
            name=request.name,
            description=request.description,
            created_by=user,
            updated_by=user,
            manifest_json=request.manifest_json,
            version=1,
            published=False,
            is_default=False,
            is_active=True,
        )
        for tok in request.tokens or []:
            ds.tokens.append(DesignSystemToken(group=tok.group, name=tok.name, value=tok.value))

        db.add(ds)
        db.flush()
        recompute_compiled_style_content(ds)
        db.commit()
        db.refresh(ds)
        logger.info(f"Created design system: {ds.name} (id={ds.id})")
        return _detail(ds)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating design system: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create design system",
        )


@router.get("/{ds_id}", response_model=DesignSystemDetail)
def get_design_system(ds_id: int, db: Session = Depends(get_db)):
    """Get a design system detail (README/manifest, tokens, assets)."""
    try:
        ds = db.query(DesignSystem).filter(DesignSystem.id == ds_id).first()
        if not ds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Design system {ds_id} not found",
            )
        return _detail(ds)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get design system",
        )


@router.put("/{ds_id}", response_model=DesignSystemDetail)
def update_design_system(
    ds_id: int,
    request: DesignSystemUpdate,
    db: Session = Depends(get_db),
):
    """Update a design system and recompute its compiled prompt artifact."""
    try:
        ds = db.query(DesignSystem).filter(DesignSystem.id == ds_id).first()
        if not ds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Design system {ds_id} not found",
            )

        if request.name and request.name != ds.name:
            clash = (
                db.query(DesignSystem)
                .filter(DesignSystem.name == request.name, DesignSystem.id != ds_id)
                .first()
            )
            if clash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Design system with name '{request.name}' already exists",
                )
            ds.name = request.name

        if request.description is not None:
            ds.description = request.description
        if request.manifest_json is not None:
            ds.manifest_json = request.manifest_json
        if request.tokens is not None:
            # Replace the token set wholesale (delete-orphan cascade removes the old).
            ds.tokens.clear()
            db.flush()
            for tok in request.tokens:
                ds.tokens.append(
                    DesignSystemToken(group=tok.group, name=tok.name, value=tok.value)
                )

        ds.version = (ds.version or 1) + 1
        ds.updated_by = _current_user()
        db.flush()
        recompute_compiled_style_content(ds)
        db.commit()
        db.refresh(ds)
        logger.info(f"Updated design system: {ds.name} (id={ds.id})")
        return _detail(ds)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update design system",
        )


@router.delete("/{ds_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_design_system(
    ds_id: int,
    hard_delete: bool = False,
    db: Session = Depends(get_db),
):
    """Delete a design system (soft-delete by default, mirroring slide styles)."""
    try:
        ds = db.query(DesignSystem).filter(DesignSystem.id == ds_id).first()
        if not ds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Design system {ds_id} not found",
            )

        # A deleted design system can't remain the org default. There is no
        # protected "system" design system to reassign to (unlike slide styles),
        # so generation simply falls back to the slide-style default.
        if ds.is_default:
            ds.is_default = False

        if hard_delete:
            db.delete(ds)
            logger.info(f"Hard deleted design system: {ds.name} (id={ds.id})")
        else:
            ds.is_active = False
            ds.updated_by = _current_user()
            logger.info(f"Soft deleted design system: {ds.name} (id={ds.id})")
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete design system",
        )


@router.post("/{ds_id}/set-default", response_model=DesignSystemDetail)
def set_default_design_system(ds_id: int, db: Session = Depends(get_db)):
    """Set a design system as the single org-wide default.

    Unsets the previous default in the same transaction. Idempotent.
    """
    try:
        ds = db.query(DesignSystem).filter(DesignSystem.id == ds_id).first()
        if not ds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Design system {ds_id} not found",
            )
        if not ds.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set an inactive design system as default",
            )
        if not ds.is_default:
            db.query(DesignSystem).filter(DesignSystem.is_default == True).update(  # noqa: E712
                {"is_default": False}
            )
            ds.is_default = True
            db.commit()
            db.refresh(ds)
        logger.info(f"Set default design system: {ds.name} (id={ds.id})")
        return _detail(ds)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting default design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default design system",
        )


@router.get("/{ds_id}/assets/{asset_id}")
def serve_design_system_asset(ds_id: int, asset_id: int, db: Session = Depends(get_db)):
    """Serve a design-system asset's raw bytes (for preview + generation)."""
    try:
        asset = (
            db.query(DesignSystemAsset)
            .filter(
                DesignSystemAsset.id == asset_id,
                DesignSystemAsset.design_system_id == ds_id,
            )
            .first()
        )
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Asset {asset_id} not found for design system {ds_id}",
            )
        return Response(content=asset.data, media_type=asset.mime)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving design system asset {asset_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve design system asset",
        )
