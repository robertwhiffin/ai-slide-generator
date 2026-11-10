"""AI image generation for the Image Library.

Pure helpers (presets, tool dicts, prompts, image fitting) plus an
:class:`ImageGenerator` that calls the Unity AI Gateway Responses API with the
``image_generation`` tool.

Probe-driven rules (docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md):

* rasters MUST stream (a non-streamed response over 640 KB is rejected), and
  the image is taken from the ``response.output_item.done`` event;
* SVG is non-streamed and read from ``response.output``;
* ``tool_choice`` is always forced to ``image_generation``;
* never send ``partial_images``, ``reasoning``, ``background="opaque"`` or
  ``instructions``; ``complexity`` only to 2.6 models and only if the preset
  sets it;
* ``with_options()`` is broken on ``DatabricksOpenAI``: the client is built
  with ``max_retries=0`` and the timeout is passed per request.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import openai
from PIL import Image, UnidentifiedImageError

from src.core.databricks_client import get_system_client
from src.services import image_service, workspace_settings
from src.services.gateway_clients import gateway_openai_client

logger = logging.getLogger(__name__)

ENV_FLAG = "TELLR_IMAGE_GENERATION_ENABLED"
ORCHESTRATOR_ENV = "TELLR_IMAGE_GEN_ORCHESTRATOR_MODEL"
DEFAULT_ORCHESTRATOR_MODEL = "system.ai.gpt-5-4-nano"
MAX_PROMPT_CHARS = 2000
QUALITIES: tuple[str, ...] = ("low", "medium", "high")
#: What each quality is for, shown under the Quality picker. Measured live: medium costs about
#: the same time as low, so it is the default.
QUALITY_DESCRIPTIONS: dict[str, str] = {
    "low": "Fastest and cheapest. Good for trying out ideas.",
    "medium": "Recommended. Good detail at about the same speed as low.",
    "high": "Most detail, for hero images. A little slower and costs more.",
}
DEFAULT_PRESET = "icon_png"
SVG_THUMBNAIL_MAX_BYTES = 200 * 1024

_FORCED_TOOL_CHOICE = {"type": "image_generation"}
_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
}
_PIL_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif"}
_SVG_DATA_URI_PREFIX = "data:image/svg+xml;base64,"
_EDIT_TIMEOUT_S = 180


# ---------------------------------------------------------------------------
# Models and presets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageModelSpec:
    id: str
    label: str
    description: str
    supports_transparent: bool
    supports_svg: bool
    supports_complexity: bool


IMAGE_MODELS: dict[str, ImageModelSpec] = {
    spec.id: spec
    for spec in (
        ImageModelSpec(
            "gpt-image-2.5-flare",
            "GPT Image 2.5 Flare",
            "Previous generation with a softer, moodier look (about 12 to 15 s). Try it when "
            "2.6 isn't giving you the style you want.",
            True,
            False,
            False,
        ),
        ImageModelSpec(
            "gpt-image-2.5-sunburst",
            "GPT Image 2.5 Sunburst",
            "Rich detail and the most precise edits of the 2.5 models, but slow (about 18 s). "
            "Use it for a hero image, or an edit that must change only what you ask.",
            True,
            False,
            False,
        ),
        ImageModelSpec(
            "gpt-image-2.6-flare",
            "GPT Image 2.6 Flare (recommended)",
            "Best all-round choice: the newest and fastest model (about 8 to 14 s), with clean "
            "icons, backgrounds and illustrations, and fast SVG icons.",
            True,
            True,
            True,
        ),
        ImageModelSpec(
            "gpt-image-2.6-sunburst",
            "GPT Image 2.6 Sunburst",
            "The most detailed model, SVG included, but the slowest (about 20 s). Use it for "
            "intricate illustrations or detailed vector art when you can wait.",
            True,
            True,
            True,
        ),
    )
}

_ALL_MODELS = tuple(IMAGE_MODELS)
_SVG_MODELS = tuple(m for m, spec in IMAGE_MODELS.items() if spec.supports_svg)

_ICON_DIRECTION = (
    "Style: a single, centered subject; flat design with a consistent stroke weight; "
    "no text, no glow, no drop shadow, and no background tile or circle behind the subject; "
    "generous padding around the subject."
)


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    description: str
    size: str | None
    output_format: str
    transparent: bool
    category: str
    art_direction: str
    models: tuple[str, ...]
    default_model: str
    default_quality: str
    complexity: str | None
    timeout_s: int


PRESETS: dict[str, Preset] = {
    p.id: p
    for p in (
        Preset(
            id="background",
            label="Background",
            description="Widescreen 16:9 slide background with room for titles.",
            size="2048x1152",
            output_format="jpeg",
            transparent=False,
            category="background",
            art_direction=(
                "Style: a subtle, widescreen slide background with plenty of negative space "
                "for titles and body text; soft, low-contrast composition; "
                "no text or logos."
            ),
            models=_ALL_MODELS,
            default_model="gpt-image-2.6-flare",
            default_quality="medium",
            complexity=None,
            timeout_s=180,
        ),
        Preset(
            id="illustration",
            label="Illustration",
            description="3:2 illustration for the body of a slide.",
            size="1536x1024",
            output_format="jpeg",
            transparent=False,
            category="content",
            art_direction=(
                "Style: a clean, modern illustration with a clear focal point and a "
                "cohesive palette; no text or logos."
            ),
            models=_ALL_MODELS,
            default_model="gpt-image-2.6-flare",
            default_quality="medium",
            complexity=None,
            timeout_s=180,
        ),
        Preset(
            id="icon_png",
            label="Icon (PNG)",
            description="Square icon with a transparent background.",
            size="1024x1024",
            output_format="png",
            transparent=True,
            category="content",
            art_direction=_ICON_DIRECTION + " The background must be fully transparent.",
            models=_ALL_MODELS,
            default_model="gpt-image-2.6-flare",
            default_quality="medium",
            complexity=None,
            timeout_s=180,
        ),
        Preset(
            id="icon_svg",
            label="Icon (SVG)",
            description="Scalable vector icon (SVG models only).",
            size=None,
            output_format="svg",
            transparent=True,
            category="content",
            art_direction=_ICON_DIRECTION + " Output simple, static vector shapes only.",
            models=_SVG_MODELS,
            default_model="gpt-image-2.6-flare",
            default_quality="medium",
            complexity="low",
            timeout_s=240,
        ),
    )
}


#: ``ENV_FLAG`` values that turn the feature off for a deployment; unset or anything else is on.
_ENV_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def is_enabled() -> bool:
    """On by default; a deployment opts out with ``TELLR_IMAGE_GENERATION_ENABLED=0``."""
    return os.getenv(ENV_FLAG, "").strip().lower() not in _ENV_OFF_VALUES


def generation_available(db: Any) -> bool:
    """Env capability AND the admin setting; the settings table is not read when the env is off."""
    return is_enabled() and workspace_settings.image_generation_enabled(db)


def orchestrator_model() -> str:
    return os.getenv(ORCHESTRATOR_ENV) or DEFAULT_ORCHESTRATOR_MODEL


def resolve_request(
    preset_id: str, model: str | None, quality: str | None
) -> tuple[Preset, str, str]:
    """Validate a request against the preset table, applying defaults."""
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise ValueError(f"Unknown preset: {preset_id!r}")
    model = model or preset.default_model
    if model not in preset.models:
        raise ValueError(f"Model {model!r} is not available for preset {preset_id!r}")
    quality = quality or preset.default_quality
    if quality not in QUALITIES:
        raise ValueError(f"Unknown quality: {quality!r}")
    return preset, model, quality


def build_tool(preset: Preset, model: str, quality: str) -> dict[str, Any]:
    """The ``image_generation`` tool dict for a preset (a fresh dict each call)."""
    tool: dict[str, Any] = {
        "type": "image_generation",
        "model": model,
        "quality": quality,
        "output_format": preset.output_format,
    }
    if preset.output_format != "svg":
        tool["size"] = preset.size
        if preset.transparent:
            tool["background"] = "transparent"
    spec = IMAGE_MODELS.get(model)
    if preset.complexity and spec is not None and spec.supports_complexity:
        tool["complexity"] = preset.complexity
    return tool


def build_prompt(user_prompt: str, preset: Preset) -> str:
    return f"{user_prompt}\n\n{preset.art_direction}"


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def _has_alpha(img: Image.Image) -> bool:
    """True when some pixel is actually transparent, not merely when an alpha channel exists.

    Screenshots and design-tool exports are often RGBA with every pixel opaque; treating them
    as transparent would ask the model to cut out a background the user wants kept.
    """
    if not (img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)):
        return False
    return img.convert("RGBA").getchannel("A").getextrema()[0] < 255


def to_data_url(data: bytes, max_side: int = 1536) -> str:
    """Bound an image's longest side and encode it as a data URL.

    Images with alpha stay PNG so the model sees the transparency; everything
    else becomes JPEG.
    """
    img = Image.open(io.BytesIO(data))
    img.load()
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize(
            (max(1, round(img.width * ratio)), max(1, round(img.height * ratio))),
            Image.LANCZOS,
        )
    buf = io.BytesIO()
    if _has_alpha(img):
        img.convert("RGBA").save(buf, format="PNG")
        mime = "image/png"
    else:
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


_FENCE = re.compile(r"^\s*```[A-Za-z0-9_-]*[ \t]*\n(.*?)\n?[ \t]*```\s*$", re.DOTALL)


def flatten_on_white(data: bytes) -> bytes:
    """``data`` composited onto an opaque white background, as PNG (RGB)."""
    with Image.open(io.BytesIO(data)) as img:
        rgba = img.convert("RGBA")
    flat = Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba)
    buf = io.BytesIO()
    flat.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def strip_code_fences(text: str) -> str:
    match = _FENCE.match(text)
    return match.group(1) if match else text.strip()


_UNSAFE_SVG = re.compile(
    r"<script|<foreignObject|\son\w+\s*=|(?:href|src)\s*=\s*[\"']\s*(?:https?:|javascript:|data:text)",
    re.IGNORECASE,
)


def check_static_svg(svg: str) -> None:
    """Raise ValueError unless *svg* is SVG with no scripts, handlers or external references."""
    if "<svg" not in svg[:2000].lower():
        raise ValueError("model output is not SVG markup")
    if _UNSAFE_SVG.search(svg):
        raise ValueError("SVG contains scripts, event handlers or external references")


def _encode(img: Image.Image, fmt: str, quality: int | None = None) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=quality or 85)
    else:
        img.save(buf, format=fmt, optimize=True)
    return buf.getvalue()


def _scaled(img: Image.Image, factor: float) -> Image.Image:
    return img.resize(
        (max(1, round(img.width * factor)), max(1, round(img.height * factor))),
        Image.LANCZOS,
    )


def _shrink(img: Image.Image, fmt: str, max_bytes: int) -> bytes:
    """Re-encode *img* as *fmt* under *max_bytes*, scaling by 0.8 steps if needed."""
    qualities = (85, 75, 65) if fmt == "JPEG" else (None,)
    if fmt == "PNG" and img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if _has_alpha(img) else "RGB")
    factor = 1.0
    while True:
        current = img if factor == 1.0 else _scaled(img, factor)
        for q in qualities:
            data = _encode(current, fmt, q)
            if len(data) <= max_bytes:
                return data
        factor *= 0.8
        if min(img.size) * factor < 8:
            raise ValueError(f"Cannot shrink image under {max_bytes} bytes")


def fit_to_library(
    raw: bytes, *, max_bytes: int = image_service.MAX_FILE_SIZE
) -> tuple[bytes, str, str]:
    """Return ``(data, mime, ext)`` that Image Library accepts.

    The real format is sniffed with Pillow.  PNG/JPEG/GIF under the cap pass
    through unchanged; WebP and other formats become PNG (alpha) or JPEG.
    Oversize images are shrunk, keeping alpha and aspect ratio.
    """
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Image data could not be decoded") from exc

    fmt = img.format
    if fmt in _PIL_FORMATS:
        mime = _PIL_FORMATS[fmt]
        if len(raw) <= max_bytes:
            return raw, mime, _EXTENSIONS[mime]
        target = "JPEG" if fmt == "JPEG" else "PNG"  # GIF -> PNG when it must be shrunk
    else:
        target = "PNG" if _has_alpha(img) else "JPEG"

    data = _shrink(img, target, max_bytes)
    mime = _PIL_FORMATS[target]
    return data, mime, _EXTENSIONS[mime]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-") or "image"


def generated_filename(prompt: str, ext: str, *, prefix: str = "ai") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{_slug(prompt)[:40]}-{stamp}-{uuid.uuid4().hex[:8]}.{ext}"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass
class GeneratedImage:
    data: bytes
    mime: str
    ext: str
    model: str
    preset_id: str | None
    revised_prompt: str | None
    latency_s: float
    usage: dict | None


class ImageGenerationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def default_client() -> Any:
    """Gateway client with no SDK retries (a retry would be a second paid generation)."""
    return gateway_openai_client(get_system_client(), max_retries=0)


def _usage_dict(usage: Any) -> dict | None:
    if usage is None:
        return None
    return usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)


def _short(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


class ImageGenerator:
    def __init__(
        self,
        client_factory: Callable[[], Any] = default_client,
        orchestrator: str | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._orchestrator = orchestrator

    # -- public ---------------------------------------------------------

    def generate(
        self,
        prompt: str,
        preset_id: str,
        model: str | None = None,
        quality: str | None = None,
        *,
        timeout_s: float | None = None,
    ) -> GeneratedImage:
        preset, model, quality = resolve_request(preset_id, model, quality)
        tool = build_tool(preset, model, quality)
        effective_timeout = (
            preset.timeout_s
            if timeout_s is None
            else min(preset.timeout_s, max(5.0, timeout_s))
        )
        return self._run(
            input_=build_prompt(prompt, preset),
            tool=tool,
            model=model,
            quality=quality,
            preset_id=preset.id,
            timeout_s=effective_timeout,
            stream=preset.output_format != "svg",
            svg=preset.output_format == "svg",
            prompt=prompt,
        )

    def edit(
        self,
        prompt: str,
        source: bytes,
        source_mime: str,
        model: str | None = None,
        quality: str | None = None,
    ) -> GeneratedImage:
        default = PRESETS[DEFAULT_PRESET]
        model = model or default.default_model
        quality = quality or default.default_quality
        if model not in IMAGE_MODELS:
            raise ValueError(f"Unknown image model: {model!r}")
        if quality not in QUALITIES:
            raise ValueError(f"Unknown quality: {quality!r}")
        if source_mime == "image/svg+xml":
            raise ValueError("SVG images cannot be edited with a prompt")
        try:
            src = Image.open(io.BytesIO(source))
            src.load()
            transparent = _has_alpha(src)
            # The model reads transparency as black: a transparent icon sent as-is comes back
            # as a dark "neon" edit with no usable alpha. Show it the icon on white instead and
            # ask the tool for a transparent result (verified on the Gateway, 2026-11-08).
            image_url = to_data_url(flatten_on_white(source) if transparent else source)
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Source image could not be decoded") from exc
        if transparent:
            prompt = f"{prompt}\n\nKeep the background fully transparent."

        tool: dict[str, Any] = {
            "type": "image_generation",
            "model": model,
            "quality": quality,
            "size": "auto",
            "output_format": "png" if transparent else "jpeg",
        }
        if transparent:
            tool["background"] = "transparent"
        input_ = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ]
        return self._run(
            input_=input_,
            tool=tool,
            model=model,
            quality=quality,
            preset_id=None,
            timeout_s=_EDIT_TIMEOUT_S,
            stream=True,
            svg=False,
            prompt=prompt,
        )

    # -- internals ------------------------------------------------------

    def _run(
        self,
        *,
        input_: Any,
        tool: dict[str, Any],
        model: str,
        quality: str,
        preset_id: str | None,
        timeout_s: float,
        stream: bool,
        svg: bool,
        prompt: str,
    ) -> GeneratedImage:
        orchestrator = self._orchestrator or orchestrator_model()
        kwargs: dict[str, Any] = {
            "model": orchestrator,
            "input": input_,
            "tools": [tool],
            "tool_choice": dict(_FORCED_TOOL_CHOICE),
            "timeout": timeout_s,
        }
        if stream:
            kwargs["stream"] = True

        started = time.monotonic()
        try:
            client = self._client_factory()
            if stream:
                # httpx's timeout caps each read, not the call: the reader also stops at
                # the call's own deadline, so an endless stream cannot hold a job or a slot.
                b64, revised, usage = self._read_stream(
                    client.responses.create(**kwargs), deadline=started + timeout_s
                )
            else:
                b64, revised, usage = self._read_response(client.responses.create(**kwargs))
        except ImageGenerationError:
            raise
        except openai.APIError as exc:
            raise ImageGenerationError(
                f"Image generation request failed: {exc}",
                status_code=getattr(exc, "status_code", None),
            ) from exc
        except httpx.HTTPError as exc:
            raise ImageGenerationError(f"Image generation request failed: {exc}") from exc

        if not b64:
            raise ImageGenerationError("The model returned no image")
        try:
            raw = base64.b64decode(b64)
        except (binascii.Error, ValueError) as exc:
            raise ImageGenerationError("The model returned an undecodable image") from exc

        before = len(raw)
        has_alpha = False
        if svg:
            try:
                markup = strip_code_fences(raw.decode("utf-8"))
                check_static_svg(markup)
            except (UnicodeDecodeError, ValueError) as exc:
                raise ImageGenerationError(f"Unusable SVG from the model: {exc}") from exc
            data, mime, ext = markup.encode("utf-8"), "image/svg+xml", "svg"
        else:
            try:
                data, mime, ext = fit_to_library(raw)
                with Image.open(io.BytesIO(data)) as decoded:
                    has_alpha = _has_alpha(decoded)
            except ValueError as exc:
                raise ImageGenerationError(f"Unusable image from the model: {exc}") from exc

        latency = time.monotonic() - started
        logger.info(
            "image generation: preset=%s model=%s quality=%s latency=%.1fs bytes=%d->%d "
            "alpha=%s usage=%s prompt=%r",
            preset_id or "edit",
            model,
            quality,
            latency,
            before,
            len(data),
            has_alpha,
            usage,
            _short(prompt),
        )
        return GeneratedImage(
            data=data,
            mime=mime,
            ext=ext,
            model=model,
            preset_id=preset_id,
            revised_prompt=revised,
            latency_s=float(latency),
            usage=usage,
        )

    @staticmethod
    def _read_stream(
        events: Any,
        *,
        deadline: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> tuple[str | None, str | None, dict | None]:
        """The image, revised prompt and usage from a streamed response.

        Stops with an error once *clock* (``time.monotonic``) passes *deadline*, and closes
        the stream however it ends.
        """
        now = clock or time.monotonic
        try:
            return ImageGenerator._read_events(events, deadline, now)
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - closing is best effort
                    logger.debug("closing the image stream failed", exc_info=True)

    @staticmethod
    def _read_events(
        events: Any, deadline: float | None, now: Callable[[], float]
    ) -> tuple[str | None, str | None, dict | None]:
        b64: str | None = None
        revised: str | None = None
        usage: dict | None = None
        for event in events:
            if deadline is not None and now() > deadline:
                raise ImageGenerationError("Image generation took too long")
            kind = getattr(event, "type", None)
            if kind == "response.output_item.done":
                item = event.item
                if getattr(item, "type", None) == "image_generation_call" and item.result:
                    b64 = item.result
                    revised = getattr(item, "revised_prompt", None)
            elif kind == "response.completed":
                usage = _usage_dict(getattr(event.response, "usage", None))
            elif kind in ("response.failed", "response.incomplete"):
                err = getattr(event.response, "error", None)
                detail = getattr(err, "message", None) or kind
                raise ImageGenerationError(f"Image generation failed: {detail}")
            elif kind == "error":
                raise ImageGenerationError(
                    f"Image generation failed: {getattr(event, 'message', None) or 'stream error'}"
                )
        return b64, revised, usage

    @staticmethod
    def _read_response(response: Any) -> tuple[str | None, str | None, dict | None]:
        status = getattr(response, "status", None)
        if status in ("failed", "incomplete"):
            err = getattr(response, "error", None)
            detail = getattr(err, "message", None) or status
            raise ImageGenerationError(f"Image generation failed: {detail}")
        for item in response.output or []:
            if getattr(item, "type", None) == "image_generation_call" and item.result:
                return (
                    item.result,
                    getattr(item, "revised_prompt", None),
                    _usage_dict(getattr(response, "usage", None)),
                )
        return None, None, _usage_dict(getattr(response, "usage", None))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_generated_image(
    db: Any,
    img: GeneratedImage,
    *,
    owner: str,
    prompt: str,
    category: str,
    tags: list[str],
    description: str | None = None,
) -> Any:
    """Store a generated image in the Image Library and return the ``ImageAsset``."""
    asset = image_service.upload_image(
        db,
        img.data,
        generated_filename(prompt, img.ext),
        img.mime,
        owner,
        tags=tags,
        description=(description or prompt)[:500],
        category=category,
    )
    if img.mime == "image/svg+xml":
        stored = asset.image_data
        asset.thumbnail_base64 = (
            _SVG_DATA_URI_PREFIX + base64.b64encode(stored).decode()
            if len(stored) <= SVG_THUMBNAIL_MAX_BYTES
            else None
        )
        db.commit()
        db.refresh(asset)
    return asset
