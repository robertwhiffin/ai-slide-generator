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
from src.api.services.job_queue import enqueue_job
from src.api.services.session_manager import get_session_manager

logger = logging.getLogger(__name__)

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
