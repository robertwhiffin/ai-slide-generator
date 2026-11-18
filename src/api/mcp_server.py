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
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Request
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import TextContent

from src.api.mcp_auth import MCPAuthError, mcp_auth_scope
from src.api.routes.chat import (
    _GENERATION_REFUSED_DETAILS,
    ENGINE_RACE_DETAIL,
    EngineModeUnresolvedError,
    EngineRaceError,
    EnteredTurn,
    SessionBusyError,
    apply_new_deck_tool_defaults,
    enter_chat_turn,
)
from src.api.services.chat_service import resolve_engine_mode_or_unavailable
from src.api.services.job_queue import get_job_status
from src.api.services.session_manager import (
    DeckModeLockedError,
    GenerationRefusedError,
    get_session_manager,
)
from src.core.database import get_db_session
from src.core.permission_context import get_permission_context
from src.core.settings_db import (
    get_default_design_system_id,
    get_default_slide_style_id,
    get_default_template_id,
)
from src.services import design_system_service
from src.services.conversation_pins import ActiveGraphReleaseUnavailableError
from src.services.generation_rollback import RESTORE_PENDING_MESSAGE, RollbackResult
from src.services.identity_provider import resolve_display_name
from src.services.mcp_deck_preview import (
    MCP_RESULT_BUDGET_BYTES,
    build_deck_preview,
    ds_asset_ids_in,
)
from src.services.permission_service import get_permission_service
from src.services.persisted_graph_release import (
    PersistedConfigurationUnavailableError,
)
from src.utils.preview_images import SVG_INLINE_MAX_BYTES

logger = logging.getLogger(__name__)

# Mirrors CHAT_MESSAGE_MAX_LENGTH (ChatRequest.message max_length). Disabled
# (None) for usability; set an int to re-enable the length guard.
MCP_PROMPT_LIMIT: Optional[int] = None


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
        shared ``PermissionService``. Creator access is resolved by the
        service via the root session's ``created_by`` (creators implicitly
        hold CAN_MANAGE, which includes edit), so a session the caller just
        created is editable before any DeckContributor row exists.
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


MCP_LEGACY_DECK_ERROR = (
    "This deck was made in Legacy mode and can't be edited over MCP. "
    "Open it in Tellr to keep working on it: {deck_url}"
)
MCP_OWNER_ONLY_ERROR = (
    "Only the deck's owner can edit it over MCP. "
    "Open it in Tellr to keep working on it: {deck_url}"
)
MCP_SESSION_BUSY_ERROR = (
    "This deck is busy with another request. Try again when it finishes."
)
MCP_DECK_LOCKED_ERROR = "This deck is locked by {name}."
MCP_NO_GRAPH_RELEASE_ERROR = (
    "Tellr can't generate decks right now: no active Graph Release. "
    "An admin needs to publish one."
)
MCP_UNAVAILABLE_ERROR = "Tellr is temporarily unavailable. Please retry."
MCP_ENGINE_RACE_ERROR = ENGINE_RACE_DETAIL
MCP_STOPPED_ERROR = "This generation was stopped in Tellr. The deck is unchanged."


def _deck_edit_url(session_id: str, *, base_url: Optional[str] = None) -> str:
    """The Tellr editor URL for a deck (relative when no public base URL is set).

    The one writer of this URL: the error copy and ``_deck_links``'s
    ``deck_url`` both come from here. ``base_url`` defaults to
    ``_public_app_url()``; a caller that already read it passes it in.
    """
    if base_url is None:
        base_url = _public_app_url()
    return f"{base_url}/sessions/{session_id}/edit"


def _deck_links(session_id: str, base_url: str) -> dict:
    """``deck_url`` (editor) and ``deck_view_url`` (view-only), the first keys of every response."""
    return {
        "deck_url": _deck_edit_url(session_id, base_url=base_url),
        "deck_view_url": (
            f"{base_url}/sessions/{session_id}/view"
            if base_url
            else f"/sessions/{session_id}/view"
        ),
    }


@dataclass
class McpToolReply:
    """A tool result: a JSON part, then (when there is one) the preview HTML part."""

    payload: dict
    preview_html: Optional[str] = None

    def to_content(self) -> list[TextContent]:
        items = [
            TextContent(
                type="text",
                text=json.dumps(
                    self.payload, ensure_ascii=False, indent=2, default=str
                ),
            )
        ]
        if self.preview_html is not None:
            items.append(TextContent(type="text", text=self.preview_html))
        return items


async def _enter_turn_or_tool_error(
    *,
    session_id: str,
    message: str,
    correlation_id: Optional[str],
) -> str:
    """Enter an Agent turn for ``session_id`` and return its request id.

    Goes through ``enter_chat_turn``, the same Enter the async chat route uses,
    and turns each refusal into a tool error with its user-facing copy. Anything
    unmapped propagates to the calling tool's own ``except Exception``.
    """
    try:
        entered: EnteredTurn = await enter_chat_turn(
            session_id=session_id,
            message=message,
            requested_deck_mode="agent",
            extra_payload={"correlation_id": correlation_id},
        )
    except SessionBusyError as e:
        raise MCPToolError(MCP_SESSION_BUSY_ERROR) from e
    except GenerationRefusedError as e:
        if e.reason == GenerationRefusedError.GENERATION_IN_FLIGHT:
            name = await asyncio.to_thread(resolve_display_name, e.holder)
            raise MCPToolError(MCP_DECK_LOCKED_ERROR.format(name=name)) from e
        raise MCPToolError(_GENERATION_REFUSED_DETAILS[e.reason]) from e
    except EngineRaceError as e:
        raise MCPToolError(MCP_ENGINE_RACE_ERROR) from e
    except EngineModeUnresolvedError as e:
        raise MCPToolError(MCP_UNAVAILABLE_ERROR) from e
    except ActiveGraphReleaseUnavailableError as e:
        raise MCPToolError(MCP_NO_GRAPH_RELEASE_ERROR) from e
    except DeckModeLockedError as e:
        if e.deck_mode == "legacy":
            raise MCPToolError(
                MCP_LEGACY_DECK_ERROR.format(deck_url=_deck_edit_url(session_id))
            ) from e
        raise
    return entered.request_id


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


def _template_names_and_ids(design_system_id: int) -> list[tuple[str, int]]:
    """The ACTIVE design system's ``(template name, template id)`` pairs.

    Eagerly materialized to PLAIN values while the DB session is still OPEN.
    This replaces a helper that returned the ``DesignSystem`` ORM instance
    itself: ``get_db_session()`` commits and closes on exit, and the
    sessionmaker uses SQLAlchemy's default ``expire_on_commit=True``, so that
    instance was detached with its ``templates`` relationship expired. Reading
    it raised ``DetachedInstanceError``, which the resolver caught and reported
    as "name matched nothing" — silently ignoring every valid production
    ``template_name``. Returning plain values makes that class of bug
    unavailable rather than merely fixed.

    Returns an empty list when the design system is missing or inactive, so the
    caller's "no match -> no pin" path is unchanged. Scoped to the ONE design
    system, so a name can never pin another system's template.
    """
    from src.core.database import get_db_session
    from src.database.models import DesignSystem
    from src.services.design_system_templates import materialize_templates

    with get_db_session() as db:
        design_system = (
            db.query(DesignSystem)
            .filter_by(id=design_system_id, is_active=True)
            .first()
        )
        if design_system is None:
            return []
        # Same idempotent derivation the generation path uses, for systems
        # imported before the templates table existed.
        materialize_templates(design_system)
        db.flush()  # newly materialized rows need ids before we read them
        return [
            (str(getattr(template, "name", None) or ""), int(template.id))
            for template in (getattr(design_system, "templates", None) or [])
            if getattr(template, "id", None) is not None
        ]


def _normalized_template_name(value: Optional[str]) -> str:
    """The comparison key for template-name matching: casefolded, with all
    whitespace runs collapsed to a single space.

    Applied to BOTH sides so the notion of "the same name" is defined in exactly
    one place — which is also what makes ambiguity detectable rather than
    order-dependent.
    """
    return " ".join((value or "").split()).casefold()


def _resolve_template_name(design_system_id: int, template_name: str) -> Optional[int]:
    """Resolve a template NAME to its id within *design_system_id*.

    MCP callers have no template ids — they see names (the compiler injects
    the name+description catalog as soft-pick guidance), so a caller that
    wants a specific layout pins it by name. Matching is case- and
    whitespace-insensitive.

    Because matching is insensitive, two DISTINCT rows can both match one query
    ("Two Column" and "two column"). That is AMBIGUOUS, and returning the first
    hit made the winner depend on relationship load order — a caller could
    silently get the other layout, and which one could change between requests.
    An ambiguous name is therefore UNRESOLVED: treated exactly like a name that
    matches nothing, and logged so the duplicate rows are discoverable.

    Returns ``None`` — never raises — when the design system is missing, the
    name matches nothing, the name is ambiguous, or the lookup fails. An
    unresolvable name must degrade to "no pin" (the model then soft-picks as
    usual), never a 500.
    """
    wanted = _normalized_template_name(template_name)
    if not wanted:
        return None
    try:
        matches = [
            template_id
            for name, template_id in _template_names_and_ids(design_system_id)
            if _normalized_template_name(name) == wanted
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            logger.warning(
                "MCP template_name %r is ambiguous in design system %s: it matches "
                "%d templates (ids %s). Ignoring the pin — the model soft-picks a "
                "layout instead. Rename the duplicates to make the name unique.",
                template_name,
                design_system_id,
                len(matches),
                ", ".join(str(template_id) for template_id in sorted(matches)),
            )
    except Exception:
        logger.exception(
            "Failed to resolve MCP template_name against design system %s",
            design_system_id,
        )
    return None


@mcp.tool(
    name="create_deck",
    description=(
        "Generate a new slide deck from a natural-language prompt. Returns "
        "`deck_url` and `deck_view_url` at once, plus a session_id and a "
        "request_id; show `deck_url` to the user now, and poll "
        "get_deck_status for completion. The resulting deck is attributed to the calling user and "
        "appears in their tellr UI. It is an Agent deck with the app's default "
        "tools for a new deck (for example Genie One, when an admin turned that "
        "default on). Any slide count belongs in the prompt, for example "
        "'make 6 slides'. The deck uses the org-default design system unless "
        "design_system_id or slide_style_id says otherwise; pass template_name "
        "to pin one of that design system's named templates (otherwise the "
        "model picks the best-matching one)."
    ),
)
async def create_deck(
    ctx: Context,
    prompt: str,
    slide_style_id: Optional[int] = None,
    design_system_id: Optional[int] = None,
    template_name: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    return await _create_deck_impl(
        request=_request_from_context(ctx),
        prompt=prompt,
        slide_style_id=slide_style_id,
        design_system_id=design_system_id,
        template_name=template_name,
        correlation_id=correlation_id,
    )


async def _create_deck_impl(
    request: Request,
    prompt: str,
    slide_style_id: Optional[int] = None,
    design_system_id: Optional[int] = None,
    template_name: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    """Implementation, separated from the decorated tool for testability."""
    if not prompt or not prompt.strip():
        raise MCPToolError("prompt must be a non-empty string")
    if MCP_PROMPT_LIMIT is not None and len(prompt) > MCP_PROMPT_LIMIT:
        raise MCPToolError(f"prompt is too long (max {MCP_PROMPT_LIMIT} characters)")
    # Same inbound prompt-injection guard as the browser chat endpoints (AISEC-248).
    from src.utils.pi_filter import scan_for_injection
    injection_matches = scan_for_injection(prompt)
    if injection_matches:
        logger.warning(
            "Blocked MCP create_deck prompt (injection patterns)",
            extra={"patterns": injection_matches},
        )
        raise MCPToolError(
            "prompt was blocked because it resembles a prompt-injection attempt"
        )

    try:
        with mcp_auth_scope(request) as identity:
            agent_config: dict[str, Any] = {"tools": []}
            # Resolve the style SOURCE exactly as the browser chat flow does
            # (see routes/chat.py::_apply_org_default_style_source): a design
            # system outranks a slide style, an explicit choice always wins,
            # and only ONE source is ever seeded so the prompt never carries
            # two competing style authorities. Before this, MCP decks could not
            # reach a design system at all — only slide_style_id was ever set,
            # so they always got the default slide style.
            effective_ds_id = design_system_id
            if effective_ds_id is None and slide_style_id is None:
                effective_ds_id = get_default_design_system_id()

            if effective_ds_id is not None:
                agent_config["design_system_id"] = effective_ds_id
                # Templates belong to a design system, so a name is only
                # meaningful here. No name, or an unresolvable one (logged) ->
                # the design system's default template; no default -> no pin,
                # and the model soft-picks from the catalog the compiler injects.
                template_id = None
                if template_name and template_name.strip():
                    template_id = _resolve_template_name(effective_ds_id, template_name)
                    if template_id is None:
                        logger.warning(
                            "MCP create_deck: template_name %r matched no template "
                            "on design system %s; using its default template, if any",
                            template_name,
                            effective_ds_id,
                        )
                if template_id is None:
                    template_id = get_default_template_id(effective_ds_id)
                if template_id is not None:
                    agent_config["template_id"] = template_id
            else:
                # No design system in play: fall back to the tellr-configured
                # default slide style rather than the hardcoded
                # DEFAULT_SLIDE_STYLE constant agent_factory would otherwise use.
                effective_style_id = slide_style_id
                if effective_style_id is None:
                    effective_style_id = get_default_slide_style_id()
                if effective_style_id is not None:
                    agent_config["slide_style_id"] = effective_style_id
                if template_name and template_name.strip():
                    logger.warning(
                        "MCP create_deck: template_name %r ignored — templates "
                        "require a design system and none is selected",
                        template_name,
                    )

            # The app's new-deck tool defaults, as the browser seeds them. A
            # caller with no token can't use a tool, so it gets none.
            apply_new_deck_tool_defaults(
                agent_config,
                client_set_fields=(
                    frozenset({"tools"}) if identity.token is None else frozenset()
                ),
            )

            session_manager = get_session_manager()
            try:
                session = session_manager.create_session(
                    created_by=identity.user_name,
                    agent_config=agent_config,
                    # An Agent deck: deck_mode="agent" pins the active Graph Release.
                    deck_mode="agent",
                )
            except ActiveGraphReleaseUnavailableError as e:
                raise MCPToolError(MCP_NO_GRAPH_RELEASE_ERROR) from e
            # create_session returns a dict (see SessionManager.create_session);
            # guard against a model-object return defensively so this stays
            # robust if the service ever switches to returning a Pydantic model.
            session_id = (
                session["session_id"]
                if isinstance(session, dict)
                else session.session_id
            )

            request_id = await _enter_turn_or_tool_error(
                session_id=session_id,
                message=prompt,
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
                **_deck_links(session_id, _public_app_url()),
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
# Deck reply builder (shared by get_deck_status and get_deck)
# ---------------------------------------------------------------------------


# The longest preview note the builder (or the fallback below) can write, with 6-digit
# counts: the placeholder that sizes item 1 before the real preview exists.
_LONGEST_PREVIEW_NOTE = (
    "Showing 999999 of 999999 slides as a preview "
    "(standard fonts, images not shown). Open the full deck in tellr."
)
# When building the preview fails, the reply still carries the links and this note.
_PREVIEW_UNAVAILABLE_NOTE = "A preview is not available for this deck. Open the full deck in tellr."


def _build_deck_reply(
    deck_dict: Optional[dict],
    session: dict,
    session_id: str,
    base_url: str,
    *,
    head: dict,
    tail: dict,
) -> McpToolReply:
    """The deck-shaped reply shared by ``get_deck_status`` (ready) and ``get_deck``.

    The payload is ``head`` (links first, then ids/status), ``title``, ``slide_count``,
    ``preview``, then ``tail``. The preview is built from the persisted deck after
    slide-number tokens, with no image-library or design-system byte read: only small
    SVGs scoped to the session's active design system are inlined. Its HTML ceiling is
    the result budget minus the UTF-8 bytes of the JSON part, sized with a worst-case
    ``preview`` entry first, so a long ``reply`` shrinks the preview rather than
    pushing the whole result over budget.

    A failure anywhere in building the preview (the css scanners, the SVG read) is
    logged and costs only the preview: the reply is then the JSON part alone, links
    first, with ``preview.included`` false and ``_PREVIEW_UNAVAILABLE_NOTE``.
    """
    from src.api.services.chat_service import resolve_active_design_system_id
    from src.utils.slide_number_tokens import substitute_deck_slide_numbers

    deck_dict = deck_dict or {}

    title = session.get("title") or deck_dict.get("title")
    slide_count = len(deck_dict.get("slides") or [])

    def payload_with(preview: dict) -> dict:
        return {
            **head,
            "title": title,
            "slide_count": slide_count,
            "preview": preview,
            **tail,
        }

    placeholder = {
        "included": True,
        "slides_shown": 999999,
        "slides_total": 999999,
        "images_hidden": 999999,
        "note": _LONGEST_PREVIEW_NOTE,
    }
    item1_bytes = len(
        McpToolReply(payload_with(placeholder)).to_content()[0].text.encode("utf-8")
    )
    max_html_bytes = MCP_RESULT_BUDGET_BYTES - item1_bytes - 256

    try:
        substitute_deck_slide_numbers(deck_dict)
        asset_ids = ds_asset_ids_in(deck_dict)
        svg_assets: dict[int, str] = {}
        if asset_ids:
            design_system_id = resolve_active_design_system_id(session_id)
            with get_db_session() as db:
                svg_assets = design_system_service.get_small_svg_assets(
                    db,
                    asset_ids,
                    design_system_id=design_system_id,
                    max_bytes=SVG_INLINE_MAX_BYTES,
                )

        preview = build_deck_preview(
            deck_dict,
            title=deck_dict.get("title") or session.get("title"),
            deck_url=head["deck_url"],
            svg_assets=svg_assets,
            max_html_bytes=max_html_bytes,
        )
    except Exception:
        logger.exception("MCP deck preview failed; replying without it (session_id=%s)", session_id)
        return McpToolReply(
            payload_with(
                {
                    "included": False,
                    "slides_shown": 0,
                    "slides_total": slide_count,
                    "images_hidden": 0,
                    "note": _PREVIEW_UNAVAILABLE_NOTE,
                }
            )
        )
    return McpToolReply(payload_with(preview.as_payload()), preview.html)


# ---------------------------------------------------------------------------
# get_deck_status
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_deck_status",
    structured_output=False,
    description=(
        "Poll the status of a deck generation or edit job. Every response "
        "starts with `deck_url` (the full editor) and `deck_view_url` "
        "(view-only); show `deck_url` to the user. Returns lightweight "
        "status while pending/running. When ready, the response is a JSON "
        "part (links first, then title, slide_count and the reply) plus a "
        "second part that is a **preview** HTML page of at most 10 slides "
        "with standard fonts and images not shown. The full deck and all "
        "editing are at `deck_url`. "
        "A ready turn may leave the deck UNCHANGED (the assistant may "
        "answer or ask a question instead of editing). Show `reply` (the "
        "assistant's final message of the turn) to the user; `deck_changed` "
        "says whether the deck was modified, and "
        "metadata.clarification_needed is always its opposite. On an Agent "
        "turn (every turn create_deck and edit_deck start), "
        "metadata.clarification repeats the reply when deck_changed is false, "
        "and a turn with no recorded intent reports deck_changed false. On a "
        "Legacy turn, deck_changed is false only when the assistant asked a "
        "clarifying question instead of editing: metadata.clarification is "
        "that question, and reply may be null. A stopped generation reports "
        "status failed."
    ),
)
async def get_deck_status(
    ctx: Context,
    session_id: str,
    request_id: str,
) -> list[TextContent]:
    reply = await _get_deck_status_impl(
        request=_request_from_context(ctx),
        session_id=session_id,
        request_id=request_id,
    )
    return reply.to_content()


async def _get_deck_status_impl(
    request: Request, session_id: str, request_id: str
) -> McpToolReply:
    """Implementation, separated from the decorated tool for testability.

    Mirrors the data-access pattern of ``GET /api/chat/poll/{request_id}``:
    the in-memory ``jobs`` dict is authoritative for pending/running/failed
    state, but worker completion pops the in-memory entry (see
    ``job_queue.process_chat_request``'s ``finally`` clause). To see the
    ready/error terminal state we have to fall back to the persisted
    ``chat_request`` DB row, then re-fetch the deck via
    ``SessionManager.get_slide_deck`` since neither ``get_job_status``
    nor ``get_session`` carry the structured deck payload. Every branch's payload
    starts with the deck links.
    """
    try:
        with mcp_auth_scope(request):
            if not permission_service.can_view_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to view it"
                )

            session_manager = get_session_manager()
            base = _public_app_url()
            links = _deck_links(session_id, base)

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
                    return McpToolReply({
                        **links,
                        "session_id": session_id,
                        "request_id": request_id,
                        "status": job_status,
                        "progress": entry.get("progress"),
                    })

                if job_status == "failed":
                    return McpToolReply({
                        **links,
                        "session_id": session_id,
                        "request_id": request_id,
                        "status": "failed",
                        "error": entry.get("error", "Generation failed"),
                    })
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
                return McpToolReply({
                    **links,
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": db_status,
                    "progress": None,
                })

            if db_status == "cancelled":
                # Only a stop (``cancel_chat``, by the request's sender) writes
                # ``cancelled``; timeouts and orphan sweeps write ``error``.
                if (
                    chat_request.get("rollback_outcome")
                    == RollbackResult.RESTORE_FAILED.value
                ):
                    # The stop's restore failed: the deck may still hold the
                    # turn's changes and stays locked until a retry restores
                    # it, so it is not "unchanged". Report the request's own
                    # restore-pending copy until a retry settles the request
                    # (it then records the final outcome and clears the copy).
                    return McpToolReply({
                        **links,
                        "session_id": session_id,
                        "request_id": request_id,
                        "status": "failed",
                        "error": chat_request.get("error_message")
                        or RESTORE_PENDING_MESSAGE,
                    })
                return McpToolReply({
                    **links,
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "failed",
                    "error": MCP_STOPPED_ERROR,
                })

            if db_status == "error":
                return McpToolReply({
                    **links,
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "failed",
                    "error": chat_request.get("error_message")
                    or "Generation failed",
                })

            if db_status != "completed":
                # Unknown terminal state — surface as failure so callers
                # aren't left polling forever.
                return McpToolReply({
                    **links,
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "failed",
                    "error": f"Unknown job status: {db_status!r}",
                })

            # Ready path. The worker stored the deck via
            # SessionManager.save_slide_deck (from inside send_message_streaming)
            # before calling set_chat_request_result, so get_slide_deck is
            # authoritative.
            session = session_manager.get_session(session_id)
            deck_dict = session_manager.get_slide_deck(session_id)

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

            # ``reply``: the turn's last assistant ``llm_response`` row, for both
            # engines (a graph turn writes it only from architect code).
            reply = next(
                (
                    message.get("content")
                    for message in reversed(messages)
                    if message.get("role") == "assistant"
                    and message.get("message_type") == "llm_response"
                ),
                None,
            )

            if result_metadata.get("engine_mode") == "graph":
                # Agent turn: the architect's intent says whether the deck
                # changed. ``discuss`` / ``confirm_design_contract`` return
                # before any deck write, so the reply is the answer or question
                # and is surfaced as the clarification. A missing intent is
                # reported as unchanged (pre-pass Ruling 2: such a result comes
                # only from an app turn made before this release).
                deck_changed = result_metadata.get("architect_intent") in (
                    "build",
                    "edit",
                )
                clarification_needed = not deck_changed
                clarification = reply if clarification_needed else None
            else:
                # WG2-01 (Legacy results, which carry no ``engine_mode``). An
                # edit instruction that names no slide is DELIBERATELY not
                # applied: chat_service asks which slide instead (its RC10 twins,
                # plus the ambiguous add-vs-replace pair) and attaches
                # ``clarification_needed`` to the COMPLETE event, which
                # ``job_queue.process_chat_request`` copies verbatim into
                # ``result["metadata"]``.
                #
                # Such a turn completes normally, so "ready" is the honest status
                # and ``replacement_info`` is None, which is indistinguishable
                # from an edit that applied but replaced nothing. Surfaced
                # ADDITIVELY, and ``status`` keeps its existing meaning.
                clarification_needed = bool(
                    result_metadata.get("clarification_needed")
                )
                deck_changed = not clarification_needed
                clarification = None
                if clarification_needed:
                    # The question itself, so a caller can act on it without
                    # re-filtering the transcript. Last one wins.
                    clarification = next(
                        (
                            message.get("content")
                            for message in reversed(messages)
                            if message.get("message_type") == "clarification"
                        ),
                        None,
                    )

            return _build_deck_reply(
                deck_dict,
                session,
                session_id,
                base,
                head={
                    **links,
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "ready",
                },
                tail={
                    "reply": reply,
                    "deck_changed": deck_changed,
                    "replacement_info": result.get("replacement_info"),
                    "metadata": {
                        "tool_calls": result_metadata.get("tool_calls"),
                        "latency_ms": result_metadata.get("latency_ms")
                        or result_metadata.get("latency_seconds"),
                        "experiment_url": result.get("experiment_url"),
                        "session_title": result.get("session_title"),
                        "clarification_needed": clarification_needed,
                        "clarification": clarification,
                    },
                },
            )
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


def _require_agent_deck_owner(session_id: str, user_name: str) -> None:
    """Refuse unless ``user_name`` owns an Agent deck nobody else is generating on.

    Mirrors the app route's owner and live-generation gate
    (``_check_chat_permission(gate_owner_on_generation=True)``), so an MCP edit
    cannot do what the same user in the app could not. Collaborators edit in the
    Tellr app, not over MCP.
    """
    session_manager = get_session_manager()
    session_info = session_manager.get_session(session_id)
    if session_info.get("created_by") != user_name or session_info.get(
        "is_contributor_session", False
    ):
        raise MCPToolError(
            MCP_OWNER_ONLY_ERROR.format(deck_url=_deck_edit_url(session_id))
        )

    try:
        engine_mode = resolve_engine_mode_or_unavailable(session_id)
    except PersistedConfigurationUnavailableError as e:
        raise MCPToolError(MCP_UNAVAILABLE_ERROR) from e
    if engine_mode == "monolith":
        raise MCPToolError(
            MCP_LEGACY_DECK_ERROR.format(deck_url=_deck_edit_url(session_id))
        )

    # Only a LIVE generation by someone else blocks the owner (an idle
    # contributor's heartbeat lock never does).
    holder = session_manager.live_generation_holder(session_id, live_only=True)
    if holder and holder != user_name:
        raise MCPToolError(
            MCP_DECK_LOCKED_ERROR.format(name=resolve_display_name(holder))
        )


@mcp.tool(
    name="edit_deck",
    description=(
        "Ask Tellr's architect about an existing deck: either a change to make "
        "or a question about it. Name slides by number in the instruction "
        "(e.g. \"On slides 1 and 4, shorten the titles\"). A change is made to "
        "this same deck, so the session_id and deck_url stay stable; "
        "get_deck_status's deck_changed says whether the turn changed it. "
        "Returns `deck_url` and `deck_view_url` at once (show `deck_url` to "
        "the user) and a request_id; poll get_deck_status until it completes, "
        "and show the user the `reply` it returns, which is the architect's answer or a "
        "summary of what changed. Only the deck's owner can edit it over MCP, "
        "and only decks made in Agent mode; for anything else, open the deck "
        "in Tellr."
    ),
)
async def edit_deck(
    ctx: Context,
    session_id: str,
    instruction: str,
    correlation_id: Optional[str] = None,
) -> dict:
    return await _edit_deck_impl(
        request=_request_from_context(ctx),
        session_id=session_id,
        instruction=instruction,
        correlation_id=correlation_id,
    )


async def _edit_deck_impl(
    request: Request,
    session_id: str,
    instruction: str,
    correlation_id: Optional[str] = None,
) -> dict:
    """Implementation, separated from the decorated tool for testability.

    Enters an Agent turn on the caller's own deck with the instruction verbatim
    (``_enter_turn_or_tool_error``). The owner and Agent-mode checks run first,
    so a refused edit writes nothing.
    """
    if not instruction or not instruction.strip():
        raise MCPToolError("instruction must be a non-empty string")
    if MCP_PROMPT_LIMIT is not None and len(instruction) > MCP_PROMPT_LIMIT:
        raise MCPToolError(
            f"instruction is too long (max {MCP_PROMPT_LIMIT} characters)"
        )
    # Same inbound prompt-injection guard as the browser chat endpoints and
    # create_deck (AISEC-248).
    from src.utils.pi_filter import scan_for_injection
    injection_matches = scan_for_injection(instruction)
    if injection_matches:
        logger.warning(
            "Blocked MCP edit_deck instruction (injection patterns)",
            extra={"patterns": injection_matches},
        )
        raise MCPToolError(
            "instruction was blocked because it resembles a prompt-injection attempt"
        )

    try:
        with mcp_auth_scope(request) as identity:
            if not permission_service.can_edit_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to edit it"
                )

            # Off the event loop, as the app route's gate is: it reads the DB
            # and, on a locked deck, may make a SCIM display-name call (cached
            # per process only after a name's first lookup). ``to_thread``
            # copies the ContextVars ``mcp_auth_scope`` bound.
            await asyncio.to_thread(
                _require_agent_deck_owner, session_id, identity.user_name
            )

            request_id = await _enter_turn_or_tool_error(
                session_id=session_id,
                message=instruction,
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
                    "correlation_id": correlation_id,
                },
            )

            return {
                **_deck_links(session_id, _public_app_url()),
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
    structured_output=False,
    description=(
        "Retrieve the current state of a deck without submitting new work. "
        "The response is a JSON part (`deck_url` and `deck_view_url` first, "
        "then title and slide_count) plus a second part that is a **preview** "
        "HTML page of at most 10 slides with standard fonts and images not "
        "shown. The full deck and all editing are at `deck_url`; show "
        "`deck_url` to the user. Idempotent; no job queue interaction. Use "
        "when you have a session_id from earlier and want to see the deck "
        "without polling."
    ),
)
async def get_deck(ctx: Context, session_id: str) -> list[TextContent]:
    reply = await _get_deck_impl(
        request=_request_from_context(ctx),
        session_id=session_id,
    )
    return reply.to_content()


async def _get_deck_impl(request: Request, session_id: str) -> McpToolReply:
    """Implementation, separated from the decorated tool for testability.

    Idempotent read-only counterpart to ``get_deck_status``'s ready branch:
    no job-queue interaction, no ``request_id``/``status`` in the response.
    Reuses ``_build_deck_reply`` so the deck-shaped fields stay identical to
    those in a ready ``get_deck_status`` reply.
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

            return _build_deck_reply(
                deck_dict,
                session,
                session_id,
                base,
                head={**_deck_links(session_id, base), "session_id": session_id},
                tail={},
            )
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP get_deck failed")
        raise MCPToolError(f"Internal error: {e}") from e
