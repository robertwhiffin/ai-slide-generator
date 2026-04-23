"""MCP (Model Context Protocol) server for tellr.

Exposes tellr's deck-generation capabilities as a set of MCP tools so
external Databricks Apps and MCP-compatible agent tools (e.g., Claude
Code) can programmatically create, edit, and retrieve slide decks.

The tools are thin wrappers over existing services (ChatService,
SessionManager, SlideDeck, permission_service) — no re-implementation
of the agent pipeline.

See docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md for
the design rationale and docs/technical/mcp-server.md (added later) for
the caller-facing integration guide.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from fastapi import Request
from mcp.server.fastmcp import Context, FastMCP

from src.api.mcp_auth import MCPAuthError, mcp_auth_scope
from src.api.services.job_queue import enqueue_job, get_job_status
from src.api.services.session_manager import get_session_manager
from src.core.database import get_db_session
from src.core.permission_context import get_permission_context
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.permission_service import get_permission_service

logger = logging.getLogger(__name__)


class _PermissionServiceFacade:
    """Module-level facade exposing a simplified permission-check API.

    The underlying ``PermissionService.can_view_deck`` requires a DB session
    and a set of identity kwargs; the MCP tool handlers only have a string
    ``session_id`` and rely on the identity ContextVars that
    ``mcp_auth_scope`` already bound. This facade bridges the two so tool
    implementations can call ``permission_service.can_view_deck(session_id)``
    without re-plumbing auth context. Unit tests replace this facade by
    patching ``src.api.mcp_server.permission_service`` with a MagicMock, so
    the facade is not exercised in test paths.
    """

    def can_view_deck(self, session_id: str) -> bool:
        """Return True if the current MCP caller has view access on the deck.

        Resolves the string ``session_id`` to the underlying ``UserSession.id``
        (integer PK), then delegates to the shared ``PermissionService``. The
        caller's identity is read from the request-scoped permission
        ContextVar populated by ``mcp_auth_scope``.
        """
        ctx = get_permission_context()
        if ctx is None:
            return False
        svc = get_permission_service()
        with get_db_session() as db:
            from src.database.models.session import UserSession

            session = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )
            if session is None:
                return False
            # Creator always has view access (mirrors PermissionService's
            # get_deck_permission creator check, done here on the string-id
            # fast path so a brand-new session the caller just created is
            # viewable even before any DeckContributor row exists).
            if session.created_by and session.created_by == ctx.user_name:
                return True
            return svc.can_view_deck(
                db,
                session.id,
                user_id=ctx.user_id,
                user_name=ctx.user_name,
                group_ids=ctx.group_ids,
            )


permission_service = _PermissionServiceFacade()

# FastMCP instance — one per process. Tools are registered via decorators
# added in subsequent tasks (create_deck, get_deck_status, edit_deck, get_deck).
mcp = FastMCP("tellr")


def _public_app_url() -> str:
    """Return the base URL for constructing deck_url / deck_view_url.

    Reads TELLR_APP_URL from the environment; this is set at deploy time
    by the Databricks App platform or by local dev config. Returns an
    empty string if unset — tool handlers should treat empty as "build
    relative URLs" rather than fail hard.
    """
    return os.getenv("TELLR_APP_URL", "").rstrip("/")


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class MCPToolError(Exception):
    """Raised when an MCP tool cannot complete its operation.

    FastMCP renders these as tool results with ``isError: true`` rather
    than as JSON-RPC protocol errors, per MCP convention for tool
    execution failures.
    """


# ---------------------------------------------------------------------------
# Async submission helper
# ---------------------------------------------------------------------------


async def enqueue_create_job(
    session_id: str,
    prompt: str,
    mode: str = "generate",
    slide_context: Optional[dict] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """Submit a generate or edit job to tellr's existing chat async queue.

    Mirrors the behaviour of ``POST /api/chat/async`` without re-using the
    FastAPI route so the MCP call path stays framework-free: the route
    depends on ``ChatRequest`` (Pydantic) and ``get_db`` (FastAPI), neither
    of which is natural to call from a FastMCP tool handler. Instead we
    invoke the underlying primitives directly:

    1. Acquire the session processing lock.
    2. Create a ``ChatRequest`` row (returns ``request_id``).
    3. Persist the user's prompt as a ``session_messages`` row so the
       chat history reflects the MCP call.
    4. Enqueue the payload on the in-memory job queue; the worker picks
       it up and runs the agent via ``ChatService.send_message_streaming``.

    Tests patch this helper at a single call site rather than patching
    the four primitives above, keeping the tool handler test focused on
    the handler's own logic. Returns the generated ``request_id``.

    Raises:
        MCPToolError: If the session is already processing another request.
    """
    session_manager = get_session_manager()

    # The caller is already authenticated and their identity is bound on
    # the request-scoped ContextVars by mcp_auth_scope (see mcp_auth.py).
    # create_chat_request's ``created_by`` kwarg is only consulted on the
    # auto-create branch of SessionManager.create_chat_request; by the
    # time we get here the session already exists (the tool handler created
    # it just before calling this helper), so passing None is correct.
    from src.core.user_context import get_current_user

    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock, session_id
    )
    if not locked:
        raise MCPToolError(
            "Session is currently processing another request"
        )

    try:
        request_id = await asyncio.to_thread(
            session_manager.create_chat_request,
            session_id,
            get_current_user(),
        )

        # Match the /api/chat/async flow: capture first-message flag BEFORE
        # persisting the user message (add_message increments message_count).
        session_data = await asyncio.to_thread(
            session_manager.get_session, session_id
        )
        is_first_message = session_data.get("message_count", 0) == 0

        # Persist the user's prompt so MCP-initiated sessions have a chat
        # transcript identical in shape to browser-initiated ones.
        await asyncio.to_thread(
            session_manager.add_message,
            session_id=session_id,
            role="user",
            content=prompt,
            message_type="user_query",
            request_id=request_id,
        )

        await enqueue_job(
            request_id,
            {
                "session_id": session_id,
                "message": prompt,
                "slide_context": slide_context,
                "is_first_message": is_first_message,
                "image_ids": None,
                # Forward-looking: mode and correlation_id flow into the
                # payload so the worker (and logs) can see them even
                # though v1 only executes generate-mode jobs.
                "mode": mode,
                "correlation_id": correlation_id,
            },
        )

        return request_id
    except Exception:
        # Ensure the session lock is released on any failure before the
        # worker gets a chance to see the job (matches /api/chat/async).
        await asyncio.to_thread(
            session_manager.release_session_lock, session_id
        )
        raise


# ---------------------------------------------------------------------------
# create_deck
# ---------------------------------------------------------------------------


def _request_from_context(ctx: Context) -> Request:
    """Extract the underlying Starlette/FastAPI Request from an MCP Context.

    When FastMCP is mounted inside FastAPI via the Streamable HTTP transport,
    the HTTP request is attached to the JSON-RPC RequestContext as
    ``request_context.request``. We access it through this helper so the
    tool handlers can stay declarative (they just ask for a Context) while
    the impl functions accept a plain ``Request`` and remain trivially
    testable without the MCP framework.

    Raises:
        MCPToolError: If no Request is attached (e.g., unexpected transport).
    """
    req = getattr(ctx.request_context, "request", None)
    if req is None:
        raise MCPToolError(
            "MCP tool requires an HTTP request context; "
            "unsupported transport"
        )
    return req


@mcp.tool(
    name="create_deck",
    description=(
        "Generate a new slide deck from a natural-language prompt. Returns a "
        "session_id and a request_id; the caller polls get_deck_status for "
        "completion. The resulting deck is attributed to the calling user and "
        "appears in their tellr UI. v1 runs prompt-only: the agent does not "
        "invoke Genie, Vector Search, or other tools. Callers that want data-"
        "backed decks should gather the data themselves and include it in the "
        "prompt."
    ),
)
async def create_deck(
    ctx: Context,
    prompt: str,
    num_slides: Optional[int] = None,
    slide_style_id: Optional[int] = None,
    deck_prompt_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    return await _create_deck_impl(
        request=_request_from_context(ctx),
        prompt=prompt,
        num_slides=num_slides,
        slide_style_id=slide_style_id,
        deck_prompt_id=deck_prompt_id,
        correlation_id=correlation_id,
    )


async def _create_deck_impl(
    request: Request,
    prompt: str,
    num_slides: Optional[int] = None,
    slide_style_id: Optional[int] = None,
    deck_prompt_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    """Implementation, separated from the decorated tool for testability."""
    if not prompt or not prompt.strip():
        raise MCPToolError("prompt must be a non-empty string")
    if num_slides is not None and not (1 <= num_slides <= 50):
        raise MCPToolError("num_slides must be between 1 and 50")

    try:
        with mcp_auth_scope(request) as identity:
            agent_config: dict[str, Any] = {"tools": []}
            if slide_style_id is not None:
                agent_config["slide_style_id"] = slide_style_id
            if deck_prompt_id is not None:
                agent_config["deck_prompt_id"] = deck_prompt_id
            if num_slides is not None:
                agent_config["num_slides"] = num_slides

            session_manager = get_session_manager()
            session = session_manager.create_session(
                created_by=identity.user_name,
                agent_config=agent_config,
            )
            # create_session returns a dict (see SessionManager.create_session);
            # guard against a model-object return defensively so this stays
            # robust if the service ever switches to returning a Pydantic model.
            session_id = (
                session["session_id"]
                if isinstance(session, dict)
                else session.session_id
            )

            request_id = await enqueue_create_job(
                session_id=session_id,
                prompt=prompt,
                mode="generate",
                slide_context=None,
                correlation_id=correlation_id,
            )

            logger.info(
                "MCP create_deck submitted",
                extra={
                    "event": "mcp_tool_invoked",
                    "tool_name": "create_deck",
                    "session_id": session_id,
                    "request_id": request_id,
                    "user_name": identity.user_name,
                    "token_source": identity.source,
                    "correlation_id": correlation_id,
                },
            )

            return {
                "session_id": session_id,
                "request_id": request_id,
                "status": "pending",
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP create_deck failed")
        raise MCPToolError(
            f"Internal error (correlation_id={correlation_id}): {e}"
        ) from e


# ---------------------------------------------------------------------------
# Deck response serializer (shared by get_deck_status and get_deck)
# ---------------------------------------------------------------------------


def _render_deck_response(session: dict, base_url: str) -> dict:
    """Serialize a session's deck into the MCP response fields.

    Returns a dict carrying ``slide_count``, ``title``, ``deck``,
    ``html_document``, ``deck_url``, and ``deck_view_url``. The input
    ``session`` is expected to carry a ``deck_json`` payload (the
    structured deck dict persisted by the worker) plus a ``title`` and
    ``session_id``. This helper is extracted so ``get_deck`` (Task 9)
    can reuse the exact same shape without drift between the two tools.

    ``SlideDeck`` has no ``from_dict`` constructor, so the deck is
    rebuilt by constructing ``Slide`` instances for each entry in
    ``deck_json["slides"]`` and handing them to ``SlideDeck.__init__``
    together with the stored title, CSS, external scripts, and head
    metadata.
    """
    deck_json = session.get("deck_json") or {}
    if deck_json:
        slides = [
            Slide(
                html=s.get("html", ""),
                scripts=s.get("scripts", ""),
                slide_id=s.get("slide_id"),
                created_by=s.get("created_by"),
                created_at=s.get("created_at"),
                modified_by=s.get("modified_by"),
                modified_at=s.get("modified_at"),
            )
            for s in deck_json.get("slides", [])
        ]
        deck = SlideDeck(
            title=deck_json.get("title") or session.get("title"),
            css=deck_json.get("css", ""),
            external_scripts=list(deck_json.get("external_scripts") or []),
            slides=slides,
            head_meta=dict(deck_json.get("head_meta") or {}),
        )
    else:
        deck = SlideDeck(title=session.get("title"))

    session_id = session["session_id"]
    deck_url = (
        f"{base_url}/sessions/{session_id}/edit"
        if base_url
        else f"/sessions/{session_id}/edit"
    )
    deck_view_url = (
        f"{base_url}/sessions/{session_id}/view"
        if base_url
        else f"/sessions/{session_id}/view"
    )
    return {
        "slide_count": len(deck.slides),
        "title": session.get("title") or deck.title,
        "deck": deck.to_dict(),
        "html_document": deck.to_html_document(),
        "deck_url": deck_url,
        "deck_view_url": deck_view_url,
    }


# ---------------------------------------------------------------------------
# get_deck_status
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_deck_status",
    description=(
        "Poll the status of a deck generation or edit job. Returns "
        "lightweight status while pending/running; when ready, returns the "
        "complete deck as structured slide data, a standalone HTML "
        "document, and URLs into tellr's full editor and view-only surfaces."
    ),
)
async def get_deck_status(
    ctx: Context,
    session_id: str,
    request_id: str,
) -> dict:
    return await _get_deck_status_impl(
        request=_request_from_context(ctx),
        session_id=session_id,
        request_id=request_id,
    )


async def _get_deck_status_impl(
    request: Request, session_id: str, request_id: str
) -> dict:
    """Implementation, separated from the decorated tool for testability."""
    try:
        with mcp_auth_scope(request):
            if not permission_service.can_view_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to view it"
                )

            status = get_job_status(request_id)
            if status is None:
                raise MCPToolError(f"Unknown request_id: {request_id}")

            job_status = status.get("status", "pending")

            if job_status in ("pending", "running"):
                return {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": job_status,
                    "progress": status.get("progress"),
                }

            if job_status in ("failed", "error"):
                return {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "failed",
                    "error": status.get("error", "Generation failed"),
                }

            # status == "ready" (MCP-layer contract; mapped from the worker's
            # completion signal by the caller of get_job_status).
            session_manager = get_session_manager()
            session = session_manager.get_session(session_id)
            base = _public_app_url()
            deck_fields = _render_deck_response(session, base)

            return {
                "session_id": session_id,
                "request_id": request_id,
                "status": "ready",
                **deck_fields,
                "replacement_info": status.get("replacement_info"),
                "messages": status.get("messages") or [],
                "metadata": {
                    "mode": status.get("mode"),
                    "tool_calls": status.get("tool_calls"),
                    "latency_ms": status.get("latency_ms"),
                    "correlation_id": status.get("correlation_id"),
                },
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP get_deck_status failed")
        raise MCPToolError(f"Internal error: {e}") from e
