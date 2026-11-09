"""AI image generation routes.

On by default. A deployment opts out with ``TELLR_IMAGE_GENERATION_ENABLED=0`` and an admin
can turn it off (``workspace_settings``); both are checked on every request.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.api.routes import images as images_routes
from src.api.routes.images import ImageResponse
from src.api.services import image_generation_jobs as jobs
from src.core.database import get_db
from src.database.models.image import ImageAsset
from src.services.image_generation import (
    DEFAULT_PRESET,
    IMAGE_MODELS,
    MAX_PROMPT_CHARS,
    PRESETS,
    QUALITIES,
    QUALITY_DESCRIPTIONS,
    generation_available,
    is_enabled,
    resolve_request,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/images", tags=["image-generation"])

if is_enabled():
    logger.info(
        "AI image generation is offered on this deployment "
        "(turn it off with TELLR_IMAGE_GENERATION_ENABLED=0)"
    )


def _effective_enabled(db: Session) -> bool:
    """Env capability AND the admin setting, read on every request (never cached)."""
    return generation_available(db)


def require_image_generation_enabled(db: Session = Depends(get_db)) -> None:
    if not _effective_enabled(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


# --- Schemas ---

class GenerateImageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # a blank prompt is no prompt
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    preset: str = DEFAULT_PRESET
    model: Optional[str] = None
    quality: Optional[str] = None


class EditImageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # a blank prompt is no prompt
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    model: Optional[str] = None
    quality: Optional[str] = None


class ImageGenerationJobResponse(BaseModel):
    job_id: str
    status: str
    progress: int = 0
    total_slides: int = 0
    status_message: Optional[str] = None
    error: Optional[str] = None
    image: Optional[ImageResponse] = None


class ImageModelOption(BaseModel):
    id: str
    label: str
    description: str


class ImagePresetOption(BaseModel):
    id: str
    label: str
    description: str
    output_format: str
    category: str
    transparent: bool
    models: List[ImageModelOption]
    default_model: str
    qualities: List[str]
    default_quality: str


class ImageEditOptions(BaseModel):
    models: List[ImageModelOption]
    default_model: str
    qualities: List[str]
    default_quality: str


class ImageGenerationOptions(BaseModel):
    available: bool
    max_prompt_chars: int
    default_preset: Optional[str] = None
    presets: List[ImagePresetOption] = []
    edit: Optional[ImageEditOptions] = None
    #: What each quality is for, shown under the Quality picker.
    quality_descriptions: Dict[str, str] = {}


# --- Helpers ---

def _model_option(model_id: str) -> ImageModelOption:
    spec = IMAGE_MODELS[model_id]
    return ImageModelOption(id=spec.id, label=spec.label, description=spec.description)


def _edit_model_ids() -> List[str]:
    """Models that can produce raster output: those any non-SVG preset offers."""
    ids: List[str] = []
    for preset in PRESETS.values():
        if preset.output_format == "svg":
            continue
        for model_id in preset.models:
            if model_id not in ids:
                ids.append(model_id)
    return ids


def _job_response(info: dict, db: Session) -> ImageGenerationJobResponse:
    image = None
    if info["status"] == "completed" and info.get("image_token"):
        row = db.query(ImageAsset).filter(ImageAsset.token == info["image_token"]).first()
        if row is not None:
            image = images_routes._image_to_response(row)
    return ImageGenerationJobResponse(
        job_id=info["job_id"],
        status=info["status"],
        status_message=info["status_message"],
        error=info["error"],
        image=image,
    )


def _start(job_id: str, owner: str, spec) -> ImageGenerationJobResponse:
    if not jobs.submit(job_id, owner=owner, spec=spec):
        try:
            jobs._update_job(
                job_id, jobs.get_db_session,
                status="error", status_message="Failed",
                error_message="Too many image jobs are running. Try again shortly.",
                completed_at=datetime.utcnow(),
            )
        except Exception:
            logger.error("Could not mark refused image job %s", job_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many image jobs are running. Try again shortly.",
        )
    return ImageGenerationJobResponse(job_id=job_id, status="pending", status_message="Queued")


# --- Endpoints ---

@router.get("/generate/available", response_model=ImageGenerationOptions)
def image_generation_available(db: Session = Depends(get_db)) -> ImageGenerationOptions:
    """Whether generation is enabled, with the choices the UI may offer. Never flag-gated."""
    if not _effective_enabled(db):
        return ImageGenerationOptions(available=False, max_prompt_chars=0)
    default = PRESETS[DEFAULT_PRESET]
    presets = [
        ImagePresetOption(
            id=p.id, label=p.label, description=p.description,
            output_format=p.output_format, category=p.category, transparent=p.transparent,
            models=[_model_option(m) for m in p.models],
            default_model=p.default_model, qualities=list(QUALITIES),
            default_quality=p.default_quality,
        )
        for p in PRESETS.values()
    ]
    edit = ImageEditOptions(
        models=[_model_option(m) for m in _edit_model_ids()],
        default_model=default.default_model,
        qualities=list(QUALITIES),
        default_quality=default.default_quality,
    )
    return ImageGenerationOptions(
        available=True, max_prompt_chars=MAX_PROMPT_CHARS,
        default_preset=DEFAULT_PRESET, presets=presets, edit=edit,
        quality_descriptions=dict(QUALITY_DESCRIPTIONS),
    )


@router.post(
    "/generate",
    response_model=ImageGenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_image_generation_enabled)],
)
def start_generation(body: GenerateImageRequest) -> ImageGenerationJobResponse:
    try:
        resolve_request(body.preset, body.model, body.quality)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    owner = images_routes._get_current_user()
    job_id = jobs.create_job(owner=owner, title=body.prompt)
    spec = jobs.GenerationSpec(
        prompt=body.prompt, preset_id=body.preset, model=body.model, quality=body.quality
    )
    return _start(job_id, owner, spec)


@router.post(
    "/{token}/edit",
    response_model=ImageGenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_image_generation_enabled)],
)
def start_edit(
    token: str, body: EditImageRequest, db: Session = Depends(get_db)
) -> ImageGenerationJobResponse:
    image = db.query(ImageAsset).filter(
        ImageAsset.token == token, ImageAsset.is_active == True  # noqa: E712
    ).first()
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    images_routes._deny_ephemeral_cross_user(image)
    if image.mime_type == "image/svg+xml":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="SVG images cannot be edited"
        )
    allowed = _edit_model_ids()
    if body.model is not None and body.model not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported model")
    if body.quality is not None and body.quality not in QUALITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported quality")

    owner = images_routes._get_current_user()
    spec = jobs.EditSpec(
        prompt=body.prompt,
        source_bytes=bytes(image.image_data),
        source_mime=image.mime_type,
        source_name=image.original_filename,
        source_category=image.category or "content",
        model=body.model,
        quality=body.quality,
    )
    job_id = jobs.create_job(owner=owner, title=body.prompt)
    return _start(job_id, owner, spec)


@router.get(
    "/generate/jobs/{job_id}",
    response_model=ImageGenerationJobResponse,
    dependencies=[Depends(require_image_generation_enabled)],
)
def poll_generation(job_id: str, db: Session = Depends(get_db)) -> ImageGenerationJobResponse:
    owner = images_routes._get_current_user()
    info = jobs.get_job(job_id, owner=owner)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_response(info, db)
