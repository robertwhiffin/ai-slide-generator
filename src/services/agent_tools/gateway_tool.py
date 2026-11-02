"""The generic Gateway MCP agent tool: one tool of a connected Gateway service.

A :class:`GatewayMcpAgentTool` wraps one :class:`GatewayToolSpec` listed by a
Gateway MCP service.  The model is bound to the service's own JSON schema
(``parameters_json_schema``), the arguments are passed through untouched, and
the result is shaped before the model sees it: images are saved as content
images and replaced by a ``{{image:TOKEN}}`` note, ``*base64`` / ``*b64`` fields
are removed, inline image data URIs are replaced by their reference, and the text
is capped (never the image notes) and spotlighted.

This module must not import ``src.core.skills`` (no prompt text lives here).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from src.core.database import get_db_session
from src.services import image_service
from src.services.agent_tools.gateway_mcp import (
    CALL_TIMEOUT_SECONDS,
    GatewayMcpClient,
    GatewayMcpError,
    GatewayToolSpec,
)
from src.services.agent_tools.toolset import ToolAccessError
from src.utils.spotlight import spotlight

logger = logging.getLogger(__name__)

GATEWAY_OUTPUT_CAP_CHARS: Final = 32000

ImageSaver = Callable[[bytes, str], str]

_IMAGE_MIMES: Final = frozenset({"image/png", "image/jpeg", "image/gif", "image/svg+xml"})
_EXTENSIONS: Final = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
}
_IMAGE_NOTE_TAIL: Final = (
    ". To show it on a slide, put this exact reference in that slide's content_brief."
)
#: JSON keys whose value is removed (and saved, if it is an image): any key ending
#: in one of these, case-insensitively.
_BASE64_KEY_SUFFIXES: Final = ("base64", "b64")
#: An inline image data URI, anywhere in a text or a JSON string value.
_DATA_URI_RE: Final = re.compile(
    r"data:(?P<mime>image/(?:png|jpeg|gif|svg\+xml));base64,(?P<data>[A-Za-z0-9+/]+={0,2})",
    re.IGNORECASE,
)


class GatewayArgs(BaseModel):
    """Any object: the Gateway service validates the arguments, not Tellr."""

    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True)
class GatewayToolContext:
    display_name: str
    service_name: str
    client: GatewayMcpClient = field(repr=False)
    save_image: ImageSaver
    on_call: Callable[[str], None]
    session_id: str | None
    deadline_at: float | None = None  # epoch seconds; no call starts after it


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------


def _sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if b"<svg" in data[:4096].lower():
        return "image/svg+xml"
    return None


def _image_size(data: bytes, mime: str) -> tuple[int, int] | None:
    """A raster image's ``(width, height)``; ``None`` for SVG or bytes Pillow cannot read."""
    if mime == "image/svg+xml":
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return img.size
    except Exception:  # noqa: BLE001 - unreadable bytes (or a decompression bomb)
        return None


def _decode_base64(value: str) -> bytes | None:
    if value.startswith("data:") and "," in value[:200]:
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


class _Shaper:
    """Builds the model text for one result and saves its images once each.

    ``notes`` collects one line per image (the "Image saved" note or an
    ``[image not saved: …]`` line); they are appended after the capped text.
    """

    def __init__(self, save_image: ImageSaver) -> None:
        self._save = save_image
        #: SHA-256 -> what stands in for that image (its reference, or why not saved).
        self._seen: dict[str, str] = {}
        self.tokens: list[str] = []
        self.notes: list[str] = []

    def _store(self, data: bytes, mime: str, *, in_place: bool = False) -> str:
        """Save one image, once per result; what stands in for it in place.

        The stand-in is the ``{{image:TOKEN}}`` reference, or the
        ``[image not saved: …]`` line.  A new image adds its note: the "Image
        saved" note, or the failure line unless it already stands *in_place*.
        """
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self._seen:
            stand_in, note = self._save_new(data, mime)
            self._seen[digest] = stand_in
            if note is not None or not in_place:
                self.notes.append(note or stand_in)
        return self._seen[digest]

    def _save_new(self, data: bytes, mime: str) -> tuple[str, str | None]:
        """``(stand-in, note)`` for an image not seen before in this result; the note
        is ``None`` when it was not saved (the stand-in then says why)."""
        if len(data) > image_service.MAX_FILE_SIZE:
            limit_mb = image_service.MAX_FILE_SIZE // (1024 * 1024)
            return f"[image not saved: larger than {limit_mb} MB]", None
        size = _image_size(data, mime)
        if size is None and mime != "image/svg+xml":
            return "[image not saved: could not decode the image data]", None
        try:
            token = self._save(data, mime)
        except ValueError as exc:
            return f"[image not saved: {exc}]", None
        except Exception:  # noqa: BLE001 - one bad image must not cost the rest of the result
            # e.g. Pillow failing on a truncated image, or the database; the
            # service call already ran, so the model still gets its text.
            logger.warning("Gateway MCP image save failed", exc_info=True)
            return "[image not saved: it could not be stored]", None
        self.tokens.append(token)
        ref = f"{{{{image:{token}}}}}"
        dims = "" if size is None else f", {size[0]}×{size[1]}"
        return ref, f"Image saved: {ref} ({mime}{dims}){_IMAGE_NOTE_TAIL}"

    def image_block(self, block: Any) -> None:
        mime = str(getattr(block, "mimeType", "") or "").lower()
        if mime not in _IMAGE_MIMES:
            self.notes.append(f"[image not saved: unsupported type {mime or 'unknown'}]")
            return
        data = _decode_base64(str(getattr(block, "data", "") or ""))
        if not data:
            self.notes.append("[image not saved: could not decode the image data]")
            return
        self._store(data, mime)

    def inline(self, text: str) -> str:
        """*text* with every image data URI replaced in place by what stands in for it."""

        def replace(match: re.Match[str]) -> str:
            data = _decode_base64(match["data"])
            if not data:
                return "[image not saved: could not decode the image data]"
            return self._store(data, match["mime"].lower(), in_place=True)

        return _DATA_URI_RE.sub(replace, text) if "data:" in text else text

    def strip(self, node: Any) -> tuple[Any, bool]:
        """*node* without any ``*base64`` / ``*b64`` key and with its data URIs replaced;
        the images found are saved."""
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            changed = False
            for key, value in node.items():
                if isinstance(key, str) and key.lower().endswith(_BASE64_KEY_SUFFIXES):
                    changed = True
                    if isinstance(value, str):
                        data = _decode_base64(value)
                        mime = _sniff_mime(data) if data else None
                        if data and mime:
                            self._store(data, mime)
                    continue
                new, sub = self.strip(value)
                out[key] = new
                changed = changed or sub
            return out, changed
        if isinstance(node, list):
            items = []
            changed = False
            for value in node:
                new, sub = self.strip(value)
                items.append(new)
                changed = changed or sub
            return items, changed
        if isinstance(node, str):
            new_text = self.inline(node)
            return new_text, new_text != node
        return node, False

    def text(self, raw: str) -> str:
        """One text block: JSON has its base64 fields stripped; data URIs are replaced
        in any text; anything else is kept verbatim."""
        stripped = raw.strip()
        if stripped[:1] in ("{", "["):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                return self.inline(raw)
            clean, changed = self.strip(parsed)
            return json.dumps(clean, ensure_ascii=False) if changed else raw
        return self.inline(raw)


def shape_result(result: Any, *, save_image: ImageSaver) -> tuple[str, list[str]]:
    """The model text (not spotlighted) for a ``CallToolResult`` and the tokens of
    the images it saved.

    The text is the result's content, capped (see :func:`_cap`), followed by one
    line per image, which the cap never cuts.
    """
    shaper = _Shaper(save_image)
    lines: list[str] = []
    has_text = False
    for block in result.content or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            has_text = True
            lines.append(shaper.text(block.text))
        elif kind == "image":
            shaper.image_block(block)
        else:
            lines.append(f"[{kind} content omitted]")
    structured = getattr(result, "structuredContent", None)
    if not has_text and structured is not None:
        clean = structured
        if isinstance(structured, (dict, list)):
            clean, _ = shaper.strip(structured)
        lines.insert(0, json.dumps(clean, ensure_ascii=False))
    notes = "\n".join(shaper.notes)
    # The notes are kept whole: the content gets what is left of the cap.
    room = GATEWAY_OUTPUT_CAP_CHARS - (len(notes) + 1 if notes else 0)
    body = _cap("\n".join(lines), room) if lines else ""
    text = "\n".join(part for part in (body, notes) if part)
    if getattr(result, "isError", False):
        text = "Tool error: " + text
    return text, shaper.tokens


def _cap(text: str, limit: int = GATEWAY_OUTPUT_CAP_CHARS) -> str:
    """*text* cut to *limit* characters, with a trailer saying how much was cut."""
    if len(text) <= limit:
        return text
    limit = max(limit, 0)
    return text[:limit] + f"\n[truncated: {len(text) - limit} more characters]"


# ---------------------------------------------------------------------------
# Saving images
# ---------------------------------------------------------------------------


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "image"


def make_image_saver(*, user: str, service_name: str, display_name: str) -> ImageSaver:
    """An :data:`ImageSaver` that stores a content image owned by *user*."""
    slug = _slug(display_name)

    def save(data: bytes, mime: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{slug}-{stamp}-{uuid.uuid4().hex[:8]}.{_EXTENSIONS.get(mime, 'bin')}"
        with get_db_session() as db:
            asset = image_service.upload_image(
                db,
                data,
                filename,
                mime,
                user,
                tags=["gateway_mcp", service_name],
                category="content",
            )
            return asset.token

    return save


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


class GatewayMcpAgentTool:
    """One tool of a connected Gateway MCP service, as an ``AgentTool``."""

    args_schema = GatewayArgs

    def __init__(
        self,
        spec: GatewayToolSpec,
        ctx: GatewayToolContext,
        *,
        model_name: str,
        description_prefix: str | None,
    ) -> None:
        self._spec = spec
        self._ctx = ctx
        self.name = model_name
        description = spec.description or ""
        head = f"{ctx.display_name}: "
        if description_prefix:
            self.description = f"{head}{description_prefix}\n\n{description}"
        else:
            self.description = f"{head}{description}"
        schema = {k: v for k, v in spec.input_schema.items() if k != "$schema"}
        schema.setdefault("type", "object")
        self.parameters_json_schema: dict[str, Any] = schema
        self.saved_tokens: list[str] = []

    def _refusal(self, err: GatewayMcpError) -> ToolAccessError:
        name = self._ctx.display_name
        if err.kind == "sign_in_required":
            text = f"{name} needs you to sign in; the user has been told how. Continue without it."
            return ToolAccessError("sign_in_required", self.name, text, sign_in_url=err.sign_in_url)
        if err.kind == "missing_scope":
            text = (
                f"{name} needs a permission the user's sign-in to this app does not have; "
                "the user has been told how to fix it. Continue without it."
            )
            return ToolAccessError("missing_scope", self.name, text)
        text = (
            f"The user does not have access to {name}; the user has been told. Continue without it."
        )
        return ToolAccessError("access_denied", self.name, text)

    def run(self, args: BaseModel, *, remaining_seconds: float) -> str:
        ctx = self._ctx
        if remaining_seconds <= 0 or (
            ctx.deadline_at is not None and time.time() >= ctx.deadline_at
        ):
            return f"Not run: the time budget for {ctx.display_name} is spent. Continue without it."
        try:
            ctx.on_call(f"{ctx.display_name} · {self._spec.name}")
        except Exception:  # noqa: BLE001 - a progress line must never stop the call
            logger.warning("Gateway progress line failed", exc_info=True)
        try:
            result = ctx.client.call_tool(
                self._spec.name,
                args.model_dump(),
                timeout_seconds=min(CALL_TIMEOUT_SECONDS, remaining_seconds),
            )
        except GatewayMcpError as err:
            if err.kind in ("sign_in_required", "missing_scope", "access_denied"):
                raise self._refusal(err) from err
            return spotlight(
                ctx.display_name,
                f"{ctx.display_name} could not run {self._spec.name}: {err.message}",
                session_id=ctx.session_id,
            )
        text, tokens = shape_result(result, save_image=ctx.save_image)
        self.saved_tokens.extend(tokens)
        # ``shape_result`` has already capped the text (its image notes kept whole).
        return spotlight(ctx.display_name, text, session_id=ctx.session_id)
