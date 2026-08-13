"""Design System Library API endpoints (Phase 3).

CRUD + bundle import for org-shared design systems. Mirrors the slide-styles
router (``slide_styles.py``): design systems are company-wide assets (everyone
can view/use), ``created_by`` records authorship, and a single ``is_default``
marks the org default. A design system compiles to ``compiled_style_content`` —
the drop-in equivalent of ``slide_style_library.style_content`` — so it flows
through the existing generation seam (see ``agent_factory._get_prompt_content``).

Name uniqueness: creation/import return **409 Conflict** on a duplicate name
(spec §6), matching the slide-styles convention. This is deliberately
non-destructive — an org-shared asset is never silently overwritten; the caller
supplies a different name (import accepts a ``name`` form field) to import a copy.

Uniqueness is scoped to **LIVE** rows, at both layers: the pre-checks here filter
``is_active``, and the database enforces the partial unique index
``uq_design_system_name_active`` (``WHERE is_active``). A whole-table rule made the
soft DELETE below reserve the name FOREVER — the tombstone is hidden from the list
endpoint, so a user who deleted a design system could never re-import under the same
name and had nothing left to delete. A name held only by a tombstone is free.
"""
import logging
import os
import re
import unicodedata
from collections import OrderedDict
from typing import Any, List, Optional, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.core.database import get_db
from src.core.permission_context import get_permission_context
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
    DesignSystemNameTooLongError,
    translate_name_index_limit_error,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design-systems", tags=["design-systems"])


# --- Schemas ---------------------------------------------------------------


class TokenIn(BaseModel):
    # NO max_length on any of the three. These are FREE-FORM BRAND TEXT, and the
    # storage columns are unbounded ``Text`` (see
    # ``database/models/design_system.py``); the two layers must move TOGETHER,
    # because a cap at EITHER one still turns the brand away with
    # ``string_too_long`` — which is exactly how this defect survived the round that
    # widened only the storage column.
    #
    # The caps were 50/100, then 255/255. Each widening was reopened by a longer
    # real-world string, because the NUMBER was never the problem: a bundle import
    # is one request, so one over-length token failed the WHOLE import and cost
    # every other token in the bundle. The compiler imposes no cap of its own (it
    # sanitizes, never rejects), so nothing downstream needs a bound either.
    #
    # ``min_length=1`` is KEPT: an empty group/name/value is a malformed token, not
    # brand data. Only the MAXIMUM is a brand-hostile limit.
    group: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


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
    # Brand font family names (from font_mapping_json) so the picker can show
    # its "font stack · N templates" subtitle without fetching the detail.
    font_families: List[str] = []
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
    # UNCAPPED, matching the unbounded ``design_system.name`` column; ``min_length``
    # is kept because an empty name is malformed. See ``TokenIn``.
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    tokens: Optional[List[TokenIn]] = None
    manifest_json: Optional[dict] = None


class DesignSystemUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
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


# Unicode categories whose members carry no visible content:
#   Cf format (zero-width family, BOM, soft hyphen, bidi marks, U+180E)
#   Cc control, Cs surrogate, Co private-use, Cn unassigned
#   Zs/Zl/Zp separators (space, U+3000, NBSP, U+2028/U+2029, …)
#   Mn/Me non-spacing and enclosing marks — no standalone glyph
# A string made only of these is semantically EMPTY however long it is.
_INVISIBLE_CATEGORIES = frozenset(
    {"Cf", "Cc", "Cs", "Co", "Cn", "Zs", "Zl", "Zp", "Mn", "Me"}
)

# Characters that DO render nothing but whose category says otherwise, so no
# category rule can catch them. This is an explicit escape hatch, not the primary
# mechanism — the categories above carry the general case.
#
# Each entry is here because it was demonstrated, and each cost a review round:
#   U+3164 / U+115F / U+1160  Hangul fillers   — category Lo (a LETTER)
#   U+2800                    BRAILLE BLANK    — category So (a SYMBOL); this is
#                             the all-dots-lowered braille cell, which by
#                             definition paints nothing, unlike every other
#                             braille code point.
# The TEST for this predicate is table-driven over the PROPERTY ("renders no
# glyph") rather than over this list, so a new member is caught by a failing test
# rather than by another review round.
_INVISIBLE_CHARS = frozenset({"ㅤ", "ᅟ", "ᅠ", "⠀"})


def _is_blank_identity(value: Optional[str]) -> bool:
    """True when *value* renders no visible glyph, so it names nobody.

    The QUESTION is deliberately "does anything render", not "is anything
    unusual". ``str.strip()`` was not sufficient (it leaves zero-width Cf
    characters), then Cf/Cc/Zs/Zl/Zp was not sufficient (the Hangul fillers are
    Lo), then that was not sufficient either (U+2800 BRAILLE BLANK is So). Each
    round added the code point just demonstrated; the fix is to ask the property
    of every character and keep the explicit set as a small escape hatch for
    characters whose category lies.

    Normalizes NFKC first, so a compatibility form cannot smuggle a
    visible-looking but empty character past the test, then requires at least one
    character that is neither in an invisible CATEGORY nor in
    :data:`_INVISIBLE_CHARS`.

    Used ONLY to decide blankness — never to compare two identities, which stays
    an EXACT match on the raw values, so trailing whitespace and case differences
    still denote DIFFERENT principals and still fail closed.
    """
    if not value:
        return True
    normalized = unicodedata.normalize("NFKC", value)
    return all(
        unicodedata.category(ch) in _INVISIBLE_CATEGORIES
        or ch in _INVISIBLE_CHARS
        for ch in normalized
    )


def _require_creator_or_admin(ds: DesignSystem) -> None:
    """Require the caller to be ``ds``'s author, or a workspace admin.

    Design systems are org-shared, user-CONTRIBUTED content: any user may add
    one (create/import stay open) and manage the ones they uploaded, nobody may
    touch someone else's, and admins may manage anything. Used by PUT and
    DELETE. ``set-default`` stays admin-only — it changes what EVERY user gets
    by default, so authorship does not buy it.

    ORG-DEFAULT FREEZE (product owner's decision: "only admin when it's org
    default"). Creator-or-admin alone was not enough: a non-admin CREATOR could
    DELETE the ACTIVE ORG DEFAULT and get 204, leaving the row inactive and
    unflagged while OTHER users' sessions still pointed at that id — so an
    admin's act of promoting a system to org default could be undone by the
    row's author. While ``ds.is_default`` is set, rename/delete on THAT row are
    therefore ADMIN-ONLY; authorship stops buying them at exactly the moment the
    row becomes org-wide state. Creators keep full control of every NON-default
    system they uploaded, so the contribute-and-manage story is untouched.

    ``is_default`` is read from the LOADED ROW, inside the caller's transaction —
    never from request input, so a caller cannot present themselves a
    non-default row to unfreeze one. The branch is evaluated FIRST, before the
    authorship comparison, so the creator branch cannot short-circuit it; both
    call sites run this gate before any mutation or expensive work.

    Identity comes from ``get_permission_context().user_name``, which the OBO
    middleware derives server-side from the caller's authenticated token
    (``src/api/main.py``: ``user_client.current_user.me()``, or ``DEV_USER_ID``
    locally). It is never read from the request body, query string or a client
    header, so a caller cannot assert someone else's identity. The creator half
    of the check follows the house pattern at ``src/api/routes/profiles.py:191``
    (``perm_ctx.user_name == created_by``, guarded on both values being
    truthy); the admin half delegates to the SDR-4437 ``require_admin``
    primitive unchanged.

    ``design_system.created_by`` is NULLABLE and legacy rows may hold NULL or a
    blank string. Such rows are ADMIN-ONLY: an author-less row must never
    become "anyone may manage this", and a blank/unresolved CALLER must never
    match a blank OWNER, so both sides must be non-blank for the creator branch
    to fire. Anything else falls through to ``require_admin``.

    "Non-blank" is decided by :func:`_is_blank_identity`, which treats anything
    VISUALLY empty as blank — ``str.strip()`` alone let a zero-width character
    (category Cf: not ``isspace()``, untouched by ``strip()``) present as a real
    name on both sides and satisfy the creator branch, and a Hangul FILLER did
    the same past the category test by normalizing to a letter. The blankness
    TEST is the only thing that normalizes; the identity COMPARISON below is
    EXACT on the raw values, so two principals whose names differ only by
    invisible characters, by surrounding whitespace, or by case remain different
    principals and still fail closed.

    Raises:
        HTTPException 403: caller is neither the author nor an admin, or the row
            is the org default and the caller is not an admin.
    """
    # The org default is org-wide state, so authorship does not buy managing it.
    # Read off the LOADED ROW (never request input) and decided BEFORE the
    # authorship comparison, so being the creator cannot bypass the freeze.
    if bool(ds.is_default):
        # Admin-only. require_admin is still the ONE admin primitive (SDR-4437) —
        # its verdict is not reimplemented here; only the 403's detail is
        # rewritten, so the reason is debuggable instead of a generic "Admin
        # access required" that looks identical to the not-the-author denial.
        #
        # Non-disclosure: the message names the REASON (this row is the org
        # default) and nothing about the row's contents or authorship. Reads on
        # this router are OPEN by design, so any authenticated caller can already
        # GET the row and see ``is_default`` — this reveals nothing they could not
        # otherwise tell, and it is only ever reached for a row that was loaded
        # (a missing row 404s earlier, in the handler).
        try:
            require_admin()
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This design system is the organization default; only a "
                    "workspace admin can rename or delete it. Ask an admin to "
                    "make a different design system the default first."
                ),
            ) from None
        return

    perm_ctx = get_permission_context()
    # RAW values: blankness is decided by ``_is_blank_identity`` (which may
    # normalize), and the identity COMPARISON is then exact on what was actually
    # stored and resolved. Stripping both sides first — as this did — quietly made
    # ``"creator@test.com "`` and ``"creator@test.com"`` the same principal, which
    # contradicts the exact-match contract documented above.
    caller = perm_ctx.user_name if perm_ctx else None
    # ``cast`` only tells mypy what the ORM already returns at runtime (a str or
    # None, not a Column); it performs NO conversion, so the comparison below
    # stays exact on the stored value.
    created_by = cast(Optional[str], ds.created_by)
    is_creator = (
        not _is_blank_identity(caller)
        and not _is_blank_identity(created_by)
        and caller == created_by
    )
    if is_creator:
        return
    # Not the author (or authorship is unknown/blank) — admin-only from here.
    # require_admin raises 403 itself; same status as the creator-denied path,
    # so an unauthorised caller cannot tell the two apart.
    require_admin()


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
    return f"{_asset_url(ds_id, int(asset.id))}/thumbnail"


def _font_families(font_mapping_json: Any) -> List[str]:
    """Sorted family names from ``font_mapping_json`` (scalar JSON-column read)."""
    families = (
        font_mapping_json.get("families")
        if isinstance(font_mapping_json, dict)
        else None
    )
    if not isinstance(families, list):
        return []
    return sorted(
        {
            str(f["family"]).strip()
            for f in families
            if isinstance(f, dict) and str(f.get("family") or "").strip()
        }
    )


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
        font_families=_font_families(ds.font_mapping_json),
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
                thumbnail_url=_asset_thumbnail_url(int(ds.id), a),
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
            db,
            zip_bytes=content,
            user=_current_user(),
            name_override=name,
            source_filename=file.filename,
        )
        return _detail(ds)
    except DesignSystemNameConflictError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    # A name the UNIQUE index cannot hold is the CALLER's to fix, so it must not fall
    # through to the generic 500 below — a 500 on a legitimate upload is a bug.
    except DesignSystemNameTooLongError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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
        # LIVE rows only, matching the partial unique index
        # ``uq_design_system_name_active``. A soft-deleted system's name is free to
        # reuse — see the DesignSystem model's note on the name column.
        existing = (
            db.query(DesignSystem)
            .filter(DesignSystem.name == request.name, DesignSystem.is_active == True)  # noqa: E712
            .first()
        )
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
        # The UNIQUE index on ``name`` has to hold the value here; whether it can is
        # the database's call, so its refusal is translated into a 400 rather than
        # predicted beforehand (see translate_name_index_limit_error).
        try:
            db.flush()
            recompute_compiled_style_content(ds)
            db.commit()
        except Exception as exc:
            translate_name_index_limit_error(exc, name=request.name)
            raise
        db.refresh(ds)
        logger.info(f"Created design system: {ds.name} (id={ds.id})")
        return _detail(ds)
    except HTTPException:
        raise
    except DesignSystemNameTooLongError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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


# SDR-4437 HIGH-3 / Option C: rename is CREATOR-OR-ADMIN. The gate needs the
# row (to read created_by), so it runs in the handler rather than as a route
# dependency — see _require_creator_or_admin.
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
        _require_creator_or_admin(ds)

        if request.name and request.name != ds.name:
            # LIVE rows only, matching the partial unique index
            # ``uq_design_system_name_active`` — the same reason as create/import: a
            # tombstone must not reserve a name the picker no longer shows.
            clash = (
                db.query(DesignSystem)
                .filter(
                    DesignSystem.name == request.name,
                    DesignSystem.id != ds_id,
                    DesignSystem.is_active == True,  # noqa: E712
                )
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
        # As on create: a rename the UNIQUE index cannot hold is refused by the
        # database, and its refusal becomes a 400. The rollback in the handler below
        # leaves the row's existing name intact.
        try:
            db.flush()
            recompute_compiled_style_content(ds)
            db.commit()
        except Exception as exc:
            translate_name_index_limit_error(exc, name=request.name)
            raise
        db.refresh(ds)
        logger.info(f"Updated design system: {ds.name} (id={ds.id})")
        return _detail(ds)
    except HTTPException:
        raise
    except DesignSystemNameTooLongError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating design system {ds_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update design system",
        )


# SDR-4437 HIGH-3 / Option C: delete is CREATOR-OR-ADMIN. The gate needs the
# row (to read created_by), so it runs in the handler rather than as a route
# dependency — see _require_creator_or_admin.
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
        _require_creator_or_admin(ds)

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


# SDR-4437 HIGH-3: workspace-global library writes are admin-only.
@router.post(
    "/{ds_id}/set-default", response_model=DesignSystemDetail,
    dependencies=[Depends(require_admin)],
)
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
    # Serve-time resolution (dsv2 F8): the preview frame is sandboxed behind a
    # no-egress CSP, so {{ds-asset:ID}} handles must leave here as inline
    # data: URIs. The stored row keeps its handles for generation. Resolution is
    # scoped to the template's OWNING design system (this row was already fetched
    # under design_system_id == ds_id) so a crafted bundle's foreign handle can
    # never disclose another system's asset bytes.
    from src.services.design_system_templates import resolve_template_source_for_preview

    owning_ds_id = int(template.design_system_id)
    return TemplateSourceOut(
        id=int(template.id),
        name=str(template.name),
        layout_html=resolve_template_source_for_preview(
            str(template.layout_html), db, design_system_id=owning_ds_id
        )
        or "",
        token_css=(
            resolve_template_source_for_preview(
                str(template.token_css), db, design_system_id=owning_ds_id
            )
            if template.token_css is not None
            else None
        ),
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

# Deliberate app-level decompressed-pixel ceiling (~8k x 8k), checked from
# the image HEADER before any pixel decode. A crafted small-bytes/huge-
# dimensions file must never buy an unbounded decode; PIL's own
# DecompressionBomb guard stays as the outer net.
_MAX_DECODE_PIXELS = 64_000_000


def _thumbnail_png(asset_id: int, data: bytes) -> Optional[bytes]:
    """Downscale raster bytes to a <=128px PNG, LRU-cached per asset id.

    ``None`` on any decode/encode failure (corrupt file, pixel-ceiling or
    decompression-bomb guard, unsupported subformat) — the endpoint then
    falls back to serving the original bytes, exactly what the grid loaded
    before this existed. Never a 500.
    """
    cached = _thumbnail_cache.get(asset_id)
    if cached is not None:
        _thumbnail_cache.move_to_end(asset_id)
        return cached
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as im:
            # Header-declared dimensions, available before any pixel decode.
            if im.width * im.height > _MAX_DECODE_PIXELS:
                logger.warning(
                    "Asset %s exceeds the thumbnail pixel ceiling "
                    "(%dx%d > %d px); serving original bytes without decoding",
                    asset_id,
                    im.width,
                    im.height,
                    _MAX_DECODE_PIXELS,
                )
                return None
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
            return Response(content=asset.data, media_type=str(asset.mime), headers=headers)
        png = _thumbnail_png(int(asset.id), bytes(asset.data))
        if png is None:
            return Response(content=asset.data, media_type=str(asset.mime), headers=headers)
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
