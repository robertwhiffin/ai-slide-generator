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
from src.core.settings_db import get_default_slide_style_id
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

    def can_edit_deck(self, session_id: str) -> bool:
        """Return True if the current MCP caller has edit access on the deck.

        Mirrors ``can_view_deck`` but gates on CAN_EDIT (or higher) rather
        than any access. Resolves the string ``session_id`` to the
        underlying ``UserSession.id`` (integer PK) and delegates to the
        shared ``PermissionService``. The session creator is short-
        circuited to True — creators implicitly hold CAN_MANAGE, which
        includes edit — on the string-id fast path so a session the
        caller just created is editable before any DeckContributor row
        exists.
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
            if session.created_by and session.created_by == ctx.user_name:
                return True
            return svc.can_edit_deck(
                db,
                session.id,
                user_id=ctx.user_id,
                user_name=ctx.user_name,
                group_ids=ctx.group_ids,
            )


permission_service = _PermissionServiceFacade()

# FastMCP instance — one per process. Tools are registered via decorators
# added in subsequent tasks (create_deck, get_deck_status, edit_deck, get_deck).
#
# stateless_http=True: tellr runs multiple uvicorn workers
# (UVICORN_WORKERS=4 on Databricks Apps), and FastMCP's default stateful
# session store is an in-memory dict on each worker process. Without
# session affinity at the proxy layer, the three requests of a normal
# handshake (initialize → notifications/initialized → tools/call) can
# land on different workers, producing HTTP 404 "Session not found"
# intermittently — especially on longer generate+poll loops where many
# handshakes happen. Stateless mode sidesteps this entirely: each HTTP
# request is self-contained, no server-side session lookup, no
# possibility of session-not-found. This is the mode the MCP spec
# (2025-03-26) prescribes for multi-node deployments.
mcp = FastMCP("tellr", stateless_http=True)


def _public_app_url() -> str:
    """Return the base URL for constructing deck_url / deck_view_url.

    Reads DATABRICKS_APP_URL from the environment. The Databricks Apps
    platform injects this automatically on production deployments, so no
    manual configuration is required. Returns an empty string if unset
    (e.g., local dev) — tool handlers treat empty as "build relative URLs"
    rather than fail hard, and the browser resolves the resulting paths
    against whatever host is serving the page.
    """
    return os.getenv("DATABRICKS_APP_URL", "").rstrip("/")


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
            # Mirror the browser chat flow: if the caller didn't specify a
            # style, fall back to the tellr-configured default
            # (slide_style_library.is_default=True) rather than the
            # hardcoded DEFAULT_SLIDE_STYLE constant that agent_factory
            # uses when agent_config.slide_style_id is absent.
            effective_style_id = slide_style_id
            if effective_style_id is None:
                effective_style_id = get_default_slide_style_id()
            if effective_style_id is not None:
                agent_config["slide_style_id"] = effective_style_id
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


def _render_deck_response(
    deck_dict: Optional[dict], session: dict, base_url: str
) -> dict:
    """Serialize a session's deck into the MCP response fields.

    Returns a dict carrying ``slide_count``, ``title``, ``deck``,
    ``html_document``, ``deck_url``, and ``deck_view_url``. This helper
    is extracted so ``get_deck_status`` and ``get_deck`` (Task 9) produce
    identical response shapes without drift between the two tools.

    Args:
        deck_dict: Structured deck payload as returned by
            ``SessionManager.get_slide_deck(session_id)``. Typically has
            ``title``, ``slides``, ``css``, ``external_scripts``, and
            ``head_meta`` keys. May be ``None`` when the session has no
            deck yet (empty deck is rendered in that case).
        session: Session info from ``SessionManager.get_session(session_id)``.
            Used for ``session_id`` (required for URL construction) and
            ``title`` fallback when the deck has no title.
        base_url: Public app URL prefix for building deck URLs. Empty
            string yields relative URLs.

    ``SlideDeck`` has no ``from_dict`` constructor, so the deck is
    rebuilt by constructing ``Slide`` instances for each entry in
    ``deck_dict["slides"]`` and handing them to ``SlideDeck.__init__``
    together with the stored title, CSS, external scripts, and head
    metadata.
    """
    deck_dict = deck_dict or {}
    if deck_dict:
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
            for s in deck_dict.get("slides", [])
        ]
        deck = SlideDeck(
            title=deck_dict.get("title") or session.get("title"),
            css=deck_dict.get("css", ""),
            external_scripts=list(deck_dict.get("external_scripts") or []),
            slides=slides,
            head_meta=dict(deck_dict.get("head_meta") or {}),
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
    """Implementation, separated from the decorated tool for testability.

    Mirrors the data-access pattern of ``GET /api/chat/poll/{request_id}``:
    the in-memory ``jobs`` dict is authoritative for pending/running/failed
    state, but worker completion pops the in-memory entry (see
    ``job_queue.process_chat_request``'s ``finally`` clause). To see the
    ready/error terminal state we have to fall back to the persisted
    ``chat_request`` DB row, then re-fetch the deck via
    ``SessionManager.get_slide_deck`` since neither ``get_job_status``
    nor ``get_session`` carry the structured deck payload.
    """
    try:
        with mcp_auth_scope(request):
            if not permission_service.can_view_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to view it"
                )

            session_manager = get_session_manager()

            # Phase 1: in-memory fast path. The worker updates this dict as
            # it transitions pending -> running, and the timeout sweeper
            # flips stuck jobs to "failed". On successful completion the
            # worker pops the entry, so "completed"/"success" are not
            # normally observed here — but we still treat them as a
            # fall-through signal in case a caller observes a race.
            entry = get_job_status(request_id)
            if entry is not None:
                job_status = entry.get("status", "pending")

                if job_status in ("pending", "running"):
                    return {
                        "session_id": session_id,
                        "request_id": request_id,
                        "status": job_status,
                        "progress": entry.get("progress"),
                    }

                if job_status == "failed":
                    return {
                        "session_id": session_id,
                        "request_id": request_id,
                        "status": "failed",
                        "error": entry.get("error", "Generation failed"),
                    }
                # Any other status ("error", "completed", "success",
                # unexpected values): fall through to DB for authoritative
                # state. Worker-raised errors also land in the DB via
                # update_chat_request_status(request_id, "error", ...).

            # Phase 2: DB fallback. ``get_chat_request`` returns a dict with
            # ``status``, ``error_message``, ``result`` (the JSON blob the
            # worker stored via ``set_chat_request_result`` — slides,
            # raw_html, replacement_info, experiment_url, metadata,
            # session_title), plus timestamps and the INTEGER session_id.
            chat_request = session_manager.get_chat_request(request_id)
            if chat_request is None:
                raise MCPToolError(f"Unknown request_id: {request_id}")

            # Cross-check: the request must belong to the session the caller
            # supplied. ``chat_request["session_id"]`` is the integer PK, so
            # resolve it to the string form for comparison. Without this,
            # a caller with view access on any deck could probe for
            # messages/metadata of arbitrary other requests.
            owning_session_id = session_manager.get_session_id_for_request(
                request_id
            )
            if owning_session_id != session_id:
                raise MCPToolError(f"Unknown request_id: {request_id}")

            db_status = chat_request.get("status")

            if db_status in ("pending", "running"):
                return {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": db_status,
                    "progress": None,
                }

            if db_status == "error":
                return {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "failed",
                    "error": chat_request.get("error_message")
                    or "Generation failed",
                }

            if db_status != "completed":
                # Unknown terminal state — surface as failure so callers
                # aren't left polling forever.
                return {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "failed",
                    "error": f"Unknown job status: {db_status!r}",
                }

            # Ready path. The worker stored the deck via
            # SessionManager.save_slide_deck (from inside send_message_streaming)
            # before calling set_chat_request_result, so get_slide_deck is
            # authoritative.
            session = session_manager.get_session(session_id)
            deck_dict = session_manager.get_slide_deck(session_id)
            base = _public_app_url()
            deck_fields = _render_deck_response(deck_dict, session, base)

            # ``result`` is a JSON blob the worker wrote. Per
            # job_queue.process_chat_request, keys are: slides, raw_html,
            # replacement_info, experiment_url, metadata, session_title.
            result = chat_request.get("result") or {}
            result_metadata = result.get("metadata") or {}

            # Messages for this turn: the worker persists each streamed
            # event as a SessionMessage tagged with the request_id, so
            # get_messages_for_request gives us the turn's transcript.
            db_messages = session_manager.get_messages_for_request(request_id)
            messages = [
                {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "message_type": m.get("message_type"),
                    "created_at": m.get("created_at"),
                }
                for m in db_messages
            ]

            return {
                "session_id": session_id,
                "request_id": request_id,
                "status": "ready",
                **deck_fields,
                "replacement_info": result.get("replacement_info"),
                "messages": messages,
                "metadata": {
                    "tool_calls": result_metadata.get("tool_calls"),
                    "latency_ms": result_metadata.get("latency_ms")
                    or result_metadata.get("latency_seconds"),
                    "experiment_url": result.get("experiment_url"),
                    "session_title": result.get("session_title"),
                },
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP get_deck_status failed")
        raise MCPToolError(f"Internal error: {e}") from e


# ---------------------------------------------------------------------------
# edit_deck
# ---------------------------------------------------------------------------


def _check_contiguous(indices: list[int]) -> None:
    """Raise MCPToolError unless indices form a contiguous run.

    The edit pipeline's ``_parse_slide_replacements`` / ``_apply_slide_
    replacements`` helpers assume the caller-supplied slide range is a
    single contiguous slice so replacement output can be spliced back in
    at a single index. Callers that want to edit disjoint slides should
    issue one ``edit_deck`` call per slice.
    """
    if not indices:
        return
    sorted_idx = sorted(indices)
    for a, b in zip(sorted_idx, sorted_idx[1:]):
        if b - a != 1:
            raise MCPToolError(
                "slide_indices must be contiguous (e.g. [2, 3, 4], not [2, 4])"
            )


@mcp.tool(
    name="edit_deck",
    description=(
        "Refine an existing deck through a natural-language instruction. "
        "Optionally target specific contiguous slides via slide_indices. "
        "The edit is applied in-place; the session_id and deck_url stay "
        "stable across edits. Returns a request_id; the caller polls "
        "get_deck_status for completion and receives the updated deck "
        "plus replacement_info summarizing what changed."
    ),
)
async def edit_deck(
    ctx: Context,
    session_id: str,
    instruction: str,
    slide_indices: Optional[list[int]] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    return await _edit_deck_impl(
        request=_request_from_context(ctx),
        session_id=session_id,
        instruction=instruction,
        slide_indices=slide_indices,
        correlation_id=correlation_id,
    )


async def _edit_deck_impl(
    request: Request,
    session_id: str,
    instruction: str,
    slide_indices: Optional[list[int]] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    """Implementation, separated from the decorated tool for testability.

    Reuses ``enqueue_create_job`` with ``mode="edit"`` so the worker
    dispatches to the existing ChatService edit path (slide_context
    present => editing_mode in ``agent.chat_async_streaming``). When
    ``slide_indices`` is provided we pull the current slide HTMLs via
    ``SessionManager.get_slide_deck`` and bundle them into the
    ``slide_context`` dict the agent's ``_format_slide_context`` helper
    expects (``{"indices": [...], "slide_htmls": [...]}``). Without
    ``slide_indices`` the job is submitted with ``slide_context=None``
    — still edit-mode, but the agent will operate against the full deck.
    """
    if not instruction or not instruction.strip():
        raise MCPToolError("instruction must be a non-empty string")
    if slide_indices is not None:
        _check_contiguous(slide_indices)

    try:
        with mcp_auth_scope(request) as identity:
            if not permission_service.can_edit_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to edit it"
                )

            slide_context: Optional[dict] = None
            if slide_indices:
                sm = get_session_manager()
                deck = sm.get_slide_deck(session_id)
                if deck is None:
                    raise MCPToolError(
                        f"Deck not found for session_id: {session_id}"
                    )
                all_slides = deck.get("slides") or []
                try:
                    slide_htmls = [
                        all_slides[i]["html"] for i in slide_indices
                    ]
                except IndexError as e:
                    raise MCPToolError(
                        f"slide_indices contains out-of-range index: {e}"
                    ) from e
                except (TypeError, KeyError) as e:
                    raise MCPToolError(
                        f"Failed to read slide html at index: {e}"
                    ) from e
                slide_context = {
                    "indices": slide_indices,
                    "slide_htmls": slide_htmls,
                }

            request_id = await enqueue_create_job(
                session_id=session_id,
                prompt=instruction,
                mode="edit",
                slide_context=slide_context,
                correlation_id=correlation_id,
            )

            logger.info(
                "MCP edit_deck submitted",
                extra={
                    "event": "mcp_tool_invoked",
                    "tool_name": "edit_deck",
                    "session_id": session_id,
                    "request_id": request_id,
                    "user_name": identity.user_name,
                    "slide_indices": slide_indices,
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
        logger.exception("MCP edit_deck failed")
        raise MCPToolError(f"Internal error: {e}") from e


# ---------------------------------------------------------------------------
# get_deck
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_deck",
    description=(
        "Retrieve the current state of a deck without submitting new work. "
        "Returns structured slide data, a standalone HTML document, and "
        "URLs into tellr's editor — same payload as a ready get_deck_status "
        "response, without status/request_id/messages. Idempotent; no job "
        "queue interaction. Use when you have a session_id from earlier and "
        "want to re-render without polling."
    ),
)
async def get_deck(ctx: Context, session_id: str) -> dict:
    return await _get_deck_impl(
        request=_request_from_context(ctx),
        session_id=session_id,
    )


async def _get_deck_impl(request: Request, session_id: str) -> dict:
    """Implementation, separated from the decorated tool for testability.

    Idempotent read-only counterpart to ``get_deck_status``'s ready branch:
    no job-queue interaction, no ``request_id``/``status``/``messages`` in
    the response. Reuses ``_render_deck_response`` so the deck-shaped
    fields stay identical to those in a ready ``get_deck_status`` reply.
    """
    try:
        with mcp_auth_scope(request):
            if not permission_service.can_view_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to view it"
                )

            sm = get_session_manager()
            session = sm.get_session(session_id)
            if session is None:
                raise MCPToolError(
                    f"Deck not found: session_id={session_id}"
                )
            deck_dict = sm.get_slide_deck(session_id) or {}
            base = _public_app_url()

            deck_fields = _render_deck_response(deck_dict, session, base)

            return {
                "session_id": session_id,
                **deck_fields,
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP get_deck failed")
        raise MCPToolError(f"Internal error: {e}") from e
