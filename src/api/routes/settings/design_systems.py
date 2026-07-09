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
import re
from collections import OrderedDict
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
    DesignSystemFile,
    DesignSystemTemplate,
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
    # Downscaled-variant endpoint for raster formats; None for SVG/fonts/etc.
    # (SVGs are small — grids use ``url`` directly for those).
    thumbnail_url: Optional[str] = None


class TemplateOut(BaseModel):
    """Picker view of one addressable template (Phase 4). The layout HTML is
    deliberately NOT exposed here — source viewing is a later phase."""
    id: int
    name: str
    description: Optional[str]
    entry_path: str
    thumbnail_url: Optional[str]  # template-scoped thumbnail endpoint, or None


class DesignSystemTemplateListResponse(BaseModel):
    templates: List[TemplateOut]
    total: int


class TemplateSourceOut(BaseModel):
    """The stored template sources for CLIENT-SIDE preview rendering.

    Real Claude Design exports ship no screenshot, so the frontend live-renders
    the layout inside a fully-sandboxed iframe (no scripts, no same-origin).
    Returned as JSON — this endpoint never serves renderable markup from the
    app origin (the Phase-6 rule).
    """
    id: int
    name: str
    layout_html: str
    token_css: Optional[str]


class FileEntryOut(BaseModel):
    """One node of the source-file tree (Phase 6) — metadata only, never bytes."""
    path: str
    kind: str
    mime: str
    size_bytes: int


class DesignSystemFileListResponse(BaseModel):
    files: List[FileEntryOut]
    total: int


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


def _asset_thumbnail_url(ds_id: int, asset: DesignSystemAsset) -> Optional[str]:
    """Thumbnail endpoint URL for raster assets; None for everything else."""
    if str(asset.mime) not in _INLINE_SAFE_MIMES:
        return None
    return f"{_asset_url(ds_id, asset.id)}/thumbnail"


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
                thumbnail_url=_asset_thumbnail_url(ds.id, a),
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
    # Reject an oversized upload from its declared size BEFORE materialising it
    # (Starlette populates UploadFile.size from the multipart part when known).
    if file.size is not None and file.size > MAX_BUNDLE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload exceeds the maximum bundle size of {MAX_BUNDLE_SIZE_BYTES} bytes",
        )
    content = await file.read()
    if len(content) > MAX_BUNDLE_SIZE_BYTES:  # backstop when size was unknown
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


def _template_thumbnail_url(ds_id: int, template_id: int) -> str:
    return f"/api/settings/design-systems/{ds_id}/templates/{template_id}/thumbnail"


@router.get("/{ds_id}/templates", response_model=DesignSystemTemplateListResponse)
def list_design_system_templates(ds_id: int, db: Session = Depends(get_db)):
    """List a design system's addressable templates for the picker.

    Rows are materialized lazily (from the manifest + retained bundle files) for
    systems imported before templates were addressable entities, then persisted;
    a system without retained template files simply lists zero templates.
    """
    try:
        ds = db.query(DesignSystem).filter(DesignSystem.id == ds_id).first()
        if not ds:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Design system {ds_id} not found",
            )
        from src.services.design_system_templates import materialize_templates

        if materialize_templates(ds):
            db.commit()  # persist lazily-derived rows (and assign their ids)

        templates = sorted(ds.templates, key=lambda t: t.id)
        return DesignSystemTemplateListResponse(
            templates=[
                TemplateOut(
                    id=t.id,
                    name=t.name,
                    description=t.description,
                    entry_path=t.entry_path,
                    thumbnail_url=(
                        _template_thumbnail_url(ds_id, t.id)
                        if t.thumbnail_asset_id is not None
                        else None
                    ),
                )
                for t in templates
            ],
            total=len(templates),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error listing templates for design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list design system templates",
        )


# Raster image types that are safe to render inline. Anything else (notably
# image/svg+xml, which can carry inline <script>) is served as a download so a
# directly-navigated asset cannot execute script in the app origin (stored XSS).
_INLINE_SAFE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


@router.get("/{ds_id}/templates/{template_id}/thumbnail")
def serve_design_system_template_thumbnail(
    ds_id: int, template_id: int, db: Session = Depends(get_db)
):
    """Serve a template's preview-screenshot bytes for the picker.

    Ownership-validated end to end: the template must belong to the design
    system in the path AND its thumbnail asset must belong to the same system —
    404 otherwise. Served with ``X-Content-Type-Options: nosniff`` (and forced
    to download for non-raster types), mirroring the asset endpoint.
    """
    try:
        template = (
            db.query(DesignSystemTemplate)
            .filter(
                DesignSystemTemplate.id == template_id,
                DesignSystemTemplate.design_system_id == ds_id,
            )
            .first()
        )
        if not template or template.thumbnail_asset_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Thumbnail not found for template {template_id} "
                f"of design system {ds_id}",
            )
        asset = (
            db.query(DesignSystemAsset)
            .filter(
                DesignSystemAsset.id == template.thumbnail_asset_id,
                DesignSystemAsset.design_system_id == ds_id,
            )
            .first()
        )
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Thumbnail not found for template {template_id} "
                f"of design system {ds_id}",
            )
        mime = str(asset.mime)
        headers = {"X-Content-Type-Options": "nosniff"}
        if mime not in _INLINE_SAFE_MIMES:
            # Static value (no attacker-controlled filename) to avoid header injection.
            headers["Content-Disposition"] = "attachment"
        return Response(content=asset.data, media_type=mime, headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error serving thumbnail for template {template_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve design system template thumbnail",
        )


@router.get(
    "/{ds_id}/templates/{template_id}/source", response_model=TemplateSourceOut
)
def get_design_system_template_source(
    ds_id: int, template_id: int, db: Session = Depends(get_db)
):
    """Return one template's stored layout HTML + token CSS as JSON.

    Powers the live-rendered template mini-cards: real Claude Design bundles
    ship no preview screenshots, so when ``thumbnail_url`` is null the
    frontend fetches this and renders it inside a fully-sandboxed iframe
    (``sandbox=""`` — no scripts, no same-origin). JSON keeps the response
    non-renderable from the app origin, consistent with the Phase-6 file
    browser's never-serve-user-markup rule.
    """
    template = (
        db.query(DesignSystemTemplate)
        .filter(
            DesignSystemTemplate.id == template_id,
            DesignSystemTemplate.design_system_id == ds_id,
        )
        .first()
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found for design system {ds_id}",
        )
    return TemplateSourceOut(
        id=template.id,
        name=template.name,
        layout_html=template.layout_html,
        token_css=template.token_css,
    )


@router.get("/{ds_id}/assets/{asset_id}")
def serve_design_system_asset(ds_id: int, asset_id: int, db: Session = Depends(get_db)):
    """Serve a design-system asset's raw bytes (for preview + generation).

    SVG/non-raster assets are forced to download (``Content-Disposition:
    attachment``) with ``X-Content-Type-Options: nosniff`` so they cannot execute
    inline script in the app origin. The generation path is unaffected — it embeds
    assets as base64 data URIs via the resolver, not through this endpoint.
    """
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
        headers = {"X-Content-Type-Options": "nosniff"}
        if asset.mime not in _INLINE_SAFE_MIMES:
            # Static value (no attacker-controlled filename) to avoid header injection.
            headers["Content-Disposition"] = "attachment"
        return Response(content=asset.data, media_type=asset.mime, headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving design system asset {asset_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve design system asset",
        )


# In-process LRU of downscaled asset variants. Keyed by asset id — safe
# because asset rows are immutable after import (a re-upload mints new ids).
_THUMBNAIL_MAX_DIM = 128
_THUMBNAIL_CACHE_MAX = 512
_thumbnail_cache: "OrderedDict[int, bytes]" = OrderedDict()


def _thumbnail_png(asset_id: int, data: bytes) -> Optional[bytes]:
    """Downscale raster bytes to a <=128px PNG, LRU-cached per asset id.

    ``None`` on any decode/encode failure (corrupt file, decompression-bomb
    guard, unsupported subformat) — the endpoint then falls back to serving
    the original bytes, exactly what the grid loaded before this existed.
    """
    cached = _thumbnail_cache.get(asset_id)
    if cached is not None:
        _thumbnail_cache.move_to_end(asset_id)
        return cached
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as im:
            im.thumbnail((_THUMBNAIL_MAX_DIM, _THUMBNAIL_MAX_DIM))
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info
            )
            out = BytesIO()
            im.convert("RGBA" if has_alpha else "RGB").save(
                out, format="PNG", optimize=True
            )
            png = out.getvalue()
    except Exception:
        logger.warning("Thumbnail generation failed for asset %s", asset_id, exc_info=True)
        return None
    _thumbnail_cache[asset_id] = png
    _thumbnail_cache.move_to_end(asset_id)
    while len(_thumbnail_cache) > _THUMBNAIL_CACHE_MAX:
        _thumbnail_cache.popitem(last=False)
    return png


@router.get("/{ds_id}/assets/{asset_id}/thumbnail")
def serve_design_system_asset_thumbnail(
    ds_id: int, asset_id: int, db: Session = Depends(get_db)
):
    """Serve a downscaled variant of a raster asset for grid display.

    Large design systems ship hundreds of full-size assets; the detail grid
    only needs ~36px tiles, so this serves a cached <=128px PNG instead of
    the original megabytes. Security policy is IDENTICAL to the full-asset
    endpoint: nosniff always, and non-raster types (SVG can carry script)
    are returned as the original bytes forced to download — never a new
    render surface. Asset rows are immutable per id, so the response is
    long-cacheable.
    """
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
        headers = {
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400, immutable",
        }
        if asset.mime not in _INLINE_SAFE_MIMES:
            # Same policy as the full endpoint — static value, no
            # attacker-controlled filename.
            headers["Content-Disposition"] = "attachment"
            return Response(content=asset.data, media_type=asset.mime, headers=headers)
        png = _thumbnail_png(int(asset.id), bytes(asset.data))
        if png is None:
            return Response(content=asset.data, media_type=asset.mime, headers=headers)
        return Response(content=png, media_type="image/png", headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error serving design system asset thumbnail {asset_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve design system asset thumbnail",
        )


# --- Source-file browser (v1 Phase 6) ----------------------------------------

# Extensions/MIMEs that are TEXT SOURCE material in the file browser. Anything
# matched here is served as ``text/plain`` so user-uploaded markup (HTML, SVG,
# JS, …) can never render or execute in the app origin — the browser is a SOURCE
# viewer, never a preview surface (template previews go through the thumbnail
# endpoint instead). The extension fallback covers rows whose stored MIME was
# unguessable at import time.
_TEXT_SOURCE_EXTENSIONS = frozenset(
    ("md", "markdown", "css", "json", "html", "htm", "js", "mjs", "svg", "txt", "xml")
)
_TEXT_SOURCE_MIMES = frozenset(
    (
        "application/json",
        "application/javascript",
        "application/ecmascript",
        "application/xml",
    )
)

# Percent-encoded '.', '/' or '\' still present AFTER the framework's one decode
# pass — only ever seen in double-encoding smuggling attempts, so reject outright.
_ENCODED_TRAVERSAL_RE = re.compile(r"%(2e|2f|5c)", re.IGNORECASE)


def _validated_file_path(raw: str) -> Optional[str]:
    """Return ``raw`` when it is a canonical bundle-relative path, else ``None``.

    Stored ``design_system_file.path`` values are canonical by construction (the
    importer normalizes them via ``_safe_relpath``), so the browser REJECTS any
    non-canonical request instead of normalizing it into an accepted form:
    backslashes, absolute/drive paths, empty/``.``/``..`` segments, and lingering
    percent-encoded traversal bytes all fail. Lookups are DB-exact within one
    design system (no filesystem involved), so this is defence-in-depth.
    """
    if not raw or "\\" in raw:
        return None
    # NUL / C0 control characters never appear in a legitimate stored path, and
    # NUL in particular must be rejected BEFORE the DB lookup: psycopg2 refuses
    # NUL in a bound parameter (ValueError), which would surface as a 500
    # instead of the uniform opaque 404 (SQLite masks this as a no-match 404).
    if any(ord(ch) < 0x20 for ch in raw):
        return None
    if _ENCODED_TRAVERSAL_RE.search(raw):
        return None
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None
    if any(segment in ("", ".", "..") for segment in raw.split("/")):
        return None
    return raw


def _is_text_source(path: str, mime: str) -> bool:
    """True when a stored file is text source material (served as text/plain)."""
    mime_l = (mime or "").lower()
    if mime_l.startswith("text/"):
        return True
    if mime_l in _TEXT_SOURCE_MIMES or mime_l.endswith("+json") or mime_l.endswith("+xml"):
        return True
    base = path.rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    return ext in _TEXT_SOURCE_EXTENSIONS


@router.get("/{ds_id}/files", response_model=DesignSystemFileListResponse)
def list_design_system_files(ds_id: int, db: Session = Depends(get_db)):
    """List a design system's retained bundle file tree — metadata only.

    ``design_system_file`` carries the COMPLETE tree for any system imported
    since source retention (v1 Phase 1): SOURCE rows (readme/skill/css/template
    HTML) plus path-only REFERENCE rows for every asset/font (their bytes live in
    ``design_system_asset``). The listing is a column projection — byte payloads
    are never loaded, mirroring the blob-free list conventions above.
    """
    try:
        exists = db.query(DesignSystem.id).filter(DesignSystem.id == ds_id).first()
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Design system {ds_id} not found",
            )
        rows = (
            db.query(
                DesignSystemFile.path,
                DesignSystemFile.kind,
                DesignSystemFile.mime,
                DesignSystemFile.size_bytes,
            )
            .filter(DesignSystemFile.design_system_id == ds_id)
            .all()
        )
        # Sort in Python: deterministic byte order on every backend (SQL ORDER BY
        # is collation-dependent on PostgreSQL).
        rows = sorted(rows, key=lambda r: str(r[0]))
        return DesignSystemFileListResponse(
            files=[
                FileEntryOut(path=path, kind=kind, mime=mime, size_bytes=size_bytes)
                for path, kind, mime, size_bytes in rows
            ],
            total=len(rows),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing files for design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list design system files",
        )


@router.get("/{ds_id}/files/{file_path:path}")
def serve_design_system_file(ds_id: int, file_path: str, db: Session = Depends(get_db)):
    """Serve ONE stored bundle file's content — the "Open source file" endpoint.

    Security posture for user-uploaded content (mirrors the thumbnail/asset
    endpoints, hardened further because this endpoint serves markup sources):

    - The requested path must be canonical (:func:`_validated_file_path` rejects
      traversal, absolute, backslash and percent-encoded forms) and is looked up
      by EXACT match scoped to this design system; reference rows resolve their
      bytes through an ownership-checked ``design_system_asset`` lookup. Every
      failure is the same opaque 404.
    - Text sources (md/css/html/js/json/svg/…) are served as
      ``text/plain; charset=utf-8`` — uploaded markup never gets a renderable or
      executable content type.
    - EVERY response is ``Content-Disposition: attachment`` (static value — no
      attacker-controlled filename, no header injection) with
      ``X-Content-Type-Options: nosniff``; nothing is served inline.
    """
    not_found = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"File not found for design system {ds_id}",
    )
    try:
        validated = _validated_file_path(file_path)
        if validated is None:
            raise not_found
        row = (
            db.query(DesignSystemFile)
            .filter(
                DesignSystemFile.design_system_id == ds_id,
                DesignSystemFile.path == validated,
            )
            .first()
        )
        if not row:
            raise not_found
        content = row.data
        if content is None:
            # Asset/font reference row: bytes live in design_system_asset. The
            # asset must belong to the SAME design system — 404 otherwise.
            if row.asset_id is None:
                raise not_found
            asset = (
                db.query(DesignSystemAsset)
                .filter(
                    DesignSystemAsset.id == row.asset_id,
                    DesignSystemAsset.design_system_id == ds_id,
                )
                .first()
            )
            if not asset:
                raise not_found
            content = asset.data
        media_type = (
            "text/plain; charset=utf-8"
            if _is_text_source(str(row.path), str(row.mime))
            else str(row.mime)
        )
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "attachment",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving file for design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve design system file",
        )
