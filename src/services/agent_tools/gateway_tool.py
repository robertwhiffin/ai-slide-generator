"""The generic Gateway MCP agent tool: one tool of a connected Gateway service.

A :class:`GatewayMcpAgentTool` wraps one :class:`GatewayToolSpec` listed by a
Gateway MCP service.  The model is bound to the service's own JSON schema
(``parameters_json_schema``), the arguments are passed through untouched, and
the result is shaped before the model sees it: images are saved as content
images and replaced by a ``{{image:TOKEN}}`` note, ``*base64`` fields are
removed, and the text is capped and spotlighted.

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
    """Builds the model text for one result and saves its images once each."""

    def __init__(self, save_image: ImageSaver) -> None:
        self._save = save_image
        self._seen: set[str] = set()
        self.tokens: list[str] = []

    def image(self, data: bytes, mime: str) -> list[str]:
        """Save one image; the lines to show the model (none for a duplicate)."""
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._seen:
            return []
        self._seen.add(digest)
        if len(data) > image_service.MAX_FILE_SIZE:
            return [
                f"[image not saved: larger than {image_service.MAX_FILE_SIZE // (1024 * 1024)} MB]"
            ]
        size = _image_size(data, mime)
        if size is None and mime != "image/svg+xml":
            return ["[image not saved: could not decode the image data]"]
        try:
            token = self._save(data, mime)
        except ValueError as exc:
            return [f"[image not saved: {exc}]"]
        except Exception:  # noqa: BLE001 - one bad image must not cost the rest of the result
            # e.g. Pillow failing on a truncated image, or the database; the
            # service call already ran, so the model still gets its text.
            logger.warning("Gateway MCP image save failed", exc_info=True)
            return ["[image not saved: it could not be stored]"]
        self.tokens.append(token)
        dims = "" if size is None else f", {size[0]}×{size[1]}"
        return [f"Image saved: {{{{image:{token}}}}} ({mime}{dims}){_IMAGE_NOTE_TAIL}"]

    def image_block(self, block: Any) -> list[str]:
        mime = str(getattr(block, "mimeType", "") or "").lower()
        if mime not in _IMAGE_MIMES:
            return [f"[image not saved: unsupported type {mime or 'unknown'}]"]
        data = _decode_base64(str(getattr(block, "data", "") or ""))
        if not data:
            return ["[image not saved: could not decode the image data]"]
        return self.image(data, mime)

    def strip(self, node: Any, notes: list[str]) -> tuple[Any, bool]:
        """*node* without any ``*base64`` key; images found there are saved."""
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            changed = False
            for key, value in node.items():
                if isinstance(key, str) and key.lower().endswith("base64"):
                    changed = True
                    if isinstance(value, str):
                        data = _decode_base64(value)
                        mime = _sniff_mime(data) if data else None
                        if data and mime:
                            notes.extend(self.image(data, mime))
                    continue
                new, sub = self.strip(value, notes)
                out[key] = new
                changed = changed or sub
            return out, changed
        if isinstance(node, list):
            items = []
            changed = False
            for value in node:
                new, sub = self.strip(value, notes)
                items.append(new)
                changed = changed or sub
            return items, changed
        return node, False

    def text(self, raw: str) -> list[str]:
        """One text block: JSON has its base64 fields stripped, anything else is kept."""
        stripped = raw.strip()
        if stripped[:1] in ("{", "["):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                return [raw]
            notes: list[str] = []
            clean, changed = self.strip(parsed, notes)
            return [json.dumps(clean) if changed else raw, *notes]
        return [raw]


def shape_result(result: Any, *, save_image: ImageSaver) -> tuple[str, list[str]]:
    """The model text (not spotlighted) for a ``CallToolResult`` and the tokens of
    the images it saved."""
    shaper = _Shaper(save_image)
    lines: list[str] = []
    has_text = False
    for block in result.content or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            has_text = True
            lines.extend(shaper.text(block.text))
        elif kind == "image":
            lines.extend(shaper.image_block(block))
        else:
            lines.append(f"[{kind} content omitted]")
    structured = getattr(result, "structuredContent", None)
    if not has_text and structured is not None:
        clean, notes = structured, []
        if isinstance(structured, (dict, list)):
            clean, _ = shaper.strip(structured, notes)
        lines.insert(0, json.dumps(clean))
        lines.extend(notes)
    text = "\n".join(lines)
    if getattr(result, "isError", False):
        text = "Tool error: " + text
    return text, shaper.tokens


def _cap(text: str) -> str:
    if len(text) <= GATEWAY_OUTPUT_CAP_CHARS:
        return text
    more = len(text) - GATEWAY_OUTPUT_CAP_CHARS
    return text[:GATEWAY_OUTPUT_CAP_CHARS] + f"\n[truncated: {more} more characters]"


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
        return spotlight(ctx.display_name, _cap(text), session_id=ctx.session_id)
