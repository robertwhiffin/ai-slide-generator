"""Chat service wrapper around the agent.

All session state is stored in the database (PostgreSQL in dev, Lakebase in prod).
Sessions are auto-created on first message if they don't exist.

Scripts are stored directly on Slide objects. When a slide is replaced,
its scripts are automatically replaced with it - no separate cleanup needed.
"""

import contextvars
import logging
import queue
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import SessionNotFoundError, VersionConflictError, get_session_manager
from src.api.services.session_naming import generate_session_title
from src.core.databricks_client import (
    get_current_username,
    get_service_principal_folder,
    get_system_client,
)
from src.domain.slide import Slide, has_slide_wrapper
from src.domain.slide_deck import SlideDeck
from src.api.schemas.agent_config import resolve_agent_config
from src.services.agent_factory import build_agent_for_request
from src.services.streaming_callback import StreamingCallbackHandler
from src.utils.html_utils import (
    extract_canvas_ids_from_html,
    split_script_by_canvas,
)
from src.utils.ds_asset_utils import (
    substitute_deck_dict_ds_assets,
    substitute_ds_asset_placeholders,
)
from src.utils.image_utils import substitute_deck_dict_images, substitute_image_placeholders

logger = logging.getLogger(__name__)

#: The slide ``insert_slide`` adds when the caller supplies no HTML.
#: The wrapper is not decoration: ``has_slide_wrapper`` is what the parser, the
#: frontend thumbnail panel and every export path use to recognise a slide, so an
#: empty slide still has to carry it.  Left otherwise bare deliberately — the deck's
#: own CSS styles it, and any content here would be content nobody asked for.
BLANK_SLIDE_HTML = '<div class="slide"></div>'


def resolve_active_design_system_id(session_id: Optional[str]) -> Optional[int]:
    """The session's pinned/active design-system id, or None.

    ``{{ds-asset:ID}}`` resolution is scoped to this id at every deck response
    boundary (render, export). A generated deck can only legitimately reference
    assets of the session's active design system, so scoping to it makes a
    foreign handle — e.g. one echoed from a crafted pinned template's HTML into
    the generated deck — go inert instead of leaking another system's bytes.
    Any lookup miss (no session, no pin) resolves to None, which the resolver
    treats as fail-closed (nothing resolves).
    """
    if not session_id:
        return None
    from src.api.services.session_manager import get_session_manager

    try:
        session = get_session_manager().get_session(session_id)
    except Exception:
        return None
    return resolve_agent_config(session.get("agent_config")).design_system_id


def _sanitize_replacement_info(replacement_info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Sanitize replacement_info for JSON serialization.
    
    Removes or converts non-serializable fields like Slide objects.
    The frontend doesn't need raw Slide objects since it gets the full deck.
    """
    if not replacement_info:
        return None
    
    # Create a copy without replacement_slides (contains Slide objects)
    sanitized = {
        k: v for k, v in replacement_info.items()
        if k != "replacement_slides"
    }
    return sanitized


# ---------------------------------------------------------------------------
# Engine-mode selection (ws4d D1)
# ---------------------------------------------------------------------------

# The chat-input trigger that puts a deck on the LangGraph engine.
#
# Deliberately NOT hardened (plan D0): a loose, case-sensitive substring match
# anywhere in the deck's first user message, with no authorisation check.  The
# switch exists so one developer can exercise both engines in one deployment;
# if it ever outlives testing it needs a strict form (exact prefix, first
# message only) plus an authorisation check, because a phrase matched anywhere
# in user text can be tripped by pasted content.  Recorded, not built.
AGENT_MODE_PHRASE = "USE AGENT MODE"


def _selects_agent_mode(content: Optional[str]) -> bool:
    """Whether one message's text selects the graph engine.

    The single authority for the match, shared with
    ``SessionManager.duplicate_session``'s marker carry so the two cannot
    disagree about what a marker is.
    """
    return bool(content) and AGENT_MODE_PHRASE in content


def resolve_engine_mode(session_id: Optional[str]) -> str:
    """Return the engine this deck's turns run on: ``"graph"`` or ``"monolith"``.

    **Sticky, and derived from the transcript.**  Evaluated per message, only
    turn 1 would carry the phrase and turn 2 would fall back — a deck written
    alternately by both engines diverges between ``session_slides`` rows and
    ``deck_json``, and the architect's own conversation lives in the
    checkpointer under a ``thread_id``.  So the answer is a property of the
    deck, read off the **earliest** ``role='user'`` message.  A later message
    carrying the phrase must not switch a monolith deck, and assistant messages
    are ignored so echoed tool output cannot flip the engine.

    **Resolved on the OWNER DECK's session, not the calling session** (ruling
    W-3).  Decks are shared through ``UserSession.parent_session_id``; mode is
    per-session while divergence is per-DECK, so a contributor carrying the
    phrase would write rows while a contributor without it wrote ``deck_json``
    on the same deck — exactly the divergence stickiness exists to prevent.
    The owner is resolved with the same ``_get_deck_owner_session`` hop
    ``read_deck_spec`` uses, so a contributor inherits the owner's engine.

    **Filters on ``role`` only, never on ``message_type``.**  The two live
    paths write different types for the same user turn (``"user_input"`` on the
    sync/streaming path, ``"user_query"`` on the async route and MCP), so a
    ``message_type`` filter would see half the traffic.

    Nothing about mode is stored: the answer is derived from the database on
    every call, so there is nothing to keep in sync and it is multi-worker safe
    by construction.

    Args:
        session_id: The session whose turn is about to run.  May be a
            contributor session, an owner session, or ``None``.

    Returns:
        ``"graph"`` when the owner deck's first user message carries
        :data:`AGENT_MODE_PHRASE`, else ``"monolith"``.  A missing session, a
        deck with no user turn yet, and an empty first message all resolve to
        ``"monolith"`` — mode resolution is a test affordance and must never be
        the thing that fails a turn.
    """
    from src.core.database import get_db_session
    from src.database.models.session import SessionMessage

    if not session_id:
        return "monolith"

    session_manager = get_session_manager()
    try:
        with get_db_session() as db:
            session = session_manager._get_session_or_raise(db, session_id)
            deck_owner = session_manager._get_deck_owner_session(db, session)
            earliest_user_message = (
                db.query(SessionMessage)
                .filter(
                    SessionMessage.session_id == deck_owner.id,
                    SessionMessage.role == "user",
                )
                .order_by(SessionMessage.created_at.asc(), SessionMessage.id.asc())
                .first()
            )
            content = earliest_user_message.content if earliest_user_message else None
            owner_session_id = deck_owner.session_id
    except SessionNotFoundError:
        logger.warning(
            "Engine-mode resolution found no session; defaulting to monolith",
            extra={"session_id": session_id},
        )
        return "monolith"

    mode = "graph" if _selects_agent_mode(content) else "monolith"
    logger.info(
        "Resolved engine mode",
        extra={
            "session_id": session_id,
            "deck_owner_session_id": owner_session_id,
            "engine_mode": mode,
        },
    )
    return mode


def resolve_engine_mode_or(
    session_id: Optional[str], fallback: str = "monolith"
) -> str:
    """:func:`resolve_engine_mode`, where a FAILURE to resolve never fails the turn.

    ``resolve_engine_mode`` handles its three "no answer" cases itself and
    returns monolith for them, but an unexpected database error propagates —
    and every call site sits on the request path of a turn that would otherwise
    have run perfectly well.  Measured: with the re-resolve in
    ``send_message_streaming`` calling it bare, three pre-existing monolith
    tests died with ``psycopg2.ProgrammingError: can't adapt type 'MagicMock'``,
    which is the same shape a transient database error takes in production — a
    monolith turn that used to need no database read at all now 500s.

    Task 1's own contract is that mode resolution "is a test affordance and must
    never be the thing that fails a turn".  This is where that promise is kept:
    on any exception the caller's existing value stands.

    Args:
        session_id: Session whose turn is about to run.
        fallback: What to return if resolution raises — the mode the caller
            already had, so a failure is a no-op rather than a downgrade.
    """
    try:
        return resolve_engine_mode(session_id)
    except Exception:
        logger.warning(
            "Engine-mode resolution failed; keeping the mode already in hand",
            extra={"session_id": session_id, "engine_mode": fallback},
            exc_info=True,
        )
        return fallback


class ChatService:
    """Service for managing chat interactions with the AI agent.

    All session state is persisted in the database via SessionManager.
    The agent is built per-request from the session's agent_config,
    replacing the previous singleton agent pattern.
    """

    def __init__(self):
        """Initialize the chat service.

        The agent is no longer a singleton — it is built per-request from the
        session's agent_config via build_agent_for_request().
        """
        logger.info("Initializing ChatService")

        # Thread lock for safe deck cache access
        self._cache_lock = threading.Lock()

        # In-memory cache of slide decks (keyed by session_id)
        # This avoids re-parsing HTML on every request
        self._deck_cache: Dict[str, SlideDeck] = {}

        # DB version each cached deck corresponds to. The cache is per-process
        # while prod runs multiple uvicorn workers sharing one database, so a
        # cache hit is only valid if the DB version hasn't moved on.
        self._deck_cache_versions: Dict[str, int] = {}

        logger.info("ChatService initialized successfully")

    def _substitute_images_for_response(self, deck_dict, raw_html=None, *, session_id):
        """Apply image + design-system asset substitution before sending to client.

        Converts {{image:ID}} placeholders (image_assets) and {{ds-asset:ID}}
        placeholders (design_system_asset) to base64 data URIs in deck dicts and
        raw HTML. Called at API response boundaries so that stored/cached HTML
        keeps lightweight placeholders (avoiding LLM context bloat). The two
        namespaces are resolved independently.

        ``session_id`` (keyword-only, mandatory) scopes ds-asset resolution to the
        session's active design system so a foreign ``{{ds-asset:ID}}`` handle
        cannot disclose another system's bytes.
        """
        from src.core.database import get_db_session

        needs_deck = deck_dict and any(
            "{{image:" in s.get("html", "") for s in deck_dict.get("slides", [])
        )
        needs_html = raw_html and "{{image:" in raw_html
        needs_deck_html = deck_dict and deck_dict.get("html_content") and "{{image:" in deck_dict.get("html_content", "")
        # background-image url() references live in the deck's top-level
        # ``css``, not in slide html — gate on it too, else a deck whose only
        # image reference is in css skips the resolver entirely (same gap the
        # ds-asset gate below closed; substitute_deck_dict_images covers the
        # css field).
        needs_deck_css = bool(
            deck_dict
            and deck_dict.get("css")
            and "{{image:" in deck_dict.get("css", "")
        )

        # Design-system brand assets ({{ds-asset:ID}}) — parallel, orthogonal namespace.
        ds_needs_deck = deck_dict and any(
            "{{ds-asset:" in s.get("html", "") for s in deck_dict.get("slides", [])
        )
        ds_needs_html = raw_html and "{{ds-asset:" in raw_html
        ds_needs_deck_html = bool(
            deck_dict
            and deck_dict.get("html_content")
            and "{{ds-asset:" in deck_dict.get("html_content", "")
        )
        # @font-face src url() fonts and background-image url() live in the deck's
        # top-level ``css``, not in slide html — gate on it too, else a deck whose
        # only brand-asset reference is in css skips the resolver entirely
        # (substitute_deck_dict_ds_assets covers the css field).
        ds_needs_deck_css = bool(
            deck_dict
            and deck_dict.get("css")
            and "{{ds-asset:" in deck_dict.get("css", "")
        )

        if (
            needs_deck or needs_html or needs_deck_html or needs_deck_css
            or ds_needs_deck or ds_needs_html or ds_needs_deck_html or ds_needs_deck_css
        ):
            with get_db_session() as db:
                if needs_deck or needs_deck_html or needs_deck_css:
                    substitute_deck_dict_images(deck_dict, db)
                if needs_html:
                    raw_html = substitute_image_placeholders(raw_html, db)
                if ds_needs_deck or ds_needs_deck_html or ds_needs_deck_css or ds_needs_html:
                    ds_id = resolve_active_design_system_id(session_id)
                    if ds_needs_deck or ds_needs_deck_html or ds_needs_deck_css:
                        substitute_deck_dict_ds_assets(deck_dict, db, design_system_id=ds_id)
                    if ds_needs_html:
                        raw_html = substitute_ds_asset_placeholders(
                            raw_html, db, design_system_id=ds_id
                        )
        return deck_dict, raw_html

    def _build_agent_for_session(
        self, session_id: str, db_session: Dict[str, Any], mode: str = "generate"
    ) -> tuple:
        """Build a per-request agent from session's agent_config.

        Also ensures the MLflow experiment exists and hydrates chat history.

        Args:
            session_id: Session identifier
            db_session: Session dict from session_manager.get_session()
            mode: ``"generate"`` or ``"edit"`` — forwarded to the agent
                factory so the system prompt includes only mode-relevant
                instructions.

        Returns:
            Tuple of (agent, session_data, experiment_url)
        """
        # Resolve agent config from session
        agent_config = resolve_agent_config(db_session.get("agent_config"))

        # Ensure user experiment
        try:
            username = get_current_username()
        except Exception as e:
            logger.warning(f"ChatService: Failed to get current username: {e}")
            username = "unknown"

        experiment_id, experiment_url = self._ensure_user_experiment(
            session_id, username
        )

        # Active experiment must be set before LangChain autolog emits traces (tools, etc.).
        if experiment_id:
            import mlflow

            mlflow.set_experiment(experiment_id=experiment_id)

        # Persist experiment_id to database if newly created
        if experiment_id and experiment_id != db_session.get("experiment_id"):
            session_manager = get_session_manager()
            session_manager.set_experiment_id(session_id, experiment_id)

        # Build session_data for agent factory (mutable — Genie tool updates it)
        session_data = {
            "session_id": session_id,
            "genie_conversation_id": db_session.get("genie_conversation_id"),
            "experiment_id": experiment_id or db_session.get("experiment_id"),
        }

        # Build agent with mode-specific prompt
        agent = build_agent_for_request(agent_config, session_data, mode=mode)

        # Hydrate chat history from DB into the agent's session
        chat_history = ChatMessageHistory()
        message_count = self._hydrate_chat_history(session_id, chat_history)

        # Register session with the agent so it has conversation context
        agent.sessions[session_id] = {
            "chat_history": chat_history,
            "genie_conversation_id": session_data.get("genie_conversation_id"),
            "experiment_id": session_data.get("experiment_id"),
            "experiment_url": experiment_url,
            "username": username,
            "profile_name": "default",
            "message_count": message_count,
        }

        return agent, session_data, experiment_url

    def _persist_genie_conversation_ids(
        self, session_id: str, session_data: Dict[str, Any], original_genie_id: Optional[str]
    ) -> None:
        """Persist genie conversation_ids after a request completes.

        Updates both:
        1. The legacy genie_conversation_id column (backward compat)
        2. Per-space conversation_ids in the session's agent_config JSON

        The Genie tool closure updates session_data in-place when a new
        conversation is initialized. This method reads those updates and
        persists them to the database.
        """
        session_manager = get_session_manager()

        # 1. Legacy column persistence
        new_genie_id = session_data.get("genie_conversation_id")
        if new_genie_id != original_genie_id:
            session_manager.set_genie_conversation_id(session_id, new_genie_id)
            logger.info(
                "Persisted updated genie_conversation_id",
                extra={
                    "session_id": session_id,
                    "old_genie_id": original_genie_id,
                    "new_genie_id": new_genie_id,
                },
            )

        # 2. Per-space conversation_ids in agent_config
        self._persist_conversation_ids_to_agent_config(
            session_id, session_data, session_manager
        )

    def _persist_conversation_ids_to_agent_config(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        session_manager: Any,
    ) -> None:
        """Write per-space conversation_ids from session_data back into agent_config.

        Reads the session's current agent_config, updates each GenieTool's
        conversation_id from session_data, and saves if any changed.
        """
        from src.api.schemas.agent_config import GenieTool

        try:
            session = session_manager.get_session(session_id)
            agent_config = resolve_agent_config(session.get("agent_config"))

            updated = False
            for tool in agent_config.tools:
                if isinstance(tool, GenieTool):
                    conv_key = f"genie_conversation_id:{tool.space_id}"
                    new_conv_id = session_data.get(conv_key)
                    if new_conv_id and new_conv_id != tool.conversation_id:
                        tool.conversation_id = new_conv_id
                        updated = True

            if updated:
                from src.core.database import get_db_session
                from src.database.models import UserSession

                with get_db_session() as db:
                    db_session = (
                        db.query(UserSession)
                        .filter(UserSession.session_id == session_id)
                        .first()
                    )
                    if db_session:
                        db_session.agent_config = agent_config.model_dump()

                logger.info(
                    "Persisted per-space conversation_ids to agent_config",
                    extra={
                        "session_id": session_id,
                        "tools_updated": [
                            t.space_id for t in agent_config.tools
                            if isinstance(t, GenieTool) and t.conversation_id
                        ],
                    },
                )
        except Exception as e:
            logger.error(
                f"Failed to persist conversation_ids to agent_config: {e}",
                extra={"session_id": session_id},
            )

    def send_message(
        self,
        session_id: str,
        message: str,
        slide_context: Optional[Dict[str, Any]] = None,
        image_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send a message to the agent and get response.

        Args:
            session_id: Session ID (auto-created if doesn't exist)
            message: User's message
            slide_context: Optional context for slide editing
            image_ids: Optional list of image IDs attached to this message

        Returns:
            Dictionary containing:
                - messages: List of message dicts for UI display
                - slide_deck: Parsed slide deck dict (if generated)
                - metadata: Execution metadata
                - session_id: The session ID used

        Raises:
            Exception: If agent fails to generate slides
        """
        # Inject image context if images are attached
        if image_ids:
            message = self._inject_image_context(message, image_ids)

        logger.info(
            "Processing message",
            extra={
                "message_length": len(message),
                "session_id": session_id,
                "has_slide_context": slide_context is not None,
                "attached_image_ids": image_ids,
            },
        )

        # Get or create session in database (auto-create on first message)
        session_manager = get_session_manager()

        try:
            db_session = session_manager.get_session(session_id)
        except SessionNotFoundError:
            # Auto-create session on first message
            db_session = session_manager.create_session(
                session_id=session_id,
            )
            logger.info(
                "Auto-created session on first message",
                extra={"session_id": session_id},
            )

        # Issue 2 FIX: Detect intent ONCE and store for reuse (sync path)
        _is_edit = self._detect_edit_intent(message)
        _is_generation = self._detect_generation_intent(message)
        _is_add = self._detect_add_intent(message)
        _slide_refs, _ref_position = self._parse_slide_references(message)
        _is_explicit_replace = self._detect_explicit_replace_intent(message)

        # RC10/RC12: Early clarification check BEFORE calling LLM (sync path)
        if not slide_context:
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and len(existing_deck.slides) > 0:
                # RC12: Generation intent with existing deck - ask add or replace
                if _is_generation and not _is_add and not _is_explicit_replace:
                    logger.info(
                        "RC12: Clarification needed - generation intent with existing deck (sync)",
                        extra={"session_id": session_id, "existing_slides": len(existing_deck.slides)},
                    )
                    clarification_msg = (
                        f"You have {len(existing_deck.slides)} slides in this session. "
                        "Would you like to:\n"
                        "- Add new slides to the existing deck?\n"
                        "- Replace the entire deck with a new presentation?\n\n"
                        "Please reply with your full request, e.g., 'add 3 slides about X' or 'replace with new slides about X'."
                    )
                    session_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=clarification_msg,
                        message_type="clarification",
                    )
                    return {
                        "messages": [{
                            "role": "assistant",
                            "content": clarification_msg,
                            "timestamp": datetime.utcnow().isoformat(),
                        }],
                        "slide_deck": existing_deck.to_dict(),
                        "raw_html": existing_deck.knit(),
                        "metadata": {"clarification_needed": True},
                        "replacement_info": None,
                        "session_id": session_id,
                    }

                # RC10: Edit intent without clear target - ask for clarification
                if _is_edit and not _slide_refs and not _is_generation:
                    logger.info(
                        "RC10: Clarification needed - edit intent without slide reference (sync)",
                        extra={"session_id": session_id},
                    )
                    clarification_msg = (
                        "I'd like to help edit your slides. Could you please specify which slide? "
                        "You can either:\n"
                        "- Say the slide number (e.g., 'change slide 3 background to blue')\n"
                        "- Or select the slide from the panel on the left"
                    )
                    session_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=clarification_msg,
                        message_type="clarification",
                    )
                    return {
                        "messages": [{
                            "role": "assistant",
                            "content": clarification_msg,
                            "timestamp": datetime.utcnow().isoformat(),
                        }],
                        "slide_deck": existing_deck.to_dict(),
                        "raw_html": existing_deck.knit(),
                        "metadata": {"clarification_needed": True},
                        "replacement_info": None,
                        "session_id": session_id,
                    }

        # RC13: Auto-create slide_context from text reference (sync path)
        # Runs before agent build so mode can be determined accurately.
        logger.info(
            "RC13: Checking condition (sync)",
            extra={
                "session_id": session_id,
                "_is_edit": _is_edit,
                "_slide_refs": _slide_refs,
                "slide_context_is_none": slide_context is None,
                "slide_context_indices": slide_context.get("indices") if slide_context else None,
                "rc13_will_run": _is_edit and bool(_slide_refs) and not slide_context,
            },
        )
        if _is_edit and _slide_refs and not slide_context:
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and len(existing_deck.slides) > 0:
                valid_refs = [i for i in _slide_refs if 0 <= i < len(existing_deck.slides)]
                if valid_refs:
                    slide_htmls = [existing_deck.slides[i].html for i in valid_refs]
                    slide_context = {
                        "indices": valid_refs,
                        "slide_htmls": slide_htmls
                    }
                    logger.info(
                        "RC13: Auto-created slide_context from text reference (sync)",
                        extra={
                            "session_id": session_id,
                            "parsed_refs": _slide_refs,
                            "valid_refs": valid_refs,
                        },
                    )

        # Build per-request agent with mode-specific prompt
        _mode = "edit" if slide_context else "generate"
        original_genie_id = db_session.get("genie_conversation_id")
        agent, session_data, experiment_url = self._build_agent_for_session(
            session_id, db_session, mode=_mode
        )

        # Capture deck version BEFORE LLM runs so we can detect concurrent edits.
        _deck_version_before_llm = self._get_deck_version(session_id)
        _skip_save_point = False  # Set True only on VersionConflictError

        try:
            # Replace frontend base64 HTML with lightweight backend cache versions
            if slide_context:
                slide_context = self._replace_slide_htmls_from_cache(session_id, slide_context)

            # Call per-request agent to generate slides
            result = agent.generate_slides(
                question=message,
                session_id=session_id,
                slide_context=slide_context,
            )

            # Persist genie_conversation_id if it changed during the request
            self._persist_genie_conversation_ids(session_id, session_data, original_genie_id)

            html_output = result.get("html")
            replacement_info = result.get("replacement_info")

            # Get deck from cache or restore from database (RC6: survive backend restarts)
            current_deck = self._get_or_load_deck(session_id)

            if slide_context and replacement_info:
                # Add position intent for add operations
                if replacement_info.get("is_add_operation"):
                    replacement_info["add_position"] = self._detect_add_position(message)
                slide_deck_dict = self._apply_slide_replacements(
                    replacement_info=result["parsed_output"],
                    session_id=session_id,
                )
                with self._cache_lock:
                    current_deck = self._deck_cache.get(session_id)
                raw_html = current_deck.knit() if current_deck else None
            elif slide_context and not replacement_info:
                # RC3 GUARD: slide_context was provided but parsing failed
                # Preserve existing deck, return error instead of destroying the deck
                logger.error(
                    "Slide replacement parsing failed, preserving existing deck",
                    extra={
                        "session_id": session_id,
                        "slide_context_indices": slide_context.get("indices", []),
                    },
                )
                # Get existing deck to return
                with self._cache_lock:
                    current_deck = self._deck_cache.get(session_id)
                if current_deck:
                    slide_deck_dict = current_deck.to_dict()
                    raw_html = current_deck.knit()
                else:
                    slide_deck_dict = None
                    raw_html = None
                raise ValueError(
                    "Failed to parse LLM response as slide replacements. "
                    "The existing deck has been preserved."
                )
            elif html_output and html_output.strip():
                raw_html = html_output

                try:
                    new_deck = SlideDeck.from_html_string(html_output)
                    
                    # RC2 FIX: Reuse _is_add from early detection (Issue 2 optimization)
                    existing_deck = self._get_or_load_deck(session_id)
                    
                    if _is_add and existing_deck and len(existing_deck.slides) > 0:
                        # ADD new slides to existing deck (at beginning or end)
                        position_type, absolute_position = self._detect_add_position(message)
                        
                        # RC7: Log script status for debugging
                        existing_scripts_info = [
                            {"idx": i, "has_script": bool(s.scripts), "script_len": len(s.scripts or "")}
                            for i, s in enumerate(existing_deck.slides)
                        ]
                        
                        # Determine insert position based on user intent
                        if position_type in ("beginning", "before"):
                            insert_position = 0  # Beginning of deck
                        else:
                            insert_position = len(existing_deck.slides)  # End of deck
                        
                        logger.info(
                            "Add intent detected without slide_context - inserting into deck",
                            extra={
                                "session_id": session_id,
                                "existing_slides": len(existing_deck.slides),
                                "existing_slides_with_scripts": sum(1 for s in existing_deck.slides if s.scripts),
                                "existing_scripts_detail": existing_scripts_info,
                                "new_slides": len(new_deck.slides),
                                "new_slides_with_scripts": sum(1 for s in new_deck.slides if s.scripts),
                                "position_type": position_type,
                                "insert_position": insert_position,
                            },
                        )
                        
                        try:
                            _add_user = get_current_username()
                        except Exception:
                            _add_user = None

                        for idx, slide in enumerate(new_deck.slides):
                            # A NEW slide gets no id here: _reindex_slide_ids
                            # below mints a unique one.  A POSITIONAL id would
                            # collide with a real slide further down the deck
                            # and, being earlier in the list, would WIN the
                            # collision and steal that slide's verdict.
                            slide.slide_id = None
                            if _add_user:
                                slide.stamp_created(_add_user)
                            existing_deck.insert_slide(slide, insert_position + idx)
                        
                        self._reindex_slide_ids(existing_deck)

                        if new_deck.css:
                            existing_deck.css = existing_deck.css + "\n" + new_deck.css

                        current_deck = existing_deck
                        # RC7: Log final script status
                        final_scripts_info = [
                            {"idx": i, "has_script": bool(s.scripts), "script_len": len(s.scripts or "")}
                            for i, s in enumerate(current_deck.slides)
                        ]
                        logger.info(
                            "Added slides to existing deck",
                            extra={
                                "session_id": session_id,
                                "final_slide_count": len(current_deck.slides),
                                "final_slides_with_scripts": sum(1 for s in current_deck.slides if s.scripts),
                                "final_scripts_detail": final_scripts_info,
                            },
                        )
                    else:
                        current_deck = new_deck
                    
                    with self._cache_lock:
                        self._deck_cache[session_id] = current_deck
                    slide_deck_dict = current_deck.to_dict()
                    logger.info(
                        "Parsed slide deck",
                        extra={
                            "slide_count": len(current_deck.slides),
                            "title": current_deck.title,
                            "session_id": session_id,
                        },
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to parse HTML into SlideDeck: {e}",
                        exc_info=True,
                    )
                    with self._cache_lock:
                        self._deck_cache.pop(session_id, None)
                    slide_deck_dict = None
            else:
                raw_html = None
                slide_deck_dict = None

            # Persist slide deck to database
            if current_deck and slide_deck_dict:
                # WB-1 backstop: re-emit the pinned template's token
                # stylesheet when the model dropped it, then rebuild the dict
                # so both persisted representations agree.
                if self._ensure_pinned_template_token_css(session_id, current_deck):
                    slide_deck_dict = current_deck.to_dict()
                try:
                    _user = get_current_username()
                except Exception:
                    _user = None

                # Stamp authorship on every slide that lacks it
                if _user:
                    for slide in current_deck.slides:
                        if not slide.created_by:
                            slide.stamp_created(_user)
                    # Regenerate dict so stamps are included
                    slide_deck_dict = current_deck.to_dict()

                try:
                    save_result = session_manager.save_slide_deck(
                        session_id=session_id,
                        title=current_deck.title,
                        html_content=current_deck.knit(),
                        scripts_content=current_deck.scripts,
                        slide_count=len(current_deck.slides),
                        deck_dict=slide_deck_dict,
                        modified_by=_user,
                        expected_version=_deck_version_before_llm,
                    )
                    self._record_deck_version(session_id, save_result)
                except VersionConflictError:
                    logger.warning(
                        "Chat save rejected: deck was edited during LLM call, reloading",
                        extra={"session_id": session_id},
                    )
                    self._invalidate_deck_cache(session_id)
                    current_deck = self._get_or_load_deck(session_id)
                    if current_deck:
                        slide_deck_dict = current_deck.to_dict()
                    _skip_save_point = True  # manual edit already has its own save point

                # Create save point immediately after persisting (sync path)
                if not _skip_save_point:
                    try:
                        if slide_context:
                            slide_nums = [i + 1 for i in slide_context.get("indices", [])]
                            sp_desc = f"Edited slide {', '.join(map(str, slide_nums))}"
                        else:
                            sp_desc = f"Generated {len(current_deck.slides)} slide(s)"
                        self.create_save_point(
                            session_id=session_id,
                            description=sp_desc,
                            deck=current_deck,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to create save point (sync): {e}")

            # Update session activity
            session_manager.update_last_activity(session_id)

            # RC11: Check for conflict between selection and text reference (sync path)
            conflict_note = None
            text_refs, _ = self._parse_slide_references(message)
            logger.info(
                "RC11: Checking for selection/text conflict (sync)",
                extra={
                    "session_id": session_id,
                    "has_slide_context": slide_context is not None,
                    "slide_context_indices": slide_context.get("indices", []) if slide_context else None,
                    "text_refs": text_refs,
                    "message_preview": message[:100] if message else None,
                },
            )
            if slide_context:
                if text_refs:
                    selected_indices = slide_context.get("indices", [])
                    if set(text_refs) != set(selected_indices):
                        selected_display = [i + 1 for i in selected_indices]
                        text_display = [i + 1 for i in text_refs]
                        conflict_note = (
                            f"📝 Applied changes to slide {', '.join(map(str, selected_display))} (your selection). "
                            f"Note: you mentioned slide {', '.join(map(str, text_display))} in your message."
                        )
                        logger.info(
                            "RC11: Selection/text conflict detected (sync)",
                            extra={"session_id": session_id, "selected": selected_indices, "text_refs": text_refs},
                        )
                        session_manager.add_message(
                            session_id=session_id,
                            role="assistant",
                            content=conflict_note,
                            message_type="info",
                        )
                    else:
                        logger.info(
                            "RC11: No conflict - indices match (sync)",
                            extra={"session_id": session_id, "selected_indices": selected_indices, "text_refs": text_refs},
                        )
                else:
                    logger.info(
                        "RC11: Skipped - no text reference found in message (sync)",
                        extra={"session_id": session_id},
                    )

            # Substitute image placeholders before sending to client
            slide_deck_dict, raw_html = self._substitute_images_for_response(
                slide_deck_dict, raw_html, session_id=session_id
            )

            # Build response. Appended notices need a timestamp — MessageResponse
            # requires it, and omitting it raises a Pydantic ValidationError that
            # surfaces as a 500 with internal detail (AISEC-248 finding #10).
            messages = result["messages"]
            notice_ts = (result.get("metadata") or {}).get("timestamp") or datetime.utcnow().isoformat()
            if conflict_note:
                messages = messages + [
                    {"role": "assistant", "content": conflict_note, "timestamp": notice_ts}
                ]

            # AISEC-248: surface a chat message if the safety gate rebuilt the deck.
            safety_notice = (result.get("metadata") or {}).get("safety_notice")
            if safety_notice:
                session_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=safety_notice,
                    message_type="info",
                )
                messages = messages + [
                    {"role": "assistant", "content": safety_notice, "timestamp": notice_ts}
                ]

            response = {
                "messages": messages,
                "slide_deck": slide_deck_dict,
                "raw_html": raw_html,
                "metadata": result["metadata"],
                "replacement_info": _sanitize_replacement_info(replacement_info),
                "session_id": session_id,
                "experiment_url": experiment_url or result.get("experiment_url"),
            }

            logger.info(
                "Message processed successfully",
                extra={
                    "message_count": len(response["messages"]),
                    "has_slide_deck": response["slide_deck"] is not None,
                    "session_id": session_id,
                    "had_conflict_note": conflict_note is not None,
                },
            )

            return response

        except Exception as e:
            logger.error(f"Failed to process message: {e}", exc_info=True)
            raise

    def send_message_streaming(
        self,
        session_id: str,
        message: str,
        slide_context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        image_ids: Optional[List[str]] = None,
        is_first_message_override: Optional[bool] = None,
        engine_mode: str = "monolith",
    ) -> Generator[StreamEvent, None, None]:
        """Send a message and yield streaming events.

        This method:
        1. Persists the user message to database
        2. Yields streaming events as the agent executes
        3. Processes the final result and yields a complete event

        Args:
            session_id: Session ID (auto-created if doesn't exist)
            message: User's message
            slide_context: Optional context for slide editing
            request_id: Optional request ID for async polling support
            image_ids: Optional list of image IDs attached to this message
            is_first_message_override: If set, overrides the DB-based first-message
                detection. Used by the async path where the user message is
                persisted before the job runs.
            engine_mode: ``"graph"`` runs the turn on the LangGraph engine,
                ``"monolith"`` (the default) on the shipped agent. Resolved by
                the CHAT ROUTES and passed in — never resolved here. The default
                is what keeps MCP on the monolith: MCP reaches this method
                through the same job queue as ``POST /chat/async`` but builds a
                payload with no ``engine_mode`` key.

        Yields:
            StreamEvent objects for real-time display

        Raises:
            Exception: If agent fails to generate slides
        """
        # Inject image context if images are attached
        if image_ids:
            message = self._inject_image_context(message, image_ids)

        logger.info(
            "Processing streaming message",
            extra={
                "message_length": len(message),
                "session_id": session_id,
                "has_slide_context": slide_context is not None,
                "request_id": request_id,
            },
        )

        # Get or create session in database
        session_manager = get_session_manager()

        # Load settings for LLM endpoint (used by run_title_gen below)
        from src.core.settings_db import get_settings
        settings = get_settings()

        try:
            db_session = session_manager.get_session(session_id)
        except SessionNotFoundError:
            db_session = session_manager.create_session(
                session_id=session_id,
            )
            logger.info(
                "Auto-created session on first streaming message",
                extra={"session_id": session_id},
            )

        # Capture first-message flag BEFORE add_message increments the count.
        # The async path pre-persists the user message before the job runs,
        # so the DB count is already incremented; use the override in that case.
        if is_first_message_override is not None:
            is_first_message = is_first_message_override
        else:
            is_first_message = db_session.get("message_count", 0) == 0

        # Persist user message to database FIRST (only if not already done by async endpoint)
        if not request_id:
            user_msg = session_manager.add_message(
                session_id=session_id,
                role="user",
                content=message,
                message_type="user_input",
            )
            logger.info(
                "Persisted user message",
                extra={"session_id": session_id, "message_id": user_msg.get("id")},
            )

        # ws4d D2, seventh edit point — the SSE path RE-RESOLVES here, and only
        # the SSE path.  Resolving a mode in this method is otherwise forbidden
        # (that is what keeps MCP off the graph), so the guard is the whole point
        # of these three lines:
        #
        # `POST /chat/stream` does NOT persist the user message — the block
        # immediately above does it on the route's behalf.  So the streaming
        # route's own resolution necessarily ran BEFORE the deck had any
        # `role='user'` row, and `resolve_engine_mode` fails closed to monolith
        # for a deck with no user turn: turn 1 of a new SSE session ran the
        # monolith however the message read, and turn 2 onward ran the graph.
        # One deck written by both engines is the divergence stickiness exists
        # to prevent.
        #
        # `not request_id` IS the SSE path, structurally:
        # `job_queue._run_streaming_generator` always passes
        # `request_id=request_id`, and `enqueue_job(request_id: str, ...)` types
        # it non-optional and keys `jobs[request_id]` on it — so the async route
        # and MCP can never reach this branch, and neither can ever be
        # re-resolved onto the graph.
        #
        # IDEMPOTENT on turn 2 and after: the resolver reads the deck's EARLIEST
        # `role='user'` row, which the insert above cannot change once one
        # exists.  A re-resolve able to flip an established deck's engine would
        # be worse than the gap it closes.
        #
        # The plan contradicts itself here — D1 asserts the row exists before
        # mode resolution on this path while D0 mandates resolving in the route —
        # so this resolves a plan defect rather than deviating from the plan.
        if not request_id:
            engine_mode = resolve_engine_mode_or(session_id, engine_mode)

        # ws4d D2 — the graph branch.  Placed AFTER the user message is
        # persisted (the resolver upstream reads that row) and BEFORE anything
        # monolith-specific runs, so intent detection, the clarification
        # checks and `_build_agent_for_session` are all skipped on a graph turn
        # and the monolith path below is left byte-identical: it is this PR's
        # comparison baseline.
        #
        # `engine_mode` arrives as a parameter and is never resolved here.  It
        # defaults to "monolith", which is what excludes MCP structurally.
        if engine_mode == "graph":
            logger.info(
                "Routing this turn through the LangGraph engine",
                extra={"session_id": session_id, "request_id": request_id},
            )
            yield from self._send_message_streaming_graph(
                session_id,
                message,
                is_first_message=is_first_message,
                request_id=request_id,
            )
            return

        # Issue 2 FIX: Detect intent ONCE and store for reuse throughout the function
        _is_edit = self._detect_edit_intent(message)
        _is_generation = self._detect_generation_intent(message)
        _is_add = self._detect_add_intent(message)
        _slide_refs, _ref_position = self._parse_slide_references(message)
        _is_explicit_replace = self._detect_explicit_replace_intent(message)

        # RC10: Early clarification check BEFORE calling LLM
        if not slide_context:
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and len(existing_deck.slides) > 0:
                # Generation intent with existing deck - ask add or replace
                if _is_generation and not _is_add and not _is_explicit_replace:
                    logger.info(
                        "RC12: Clarification - generation intent with existing deck",
                        extra={
                            "session_id": session_id,
                            "existing_slides": len(existing_deck.slides),
                            "message_preview": message[:50],
                        },
                    )
                    clarification_msg = (
                        f"You have {len(existing_deck.slides)} slides in this session. "
                        "Would you like to:\n"
                        "- Add new slides to the existing deck?\n"
                        "- Replace the entire deck with a new presentation?\n\n"
                        "Please reply with your full request, e.g., 'add 3 slides about X' or 'replace with new slides about X'."
                    )
                    session_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=clarification_msg,
                        message_type="clarification",
                        request_id=request_id,
                    )
                    yield StreamEvent(
                        type=StreamEventType.ASSISTANT,
                        content=clarification_msg,
                    )
                    early_deck_dict, _ = self._substitute_images_for_response(
                        existing_deck.to_dict(), session_id=session_id
                    )
                    yield StreamEvent(
                        type=StreamEventType.COMPLETE,
                        slides=early_deck_dict,
                        metadata={"clarification_needed": True},
                    )
                    return

                # Edit intent without clear target - ask for clarification
                if _is_edit and not _slide_refs and not _is_generation:
                    logger.info(
                        "RC10: Early clarification - edit intent without slide reference",
                        extra={"session_id": session_id, "message_preview": message[:50]},
                    )
                    clarification_msg = (
                        "I'd like to help edit your slides. Could you please specify which slide? "
                        "You can either:\n"
                        "- Say the slide number (e.g., 'change slide 3 background to blue')\n"
                        "- Or select the slide from the panel on the left"
                    )
                    session_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=clarification_msg,
                        message_type="clarification",
                        request_id=request_id,
                    )
                    yield StreamEvent(
                        type=StreamEventType.ASSISTANT,
                        content=clarification_msg,
                    )
                    early_deck_dict, _ = self._substitute_images_for_response(
                        existing_deck.to_dict(), session_id=session_id
                    )
                    yield StreamEvent(
                        type=StreamEventType.COMPLETE,
                        slides=early_deck_dict,
                        metadata={"clarification_needed": True},
                    )
                    return

        # RC13: Auto-create slide_context from text reference (e.g., "edit slide 7")
        # Runs before agent build so mode can be determined accurately.
        logger.info(
            "RC13: Checking condition",
            extra={
                "session_id": session_id,
                "_is_edit": _is_edit,
                "_slide_refs": _slide_refs,
                "slide_context_is_none": slide_context is None,
                "slide_context_indices": slide_context.get("indices") if slide_context else None,
                "rc13_will_run": _is_edit and bool(_slide_refs) and not slide_context,
            },
        )
        if _is_edit and _slide_refs and not slide_context:
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and len(existing_deck.slides) > 0:
                valid_refs = [i for i in _slide_refs if 0 <= i < len(existing_deck.slides)]
                if valid_refs:
                    slide_htmls = [existing_deck.slides[i].html for i in valid_refs]
                    slide_context = {
                        "indices": valid_refs,
                        "slide_htmls": slide_htmls
                    }
                    logger.info(
                        "RC13: Auto-created slide_context from text reference",
                        extra={
                            "session_id": session_id,
                            "parsed_refs": _slide_refs,
                            "valid_refs": valid_refs,
                            "deck_size": len(existing_deck.slides),
                        },
                    )

        # Build per-request agent with mode-specific prompt
        _mode = "edit" if slide_context else "generate"
        original_genie_id = db_session.get("genie_conversation_id")
        agent, session_data, experiment_url = self._build_agent_for_session(
            session_id, db_session, mode=_mode
        )

        # RC14: Validate slide_context indices against current backend deck state
        if slide_context:
            selected_indices = slide_context.get("indices", [])
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and selected_indices:
                max_index = max(selected_indices)
                if max_index >= len(existing_deck.slides):
                    logger.error(
                        "RC14: Frontend/backend deck state mismatch detected",
                        extra={
                            "session_id": session_id,
                            "selected_indices": selected_indices,
                            "backend_slide_count": len(existing_deck.slides),
                            "max_selected_index": max_index,
                        },
                    )
                    error_msg = (
                        f"⚠️ Deck sync error: You selected slide {max_index + 1}, but only "
                        f"{len(existing_deck.slides)} slide(s) exist in the saved deck. "
                        "This can happen if a previous save failed. "
                        "Please refresh the page to resync your session."
                    )
                    early_deck_dict = existing_deck.to_dict() if existing_deck else None
                    if early_deck_dict:
                        early_deck_dict, _ = self._substitute_images_for_response(
                            early_deck_dict, session_id=session_id
                        )
                    # Include error in metadata for ReplacementFeedback display
                    yield StreamEvent(
                        type=StreamEventType.COMPLETE,
                        slides=early_deck_dict,
                        metadata={"sync_error": error_msg},
                    )
                    return

        # RC11: Detect conflict between selection and text reference
        conflict_note = None
        # Debug: Log RC11 inputs
        logger.info(
            "RC11: Checking for selection/text conflict",
            extra={
                "session_id": session_id,
                "has_slide_context": slide_context is not None,
                "slide_context_indices": slide_context.get("indices", []) if slide_context else None,
                "_slide_refs": _slide_refs,
                "message_preview": message[:100] if message else None,
            },
        )
        if slide_context:
            if _slide_refs:
                selected_indices = slide_context.get("indices", [])
                if set(_slide_refs) != set(selected_indices):
                    selected_display = [i + 1 for i in selected_indices]
                    text_display = [i + 1 for i in _slide_refs]
                    conflict_note = (
                        f"📝 Applied changes to slide {', '.join(map(str, selected_display))} (your selection). "
                        f"Note: you mentioned slide {', '.join(map(str, text_display))} in your message."
                    )
                    logger.info(
                        "RC11: Selection/text reference conflict detected",
                        extra={
                            "session_id": session_id,
                            "selected_indices": selected_indices,
                            "text_refs": _slide_refs,
                        },
                    )
                else:
                    logger.info(
                        "RC11: No conflict - indices match",
                        extra={
                            "session_id": session_id,
                            "selected_indices": selected_indices,
                            "_slide_refs": _slide_refs,
                        },
                    )
            else:
                logger.info(
                    "RC11: Skipped - no text reference found in message",
                    extra={"session_id": session_id},
                )

        # Capture deck version BEFORE LLM runs so we can detect concurrent edits.
        _deck_version_before_llm = self._get_deck_version(session_id)
        _skip_save_point = False  # Set True only on VersionConflictError

        # Replace frontend base64 HTML with lightweight backend cache versions
        if slide_context:
            slide_context = self._replace_slide_htmls_from_cache(session_id, slide_context)

        # Create event queue and callback handler
        event_queue: queue.Queue[StreamEvent] = queue.Queue()
        callback_handler = StreamingCallbackHandler(
            event_queue, session_id, request_id=request_id
        )

        # Run agent in thread and yield events
        result_container: Dict[str, Any] = {}
        error_container: Dict[str, Exception] = {}
        title_container: Dict[str, str] = {}

        # Capture context BEFORE starting thread to preserve user auth
        ctx = contextvars.copy_context()

        def run_agent():
            try:
                result = agent.generate_slides_streaming(
                    question=message,
                    session_id=session_id,
                    callback_handler=callback_handler,
                    slide_context=slide_context,
                )
                result_container["result"] = result
                # Persist genie_conversation_id if it changed during the request
                self._persist_genie_conversation_ids(session_id, session_data, original_genie_id)
            except Exception as e:
                error_container["error"] = e
                callback_handler.event_queue.put(
                    StreamEvent(type=StreamEventType.ERROR, error=str(e))
                )
            finally:
                # Signal completion by putting None
                event_queue.put(None)

        def run_title_gen():
            """Generate a session title in parallel with the main agent."""
            try:
                from databricks_langchain import ChatDatabricks
                from src.core.databricks_client import get_user_client

                from src.core.defaults import DEFAULT_CONFIG
                naming_model = ChatDatabricks(
                    endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
                    max_tokens=50,
                    temperature=0.3,
                    workspace_client=get_user_client(),
                )
                generated_title = generate_session_title(message, naming_model)
                if generated_title:
                    session_manager.rename_session(session_id, generated_title)
                    title_container["title"] = generated_title
                    logger.info(
                        "Auto-named session from first message",
                        extra={
                            "session_id": session_id,
                            "generated_title": generated_title,
                        },
                    )
            except Exception:
                logger.warning(
                    "Failed to auto-name session",
                    extra={"session_id": session_id},
                    exc_info=True,
                )

        # Start agent thread with context preserved for user auth
        agent_thread = threading.Thread(target=lambda: ctx.run(run_agent), daemon=True)
        agent_thread.start()

        # Start title generation in parallel on first message
        # Uses a separate context copy since ctx.run() can only be entered by one thread at a time
        title_thread: Optional[threading.Thread] = None
        if is_first_message:
            title_ctx = contextvars.copy_context()
            title_thread = threading.Thread(target=lambda: title_ctx.run(run_title_gen), daemon=True)
            title_thread.start()

        # Yield events as they arrive
        while True:
            event = event_queue.get()
            if event is None:
                break
            yield event

        # Check for errors
        if "error" in error_container:
            raise error_container["error"]

        # Process final result
        result = result_container.get("result")
        if not result:
            return

        html_output = result.get("html")
        replacement_info = result.get("replacement_info")

        # Get deck from cache or restore from database (RC6: survive backend restarts)
        current_deck = self._get_or_load_deck(session_id)

        slide_deck_dict = None
        raw_html = None

        if slide_context and replacement_info:
            # Add position intent for add operations
            if replacement_info.get("is_add_operation"):
                replacement_info["add_position"] = self._detect_add_position(message)
            slide_deck_dict = self._apply_slide_replacements(
                replacement_info=replacement_info,
                session_id=session_id,
            )
            with self._cache_lock:
                current_deck = self._deck_cache.get(session_id)
            raw_html = current_deck.knit() if current_deck else None
        elif slide_context and not replacement_info:
            # RC3 GUARD: slide_context was provided but parsing failed (streaming path)
            # Preserve existing deck, return error instead of destroying the deck
            logger.error(
                "Slide replacement parsing failed (streaming), preserving existing deck",
                extra={
                    "session_id": session_id,
                    "slide_context_indices": slide_context.get("indices", []),
                },
            )
            with self._cache_lock:
                current_deck = self._deck_cache.get(session_id)
            if current_deck:
                slide_deck_dict = current_deck.to_dict()
                raw_html = current_deck.knit()
            else:
                slide_deck_dict = None
                raw_html = None
            raise ValueError(
                "Failed to parse LLM response as slide replacements. "
                "The existing deck has been preserved."
            )
        elif html_output and html_output.strip():
            raw_html = html_output
            try:
                new_deck = SlideDeck.from_html_string(html_output)
                existing_deck = self._get_or_load_deck(session_id)
                
                # RC8/RC9/RC10: Reuse intent from early detection (Issue 2 optimization)
                # No need to re-detect - use _is_edit, _is_generation, _is_add, _slide_refs, _ref_position
                
                # RC10 GUARD: Edit intent without clear target - ask for clarification
                if _is_edit and not slide_context and existing_deck and len(existing_deck.slides) > 0:
                    if _slide_refs:
                        # RC8: User said "edit slide 8" - create synthetic context
                        # Validate indices
                        valid_refs = [i for i in _slide_refs if 0 <= i < len(existing_deck.slides)]
                        if valid_refs:
                            logger.info(
                                "RC8: Creating synthetic slide_context from parsed reference",
                                extra={
                                    "session_id": session_id,
                                    "parsed_refs": _slide_refs,
                                    "valid_refs": valid_refs,
                                },
                            )
                            # Apply the edit to referenced slides
                            # For now, replace the referenced slides with LLM output
                            for idx, slide_idx in enumerate(valid_refs):
                                if idx < len(new_deck.slides):
                                    existing_deck.slides[slide_idx] = new_deck.slides[idx]
                            self._reindex_slide_ids(existing_deck)
                            current_deck = existing_deck
                            with self._cache_lock:
                                self._deck_cache[session_id] = current_deck
                            slide_deck_dict = current_deck.to_dict()
                            # Skip the rest of the elif block
                            logger.info(
                                "RC8: Applied edit to referenced slides",
                                extra={
                                    "session_id": session_id,
                                    "edited_indices": valid_refs,
                                    "final_count": len(current_deck.slides),
                                },
                            )
                        else:
                            # Invalid slide reference
                            logger.warning(
                                "RC8: Invalid slide reference - indices out of range",
                                extra={
                                    "session_id": session_id,
                                    "parsed_refs": _slide_refs,
                                    "deck_size": len(existing_deck.slides),
                                },
                            )
                            # Preserve deck, don't apply changes
                            current_deck = existing_deck
                            slide_deck_dict = current_deck.to_dict()
                    else:
                        # RC10: Edit intent but no slide reference - preserve deck
                        logger.warning(
                            "RC10: Edit intent without slide reference - preserving deck",
                            extra={
                                "session_id": session_id,
                                "message_preview": message[:50],
                            },
                        )
                        # Keep existing deck, don't replace
                        current_deck = existing_deck
                        slide_deck_dict = current_deck.to_dict()
                
                # RC9: Add with slide reference (e.g., "add after slide 3")
                elif _is_add and _slide_refs and _ref_position and existing_deck and len(existing_deck.slides) > 0:
                    valid_ref = _slide_refs[0] if _slide_refs else -1
                    if 0 <= valid_ref < len(existing_deck.slides):
                        # Calculate insert position
                        if _ref_position == "after":
                            insert_position = valid_ref + 1
                        else:  # "before"
                            insert_position = valid_ref
                        
                        logger.info(
                            "RC9: Adding slide at parsed reference position",
                            extra={
                                "session_id": session_id,
                                "ref_slide": valid_ref + 1,  # 1-based for logging
                                "position": _ref_position,
                                "insert_at": insert_position,
                            },
                        )

                        try:
                            _rc9_user = get_current_username()
                        except Exception:
                            _rc9_user = None
                        
                        for idx, slide in enumerate(new_deck.slides):
                            # A NEW slide gets no id here (see _reindex_slide_ids):
                            # a positional id can impersonate an existing slide.
                            slide.slide_id = None
                            if _rc9_user:
                                slide.stamp_created(_rc9_user)
                            existing_deck.insert_slide(slide, insert_position + idx)
                        
                        self._reindex_slide_ids(existing_deck)
                        
                        if new_deck.css:
                            existing_deck.css = existing_deck.css + "\n" + new_deck.css
                        
                        current_deck = existing_deck
                        with self._cache_lock:
                            self._deck_cache[session_id] = current_deck
                        slide_deck_dict = current_deck.to_dict()
                
                # Standard add intent (at beginning/end) - only if not already handled above
                elif _is_add and existing_deck and len(existing_deck.slides) > 0:
                    # ADD new slides to existing deck (at beginning or end)
                    position_type, absolute_position = self._detect_add_position(message)
                    
                    # RC7: Log script status for debugging
                    existing_scripts_info = [
                        {"idx": i, "has_script": bool(s.scripts), "script_len": len(s.scripts or "")}
                        for i, s in enumerate(existing_deck.slides)
                    ]
                    
                    # Determine insert position based on user intent
                    if position_type in ("beginning", "before"):
                        insert_position = 0  # Beginning of deck
                    else:
                        insert_position = len(existing_deck.slides)  # End of deck
                    
                    logger.info(
                        "Add intent detected without slide_context - inserting into deck",
                        extra={
                            "session_id": session_id,
                            "existing_slides": len(existing_deck.slides),
                            "existing_slides_with_scripts": sum(1 for s in existing_deck.slides if s.scripts),
                            "existing_scripts_detail": existing_scripts_info,
                            "new_slides": len(new_deck.slides),
                            "new_slides_with_scripts": sum(1 for s in new_deck.slides if s.scripts),
                            "position_type": position_type,
                            "insert_position": insert_position,
                        },
                    )

                    try:
                        _stream_add_user = get_current_username()
                    except Exception:
                        _stream_add_user = None
                    
                    for idx, slide in enumerate(new_deck.slides):
                        # A NEW slide gets no id here (see _reindex_slide_ids):
                        # a positional id can impersonate an existing slide.
                        slide.slide_id = None
                        if _stream_add_user:
                            slide.stamp_created(_stream_add_user)
                        existing_deck.insert_slide(slide, insert_position + idx)
                    
                    self._reindex_slide_ids(existing_deck)
                    
                    # Merge CSS if new deck has any
                    if new_deck.css:
                        existing_deck.css = existing_deck.css + "\n" + new_deck.css
                    
                    current_deck = existing_deck
                    # RC7: Log final script status
                    final_scripts_info = [
                        {"idx": i, "has_script": bool(s.scripts), "script_len": len(s.scripts or "")}
                        for i, s in enumerate(current_deck.slides)
                    ]
                    logger.info(
                        "Added slides to existing deck",
                        extra={
                            "session_id": session_id,
                            "final_slide_count": len(current_deck.slides),
                            "final_slides_with_scripts": sum(1 for s in current_deck.slides if s.scripts),
                            "final_scripts_detail": final_scripts_info,
                        },
                    )
                else:
                    # RC10 GUARD: Only replace deck for explicit generation intent
                    if _is_generation or not existing_deck or len(existing_deck.slides) == 0:
                        # Explicit generation or no existing deck - replace is OK
                        current_deck = new_deck
                        logger.info(
                            "Replacing deck (generation intent or no existing deck)",
                            extra={
                                "session_id": session_id,
                                "is_generation": _is_generation,
                                "had_existing_deck": existing_deck is not None,
                            },
                        )
                    else:
                        # GUARD: Not a clear generation, edit, or add - preserve deck
                        logger.warning(
                            "RC10 GUARD: Ambiguous request - preserving existing deck",
                            extra={
                                "session_id": session_id,
                                "message_preview": message[:50],
                                "is_edit": _is_edit,
                                "is_add": _is_add,
                                "is_generation": _is_generation,
                            },
                        )
                        current_deck = existing_deck
                
                with self._cache_lock:
                    self._deck_cache[session_id] = current_deck
                slide_deck_dict = current_deck.to_dict()
            except Exception as e:
                logger.warning(f"Failed to parse HTML into SlideDeck: {e}")
                with self._cache_lock:
                    self._deck_cache.pop(session_id, None)

        # Persist slide deck to database
        if current_deck and slide_deck_dict:
            # WB-1 backstop: re-emit the pinned template's token stylesheet
            # when the model dropped it, then rebuild the dict so both
            # persisted representations agree.
            if self._ensure_pinned_template_token_css(session_id, current_deck):
                slide_deck_dict = current_deck.to_dict()
            try:
                _user = get_current_username()
            except Exception:
                _user = None

            # Stamp authorship on every slide that lacks it
            if _user:
                for slide in current_deck.slides:
                    if not slide.created_by:
                        slide.stamp_created(_user)
                # Regenerate dict so stamps are included
                slide_deck_dict = current_deck.to_dict()

            try:
                save_result = session_manager.save_slide_deck(
                    session_id=session_id,
                    title=current_deck.title,
                    html_content=current_deck.knit(),
                    scripts_content=current_deck.scripts,
                    slide_count=len(current_deck.slides),
                    deck_dict=slide_deck_dict,
                    modified_by=_user,
                    expected_version=_deck_version_before_llm,
                )
                self._record_deck_version(session_id, save_result)
            except VersionConflictError:
                logger.warning(
                    "Chat save rejected: deck was edited during LLM call, reloading",
                    extra={"session_id": session_id},
                )
                self._invalidate_deck_cache(session_id)
                current_deck = self._get_or_load_deck(session_id)
                if current_deck:
                    slide_deck_dict = current_deck.to_dict()
                _skip_save_point = True  # manual edit already has its own save point

            # Create save point immediately after persisting (streaming path)
            if not _skip_save_point:
                try:
                    if slide_context:
                        slide_nums = [i + 1 for i in slide_context.get("indices", [])]
                        sp_desc = f"Edited slide {', '.join(map(str, slide_nums))}"
                    else:
                        sp_desc = f"Generated {len(current_deck.slides)} slide(s)"
                    self.create_save_point(
                        session_id=session_id,
                        description=sp_desc,
                        deck=current_deck,
                    )
                except Exception as e:
                    logger.warning(f"Failed to create save point (streaming): {e}")

        # Update session activity
        session_manager.update_last_activity(session_id)

        # Substitute image placeholders before sending to client
        slide_deck_dict, raw_html = self._substitute_images_for_response(
            slide_deck_dict, raw_html, session_id=session_id
        )

        # RC11: Include conflict note in metadata for ReplacementFeedback display
        complete_metadata = result.get("metadata") or {}
        if conflict_note:
            complete_metadata["conflict_note"] = conflict_note

        # AISEC-248: the safety-gate retry notice is emitted live (mid-stream) via
        # callback_handler.emit_notice during agent execution, so it appears in the
        # correct chat order (HTML attempt 1 → notice → rebuild). Nothing to do here.

        # Yield final complete event with slides and optional conflict note
        yield StreamEvent(
            type=StreamEventType.COMPLETE,
            slides=slide_deck_dict,
            raw_html=raw_html,
            replacement_info=_sanitize_replacement_info(replacement_info),
            metadata=complete_metadata if complete_metadata else None,
            experiment_url=experiment_url or result.get("experiment_url"),
        )

        logger.info(
            "Streaming message completed",
            extra={
                "session_id": session_id,
                "has_slide_deck": slide_deck_dict is not None,
                "had_conflict_note": conflict_note is not None,
            },
        )

        # Collect title generated in parallel (if applicable)
        if title_thread is not None:
            title_thread.join(timeout=10)
            if "title" in title_container:
                yield StreamEvent(
                    type=StreamEventType.SESSION_TITLE,
                    session_title=title_container["title"],
                )

    def _send_message_streaming_graph(
        self,
        session_id: str,
        message: str,
        *,
        is_first_message: bool = False,
        request_id: Optional[str] = None,
    ) -> Generator[StreamEvent, None, None]:
        """Run one turn on the LangGraph engine, yielding events as they arrive.

        The graph limb of :meth:`send_message_streaming` (ws4d D2), reached only
        when the caller resolved ``engine_mode == "graph"``.

        Three things here are load-bearing, and each of the three fails
        SILENTLY when it is dropped — no exception, nothing in the logs:

        **``invoke_graph`` runs in a worker thread.**  It is synchronous and
        blocks until the whole turn completes, so calling it inline would mean
        this generator could yield nothing at all until the deck was finished:
        no event could reach the client as it happened, and incremental slide
        delivery would be impossible by construction.  The thread pushes into
        ``event_queue`` and signals completion with a ``None`` sentinel, which
        is exactly the shape the monolith's ``run_agent`` uses.

        **The context is copied BEFORE the thread is spawned.**  ``contextvars``
        do not cross a bare ``threading.Thread``, so without the copy
        ``get_current_user()`` inside ``invoke_graph`` returns ``None``,
        ``initiated_by`` is ``None``, and every ``session_slides`` row this turn
        INSERTs carries a NULL author.  (An UPDATE would *preserve* the author
        already on the row, so only a fresh INSERT shows the damage.)
        ``copy_context()`` snapshots at SPAWN — anything set after it is
        invisible inside the thread.

        **The title thread takes its OWN copy.**  One ``Context`` object cannot
        be entered by two threads at once, which is why the monolith takes a
        second copy for precisely this thread.

        The queue is created HERE and handed in as ``invoke_graph(emitter=...)``
        rather than installed in the ContextVar directly: ``invoke_graph`` owns
        that var's lifecycle and resets it on every invocation.  A
        ``queue.Queue`` also cannot travel through ``GraphState`` — it is not
        serialisable through the checkpointer, and undeclared state keys are
        silently dropped.

        Args:
            session_id: Session whose deck this turn builds.  Also the
                checkpointer's ``thread_id``.
            message: The user's request, seeded onto ``architect_message`` — the
                ONLY key this path puts in the initial state.  ``GraphState`` is
                an exhaustive contract: an undeclared key would be discarded
                silently, and nothing brand-related is resolved here because
                ``architect_node`` is the sole resolver of the design contract
                and the template bytes.
            is_first_message: Whether to generate a session title this turn.
            request_id: The async transport's ``ChatRequest.request_id``, handed
                to ``invoke_graph`` so a node persisting a chat message tags the
                row with it.  ``GET /chat/poll`` reads assistant text through
                ``get_messages_for_request``, which filters on that column, so
                without it the architect's reply is written but no polling client
                can see it — and polling is the transport the deployed app uses.
                ``None`` on the SSE path, which persists no request row: that
                client is reading the yielded events instead.

        Yields:
            Every ``StreamEvent`` the graph emits, then ``COMPLETE`` carrying
            the deck, then ``SESSION_TITLE`` when a title was generated.
        """
        from src.services.graph.builder import invoke_graph

        session_manager = get_session_manager()

        event_queue: queue.Queue = queue.Queue()
        error_container: Dict[str, Exception] = {}
        title_container: Dict[str, str] = {}

        # Capture context BEFORE starting thread to preserve user auth
        ctx = contextvars.copy_context()

        def run_graph():
            """Run the graph in a separate thread, pushing events to the queue."""
            try:
                invoke_graph(
                    session_id,
                    {"architect_message": message},
                    emitter=event_queue,
                    request_id=request_id,
                )
            except Exception as e:
                logger.error(
                    f"Graph turn failed: {e}",
                    extra={"session_id": session_id},
                    exc_info=True,
                )
                error_container["error"] = e
                event_queue.put(
                    StreamEvent(type=StreamEventType.ERROR, error=str(e))
                )
            finally:
                # Signal completion by putting None
                event_queue.put(None)

        def run_title_gen():
            """Generate a session title in parallel with the graph turn.

            The same step the monolith runs at its own first message.  Without
            it a graph-mode session would stay untitled forever, because the
            graph branch bypasses the monolith entirely.  Failing to name a
            session must never fail the turn, so this catches and logs.
            """
            try:
                from databricks_langchain import ChatDatabricks

                from src.core.databricks_client import get_user_client
                from src.core.defaults import DEFAULT_CONFIG

                naming_model = ChatDatabricks(
                    endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
                    max_tokens=50,
                    temperature=0.3,
                    workspace_client=get_user_client(),
                )
                generated_title = generate_session_title(message, naming_model)
                if generated_title:
                    session_manager.rename_session(session_id, generated_title)
                    title_container["title"] = generated_title
                    logger.info(
                        "Auto-named graph-mode session from first message",
                        extra={
                            "session_id": session_id,
                            "generated_title": generated_title,
                        },
                    )
            except Exception:
                logger.warning(
                    "Failed to auto-name session",
                    extra={"session_id": session_id},
                    exc_info=True,
                )

        # Start the graph thread with context preserved for user auth
        graph_thread = threading.Thread(
            target=lambda: ctx.run(run_graph), daemon=True
        )
        graph_thread.start()

        # Start title generation in parallel on first message.
        # Uses a separate context copy since ctx.run() can only be entered by
        # one thread at a time.
        title_thread: Optional[threading.Thread] = None
        if is_first_message:
            title_ctx = contextvars.copy_context()
            title_thread = threading.Thread(
                target=lambda: title_ctx.run(run_title_gen), daemon=True
            )
            title_thread.start()

        # Yield events as they arrive
        while True:
            event = event_queue.get()
            if event is None:
                break
            yield event

        # Check for errors
        if "error" in error_container:
            raise error_container["error"]

        # The graph wrote session_slides rows behind this process's deck cache,
        # so drop the cached deck rather than serve a deck that predates the turn.
        self._invalidate_deck_cache(session_id)

        # ONE save point per completed turn, matching the monolith — which makes
        # one here too, at `send_message_streaming`'s own post-persist step.
        # Without it a graph-built deck has EMPTY version history: nothing under
        # `src/services/graph/` touches `create_save_point`, `create_version` or
        # `SlideDeckVersion`, against eight call sites in this module.  Same class
        # of silent end-of-turn bypass as the title, and the plan names only the
        # title, so nobody owned it.  Task 6's "restore cancels a pending review"
        # would pass VACUOUSLY on a graph deck that has no versions to restore.
        #
        # PLACEMENT IS LOAD-BEARING: here, after the worker thread has finished
        # and the deck is committed — never inside a node.  Nodes fan out per
        # slide, so a save point in one would mint a version PER SLIDE, and
        # `SessionManager.VERSION_LIMIT` is 40: three turns of a 15-slide deck
        # would exhaust the whole history and start evicting the oldest.
        #
        # A save-point failure must not fail the turn, exactly as on the monolith
        # path — the deck is already committed by the time this runs.
        try:
            deck_for_save_point = self._get_or_load_deck(session_id)
            if deck_for_save_point is not None:
                self.create_save_point(
                    session_id=session_id,
                    description=(
                        f"Generated {len(deck_for_save_point.slides)} slide(s)"
                    ),
                    deck=deck_for_save_point,
                )
        except Exception as e:
            logger.warning(
                f"Failed to create save point (graph): {e}",
                extra={"session_id": session_id},
                exc_info=True,
            )

        yield StreamEvent(
            type=StreamEventType.COMPLETE,
            slides=self.get_slides(session_id),
            metadata={"engine_mode": "graph"},
        )

        logger.info(
            "Graph-mode streaming message completed",
            extra={"session_id": session_id},
        )

        # Collect title generated in parallel (if applicable)
        if title_thread is not None:
            title_thread.join(timeout=10)
            if "title" in title_container:
                yield StreamEvent(
                    type=StreamEventType.SESSION_TITLE,
                    session_title=title_container["title"],
                )

    def clear_context(self, session_id: str) -> Dict[str, Any]:
        """Drop this session's conversation context, keeping the deck and its spec.

        The deck spec is a structured compaction of the conversation: once it
        holds what was decided, the transcript is only the path taken to get
        there.  So clearing drops the transcript and the graph thread, keeps the
        deck and ``deck_spec_json``, and loses nothing that was agreed.

        **The earliest ``role='user'`` row survives.**  Engine mode is derived
        from it (:func:`resolve_engine_mode`), so deleting it would silently
        revert a graph-mode deck to the monolith on the next turn — the two
        halves of this PR would contradict each other.  There is precedent:
        ``restore_version`` also prunes messages selectively, and preserving the
        first user row is safe for that pruning too because it predates every
        save point.  It is preserved unconditionally, in both modes, so clearing
        never *changes* the mode in either direction.

        **The graph thread is deleted** through the repo's own
        ``SqlAlchemyCheckpointSaver.delete_thread``, whose ``thread_id`` is the
        session id ``invoke_graph`` runs under.  ``BaseCheckpointSaver``'s method
        body is ``raise NotImplementedError``, not a no-op, so a saver that
        cannot delete surfaces as a 500 on the route rather than skipping
        quietly.

        **This is not one transaction, and the skew has a direction.**
        ``delete_thread`` opens ``self._session()``
        (``core/checkpointer.py:226``), which **commits on success** — its own
        transaction, committed while this one is still open.  So:

        * a **raise** from ``delete_thread`` propagates out of this ``with``
          block and the transcript prune is rolled back: nothing is lost, and the
          route 500s.  That direction is safe, and it is why the call sits inside
          the block rather than after it;
        * a failure of **this** transaction's commit, after ``delete_thread``
          returned, leaves the graph thread **deleted and the transcript intact**.
          Recoverable rather than corrupting — the next graph turn starts a fresh
          thread and the user can clear again — but it is a real half-state, and
          no ordering of these two writes removes it while they are two
          transactions.  Do not read the placement as atomicity.

        A second consequence of the two connections: the bulk
        ``delete(synchronize_session=False)`` below emits its DELETE immediately,
        so the transcript rows are locked on this connection while the
        checkpointer deletes on another.  Different tables, so there is no
        ordering cycle today; worth not deepening.

        No hidden agent state can survive: every non-architect agent is built
        fresh per invocation and the monolith's history is hydrated from these
        rows.

        Args:
            session_id: The session to clear.  A contributor session clears its
                own transcript; the owner's marker (and so the deck's mode) is
                untouched, because a contributor's rows are its own.

        Returns:
            ``{"status": "cleared", "session_id": ..., "deleted_messages": N,
            "preserved_message_id": id-or-None}``

        Raises:
            SessionNotFoundError: session_id does not exist.
        """
        from src.core.database import get_db_session
        from src.database.models.session import SessionMessage

        session_manager = get_session_manager()
        with get_db_session() as db:
            session = session_manager._get_session_or_raise(db, session_id)

            marker = (
                db.query(SessionMessage)
                .filter(
                    SessionMessage.session_id == session.id,
                    SessionMessage.role == "user",
                )
                .order_by(SessionMessage.created_at.asc(), SessionMessage.id.asc())
                .first()
            )
            marker_id = marker.id if marker is not None else None

            doomed = db.query(SessionMessage).filter(
                SessionMessage.session_id == session.id
            )
            if marker_id is not None:
                doomed = doomed.filter(SessionMessage.id != marker_id)
            deleted_messages = doomed.delete(synchronize_session=False)

            # Inside the transaction on purpose — see the docstring.
            from src.core.checkpointer import get_checkpointer

            get_checkpointer().delete_thread(session_id)

        logger.info(
            "Cleared session context",
            extra={
                "session_id": session_id,
                "deleted_messages": deleted_messages,
                "preserved_message_id": marker_id,
            },
        )

        return {
            "status": "cleared",
            "session_id": session_id,
            "deleted_messages": deleted_messages,
            "preserved_message_id": marker_id,
        }

    def _ensure_user_experiment(
        self, session_id: str, username: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Ensure MLflow experiment exists for this user (one experiment per user).

        Creates an experiment if it doesn't exist, or returns the existing one.
        Experiment path:
        - Production: /Workspace/Users/{SP_CLIENT_ID}/{username}/ai-slide-generator
        - Local dev: /Workspace/Users/{username}/ai-slide-generator

        Args:
            session_id: Session identifier for logging
            username: User's email/username for path and permissions

        Returns:
            Tuple of (experiment_id, experiment_url) or (None, None) on failure
        """
        import os

        import mlflow

        from src.core.mlflow_tracing import (
            configure_tracing_environment,
            create_databricks_experiment,
            get_unity_catalog_trace_location,
        )

        # Determine experiment path based on environment
        sp_folder = get_service_principal_folder()
        
        if sp_folder:
            # Production: use service principal's folder
            experiment_path = f"{sp_folder}/{username}/ai-slide-generator"
        else:
            # Local development: use user's folder
            experiment_path = f"/Workspace/Users/{username}/ai-slide-generator"

        logger.info(
            f"ChatService: Ensuring user MLflow experiment at path: {experiment_path}",
            extra={
                "session_id": session_id,
                "username": username,
                "experiment_path": experiment_path,
                "using_sp_folder": sp_folder is not None,
            },
        )

        try:
            mlflow.set_tracking_uri("databricks")
            configure_tracing_environment()

            # Check if experiment already exists
            experiment = mlflow.get_experiment_by_name(experiment_path)
            
            if experiment:
                experiment_id = experiment.experiment_id
                logger.info(
                    f"Using existing user experiment: {experiment_id}",
                    extra={"session_id": session_id, "experiment_path": experiment_path},
                )
                if get_unity_catalog_trace_location() is not None:
                    logger.warning(
                        "TELLR_MLFLOW_UC_* is set but this experiment already existed; "
                        "UC trace_location only applies to newly created experiments. "
                        "Delete the experiment at %s and run Tellr again to bind UC traces.",
                        experiment_path,
                        extra={"session_id": session_id, "experiment_path": experiment_path},
                    )
            else:
                # Ensure parent folder exists before creating experiment
                # The folder structure is: {sp_folder}/{username}/ai-slide-generator
                # We need to create {sp_folder}/{username}/ first
                if sp_folder:
                    from src.core.databricks_client import ensure_workspace_folder
                    parent_folder = f"{sp_folder}/{username}"
                    try:
                        ensure_workspace_folder(parent_folder)
                    except Exception as e:
                        logger.warning(f"Failed to create parent folder {parent_folder}: {e}")
                        # Continue anyway - experiment creation might still work
                
                # Create new experiment for user (optional Unity Catalog trace location)
                experiment_id = create_databricks_experiment(experiment_path)
                logger.info(
                    f"Created new user experiment: {experiment_id}",
                    extra={"session_id": session_id, "experiment_path": experiment_path},
                )

                # Grant user CAN_MANAGE permission (only needed when using SP folder)
                if sp_folder:
                    self._grant_experiment_permission(experiment_id, username, session_id)

            # Construct experiment URL (ensure https:// prefix for proper linking)
            host = os.getenv("DATABRICKS_HOST", "").rstrip("/")
            if host and not host.startswith("http"):
                host = f"https://{host}"
            experiment_url = f"{host}/ml/experiments/{experiment_id}"

            return experiment_id, experiment_url

        except Exception as e:
            logger.warning(
                f"Failed to ensure user experiment, continuing without MLflow: {e}",
                extra={
                    "session_id": session_id,
                    "experiment_path": experiment_path,
                    "error": str(e),
                },
            )
            return None, None

    def _grant_experiment_permission(
        self, experiment_id: str, username: str, session_id: str
    ) -> None:
        """Grant CAN_MANAGE permission on experiment to user.

        Uses the Databricks SDK to set experiment permissions so users can
        view and manage their session's experiment data.

        Args:
            experiment_id: MLflow experiment ID
            username: User's email/username to grant permission to
            session_id: Session ID for logging context
        """
        from databricks.sdk.service.ml import (
            ExperimentAccessControlRequest,
            ExperimentPermissionLevel,
        )

        try:
            client = get_system_client()
            client.experiments.set_permissions(
                experiment_id=experiment_id,
                access_control_list=[
                    ExperimentAccessControlRequest(
                        user_name=username,
                        permission_level=ExperimentPermissionLevel.CAN_MANAGE,
                    )
                ],
            )
            logger.info(
                "Granted experiment permission",
                extra={
                    "session_id": session_id,
                    "experiment_id": experiment_id,
                    "username": username,
                    "permission": "CAN_MANAGE",
                },
            )
        except Exception as e:
            # Log warning but don't fail - user can still view via SP permissions
            logger.warning(
                f"Failed to grant experiment permission: {e}",
                extra={
                    "session_id": session_id,
                    "experiment_id": experiment_id,
                    "username": username,
                    "error": str(e),
                },
            )

    def _hydrate_chat_history(
        self, session_id: str, chat_history: ChatMessageHistory
    ) -> int:
        """Load messages from database into ChatHistory for agent context.

        This restores the conversation state when resuming a session,
        allowing the agent to maintain context across page reloads.

        Args:
            session_id: Session ID to load messages for
            chat_history: ChatMessageHistory instance to populate

        Returns:
            Number of messages hydrated
        """
        session_manager = get_session_manager()

        try:
            db_messages = session_manager.get_messages(session_id)
        except SessionNotFoundError:
            # Session doesn't exist yet (first message), no history to load
            return 0

        if not db_messages:
            return 0

        count = 0
        # Hydrate only real conversation turns. clarification IS kept — it is an
        # assistant turn the user answers; dropping it regresses "add or replace?"
        # flows. reasoning/info/tool_* are agent-internal noise and must not be
        # replayed to the LLM as turns. (Security note: after the on_llm_end guard
        # above, no *unsafe* HTML is ever persisted as llm_response.)
        HUMAN_TYPES = {"user_query", "user_input", "chat"}
        AI_TYPES = {"llm_response", "clarification"}
        for msg in db_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            mtype = msg.get("message_type", "")
            if not content:
                continue
            if role == "user" and mtype in HUMAN_TYPES:
                chat_history.add_message(HumanMessage(content=content))
                count += 1
            elif role == "assistant" and mtype in AI_TYPES:
                chat_history.add_message(AIMessage(content=content))
                count += 1
            # Skip reasoning / info / tool_call / tool_result — agent-internal noise.

        logger.info(
            "Hydrated chat history from database",
            extra={"session_id": session_id, "message_count": count},
        )

        return count

    def _detect_add_intent(self, message: str) -> bool:
        """Detect if user wants to add a new slide (RC2 fix).
        
        This is used when no slide_context is provided to determine
        if we should append to existing deck vs replace it.
        
        Args:
            message: User's message
            
        Returns:
            True if message indicates adding/inserting a new slide
        """
        add_patterns = [
            r"\badd\b.*\bslide\b",
            r"\binsert\b.*\bslide\b",
            r"\bappend\b.*\bslide\b",
            r"\bnew\s+slide\b",
            r"\bcreate\b.*\bslide\b",
            r"\badd\b.*\bat\s+the\s+(bottom|end|top|beginning)\b",
            r"\bslide\b.*\bat\s+the\s+(bottom|end|top|beginning)\b",
            r"\badd\b.*\b(summary|conclusion|key\s*takeaway|thank\s*you)",
        ]
        
        lower_message = message.lower()
        for pattern in add_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected add slide intent in message",
                    extra={"user_message": message[:50], "matched_pattern": pattern},
                )
                return True
        return False
    
    def _detect_add_position(self, message: str) -> tuple:
        """Detect where the user wants to add the slide.
        
        Returns:
            tuple of (position_type, absolute_position)
            - ("beginning", 0) - Always insert at position 0
            - ("before", None) - Insert before selected slide
            - ("after", None) - Insert after selected slide or at end (default)
        """
        lower_message = message.lower()
        
        # Check for ABSOLUTE beginning (always position 0, ignores selection)
        beginning_patterns = [
            r"\bat\s+the\s+(top|beginning|start|first)\b",
            r"\b(top|beginning|start|first)\s+of\b",
            r"\btitle\s+slide\b.*\b(beginning|start|first)\b",
            r"\b(beginning|start|first)\b.*\btitle\s+slide\b",
        ]
        
        for pattern in beginning_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected 'beginning' position intent - absolute position 0",
                    extra={"user_message": message[:50], "matched_pattern": pattern},
                )
                return ("beginning", 0)
        
        # Check for RELATIVE "before" (before selected slide)
        before_patterns = [
            r"\bbefore\b.*\bslide\b",
            r"\bslide\b.*\bbefore\b",
            r"\bbefore\s+this\b",
        ]
        
        for pattern in before_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected 'before' position intent - relative to selection",
                    extra={"user_message": message[:50], "matched_pattern": pattern},
                )
                return ("before", None)
        
        return ("after", None)

    def _detect_generation_intent(self, message: str) -> bool:
        """Detect if user wants to generate NEW slides (replace deck).
        
        Only explicit generation requests should replace the entire deck.
        
        Returns:
            True if user wants to create new slides from scratch
        """
        generation_patterns = [
            r"\bgenerate\b.*\bslides?\b",
            r"\bcreate\b.*\b(presentation|deck)\b",
            r"\bcreate\b.*\bslides?\b",  # "create slides about X"
            r"\bmake\s+me\b.*\bslides?\b",
            r"\b\d+\s+slides?\s+(about|on|for)\b",  # "5 slides about X"
            r"\bcreate\b.*\b\d+\s+slides?\b",  # "create 3 slides"
            r"\bnew\s+(presentation|deck)\b",
            r"\bbuild\b.*\b(presentation|deck|slides)\b",
            r"\bprepare\b.*\bslides?\b",
        ]
        
        lower_message = message.lower()
        for pattern in generation_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected generation intent",
                    extra={"user_message": message[:50], "matched_pattern": pattern},
                )
                return True
        return False

    def _detect_explicit_replace_intent(self, message: str) -> bool:
        """Detect if user explicitly wants to replace the deck.
        
        Used after clarification to allow deck replacement.
        
        Returns:
            True if user explicitly confirms replacement
        """
        replace_patterns = [
            r"\breplace\b.*\b(deck|slides?|presentation)\b",
            r"\b(deck|slides?|presentation)\b.*\breplace\b",
            r"\bstart\s+fresh\b",
            r"\bstart\s+over\b",
            r"\bnew\s+deck\b",
            r"\bfrom\s+scratch\b",
            r"\byes,?\s*replace\b",
        ]
        
        lower_message = message.lower()
        for pattern in replace_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected explicit replace intent",
                    extra={"user_message": message[:50], "matched_pattern": pattern},
                )
                return True
        return False

    def _detect_edit_intent(self, message: str) -> bool:
        """Detect if user wants to edit/modify existing slides.
        
        Returns:
            True if message indicates editing existing content
        """
        edit_patterns = [
            r"\b(change|edit|modify|update|fix|adjust|replace)\b.*\bslide\b",
            r"\bslide\b.*\b(change|edit|modify|update|fix|adjust|replace)\b",
            r"\b(change|update|modify|fix|replace)\b.*(color|background|title|text|chart|font)",
            r"\bmake\s+slide\b.*\b(bigger|smaller|darker|lighter|brighter)",
            r"\b(change|update|replace)\b.*\bslide\s*\d+",
            r"\bslide\s*\d+\b.*\b(change|edit|modify|update|replace)\b",
        ]
        
        lower_message = message.lower()
        for pattern in edit_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected edit intent",
                    extra={"user_message": message[:50], "matched_pattern": pattern},
                )
                return True
        return False

    def _parse_slide_references(self, message: str) -> tuple:
        """Parse slide number references from message.
        
        Returns:
            tuple of (indices, position)
            - indices: List of 0-based slide indices, or empty list if none found
            - position: 'before', 'after', or None for direct reference
        
        Examples:
            "slide 8" → ([7], None)
            "slides 2-4" → ([1, 2, 3], None)
            "after slide 3" → ([2], "after")
            "before slide 5" → ([4], "before")
        """
        lower_message = message.lower()
        indices = []
        position = None
        
        # Check for "after slide X" pattern
        after_match = re.search(r"\bafter\s+slide\s*#?(\d+)\b", lower_message)
        if after_match:
            slide_num = int(after_match.group(1))
            return ([slide_num - 1], "after")  # Convert to 0-based
        
        # Check for "before slide X" pattern
        before_match = re.search(r"\bbefore\s+slide\s*#?(\d+)\b", lower_message)
        if before_match:
            slide_num = int(before_match.group(1))
            return ([slide_num - 1], "before")  # Convert to 0-based
        
        # Check for range "slides 2-4" or "slides 2 to 4"
        range_match = re.search(r"\bslides?\s*(\d+)\s*[-–to]+\s*(\d+)\b", lower_message)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            indices = [i - 1 for i in range(start, end + 1)]  # Convert to 0-based
            return (indices, None)
        
        # Check for single "slide 8" or "slide #8"
        single_match = re.search(r"\bslide\s*#?(\d+)\b", lower_message)
        if single_match:
            slide_num = int(single_match.group(1))
            return ([slide_num - 1], None)  # Convert to 0-based
        
        # Check for ordinal "8th slide"
        ordinal_match = re.search(r"\b(\d+)(?:st|nd|rd|th)\s+slide\b", lower_message)
        if ordinal_match:
            slide_num = int(ordinal_match.group(1))
            return ([slide_num - 1], None)  # Convert to 0-based
        
        return ([], None)

    def _inject_image_context(self, message: str, image_ids: List[str]) -> str:
        """Append image metadata to user message so the agent knows about attached images.

        ``image_ids`` are opaque image tokens (SDR-4437 F-TM-7), not int PKs.
        """
        from src.core.database import get_db_session
        from src.services import image_service

        image_descriptions = []
        with get_db_session() as db:
            for img_token in image_ids:
                try:
                    img = db.query(image_service.ImageAsset).filter(
                        image_service.ImageAsset.token == img_token,
                        image_service.ImageAsset.is_active == True,
                    ).first()
                    if img:
                        image_descriptions.append(
                            f'- Image ID {img.token}: "{img.original_filename}" '
                            f'({img.description or "no description"}). '
                            f'Use: <img src="{{{{image:{img.token}}}}}" alt="{img.description or img.original_filename}" />'
                        )
                except Exception as e:
                    logger.warning(f"Failed to load image {img_token} for context injection: {e}")

        if not image_descriptions:
            return message

        context = "\n\n[Attached images]\n" + "\n".join(image_descriptions)
        return message + context

    def _resolve_pinned_template_token_css(self, session_id: str) -> Optional[str]:
        """Token stylesheet of the session's pinned template, or ``None``.

        Mirrors ``agent_factory._get_prompt_content``'s resolution: the
        session's agent_config names the design system + template pin, the
        active DesignSystem row owns the template. Any miss (no pin, inactive
        system, stale template id) resolves to ``None`` — the guarantee only
        applies where a pin actually supplied a token stylesheet.
        """
        session_manager = get_session_manager()
        session = session_manager.get_session(session_id)
        config = resolve_agent_config(session.get("agent_config"))
        if config.design_system_id is None or config.template_id is None:
            return None

        from src.core.database import get_db_session
        from src.database.models import DesignSystem
        from src.services.design_system_templates import get_template_for_generation

        with get_db_session() as db:
            design_system = (
                db.query(DesignSystem)
                .filter_by(id=config.design_system_id, is_active=True)
                .first()
            )
            if design_system is None:
                return None
            template = get_template_for_generation(design_system, config.template_id)
            if template is None:
                return None
            return (getattr(template, "token_css", None) or "").strip() or None

    def _ensure_pinned_template_token_css(self, session_id: str, deck: SlideDeck) -> bool:
        """Deterministic WB-1 backstop, applied right before every deck save.

        The pinned-template prompt block ASKS the model to carry the TOKEN
        STYLESHEET into the deck CSS; the live battery proved it can refuse
        (57 var() references, zero definitions — washout in preview and both
        PPTX paths). When the session pins a template and the deck CSS lost
        the template's token definitions, they are re-emitted into
        ``deck.css`` (see ``ensure_deck_token_css``). Returns True when the
        deck changed so callers can rebuild derived representations. Never
        raises — a failed guarantee must not block saving the deck.
        """
        try:
            token_css = self._resolve_pinned_template_token_css(session_id)
            if not token_css:
                return False

            from src.services.design_system_templates import ensure_deck_token_css

            ensured = ensure_deck_token_css(deck.css, token_css)
            if ensured == (deck.css or ""):
                return False
            deck.css = ensured
            logger.info(
                "Re-emitted pinned template token stylesheet into deck CSS "
                "(model omitted its definitions)",
                extra={"session_id": session_id},
            )
            return True
        except Exception:
            logger.exception(
                "Token-css guarantee failed; saving deck unchanged",
                extra={"session_id": session_id},
            )
            return False

    def _deck_versions(self) -> Dict[str, int]:
        """Return the cached-deck version map, creating it if needed.

        Lazy creation keeps instances built without __init__ (test harnesses
        use ChatService.__new__) working. Callers must hold _cache_lock.
        """
        try:
            return self._deck_cache_versions
        except AttributeError:
            self._deck_cache_versions = {}
            return self._deck_cache_versions

    def _record_deck_version(self, session_id: str, save_result: Optional[Dict[str, Any]]) -> None:
        """Remember which DB version the cached deck now corresponds to.

        Call after save_slide_deck so the next _get_or_load_deck cache hit
        validates cleanly instead of reloading from the database.
        """
        version = (save_result or {}).get("version")
        with self._cache_lock:
            if version is not None:
                self._deck_versions()[session_id] = version
            else:
                self._deck_versions().pop(session_id, None)

    def _get_or_load_deck(self, session_id: str) -> Optional[SlideDeck]:
        """Get deck from cache or load from database.

        Thread-safe access to deck cache using _cache_lock.

        The cache is per-process while prod runs multiple uvicorn workers
        sharing one database, so a cached deck is only served if its recorded
        version matches the current DB version; otherwise it is reloaded.

        Uses deck_dict (slides array with individual scripts) when available,
        falling back to from_html_string for legacy data.
        """
        # Check cache first (with lock)
        with self._cache_lock:
            cached_deck = self._deck_cache.get(session_id)
            cached_version = self._deck_versions().get(session_id)

        if cached_deck is not None:
            db_version = self._get_deck_version(session_id)
            if db_version is None or cached_version == db_version:
                return cached_deck
            logger.info(
                "Deck cache stale, reloading from database",
                extra={
                    "session_id": session_id,
                    "cached_version": cached_version,
                    "db_version": db_version,
                },
            )
            with self._cache_lock:
                self._deck_cache.pop(session_id, None)
                self._deck_versions().pop(session_id, None)

        # Try to load from database (outside lock to avoid blocking)
        session_manager = get_session_manager()
        deck_data = session_manager.get_slide_deck(session_id)

        if not deck_data:
            return None
            
        try:
            # Prefer reconstructing from slides array (preserves individual scripts)
            if deck_data.get("slides"):
                deck = self._reconstruct_deck_from_dict(deck_data)
                logger.info(
                    "Loaded deck from database using slides array",
                    extra={
                        "session_id": session_id,
                        "slide_count": len(deck.slides),
                        "slides_with_scripts": sum(1 for s in deck.slides if s.scripts),
                    },
                )
            elif deck_data.get("html_content"):
                # Fallback: parse from raw HTML (may lose scripts due to IIFE parsing)
                deck = SlideDeck.from_html_string(deck_data["html_content"])
                logger.warning(
                    "Loaded deck from database using HTML fallback (scripts may be lost)",
                    extra={"session_id": session_id},
                )
            else:
                return None
                
            # Store in cache (with lock)
            with self._cache_lock:
                self._deck_cache[session_id] = deck
                if deck_data.get("version") is not None:
                    self._deck_versions()[session_id] = deck_data["version"]
                else:
                    self._deck_versions().pop(session_id, None)
            return deck
        except Exception as e:
            logger.warning(f"Failed to load deck from database: {e}")

        return None

    def _get_deck_version(self, session_id: str) -> Optional[int]:
        """Read the current deck version from the database.

        Used on every deck-cache hit (multi-worker cache validation) and
        before LLM calls (optimistic locking), so it must stay cheap: a
        single-column indexed lookup, never a full deck fetch.

        Returns:
            Current deck version number, or None if no deck exists.
        """
        session_manager = get_session_manager()
        try:
            return session_manager.get_slide_deck_version(session_id)
        except Exception:
            return None

    @staticmethod
    def _reindex_slide_ids(deck: "SlideDeck") -> None:
        """Ensure every slide has a UNIQUE slide_id, without taking one away.

        Must be called after ANY operation that changes the slide list
        (add, delete, reorder, duplicate, replace).

        UNIQUENESS IS THE INVARIANT.  SEQUENTIALITY WAS INCIDENTAL DAMAGE.
        -----------------------------------------------------------------
        This used to assign ``f"slide_{idx}"`` to every slide unconditionally, and
        that one line defeated ``slide_id`` as identity everywhere downstream:

        * ``session_manager._attribute_slide_records`` resolves which verdict and
          which spec fragment belong to each slide by ``slide_id`` FIRST, documented
          as "durable per-slide identity".  With positional ids on both sides of the
          comparison, matching by identity WAS matching by position, so pass 3's
          "unclaimed" guard — the whole of the F1/F2 fix — never ran and a reorder
          handed slide A's verdict to slide B.  Measured end to end through
          ``PUT /api/slides/reorder``: the HTML moved and the verdicts did not.
        * ``SlideViewer.tsx`` keys its verification Map AND its per-slide staleness
          Set on ``slide_id`` precisely "so deck mutations (delete, reorder) cannot
          shift the index → result mapping"; ``AppLayout.tsx`` matches slides across
          deck versions with ``findIndex(s => s.slide_id === ...)``.  Rewriting the
          ids reshuffled the frontend's own state too.

        Nothing in ``src/`` or ``frontend/src`` parses an index out of a slide_id, so
        the positional FORM was never load-bearing.  What is load-bearing is
        uniqueness — this function's original stated purpose (no duplicate React
        keys), plus ``ThumbnailRibbon.tsx``'s use of the id as the dnd-kit sortable
        item id, where a collision breaks drag-and-drop outright.

        So: preserve an id a slide already has, and mint a fresh uuid4 ONLY where one
        is missing, blank, or already taken by an earlier slide in this deck.  Ids
        that merely LOOK positional (``SlideDeck.from_html_string`` assigns
        ``slide_<idx>`` to freshly parsed slides) are left alone — they are unique,
        and once they stop being rewritten they bind to their slide and become real
        identities.
        """
        seen: set = set()
        for slide in deck.slides:
            slide_id = (slide.slide_id or "").strip()
            if not slide_id or slide_id in seen:
                # Missing, blank, or a collision (a clone carries its source's id):
                # this slide needs an identity of its own.
                slide_id = str(uuid.uuid4())
            slide.slide_id = slide_id
            seen.add(slide_id)

    def _invalidate_deck_cache(self, session_id: str) -> None:
        """Remove the cached deck for a session so the next read hits the DB."""
        with self._cache_lock:
            self._deck_cache.pop(session_id, None)
            self._deck_versions().pop(session_id, None)

    def _replace_slide_htmls_from_cache(self, session_id: str, slide_context: Dict[str, Any]) -> Dict[str, Any]:
        """Replace frontend-supplied slide_htmls with backend cache versions.

        The frontend has base64-substituted HTML (needed for rendering). The backend
        cache has {{image:ID}} placeholders (lightweight). We use the cache versions
        for the LLM prompt to avoid sending megabytes of base64 to the model.
        """
        indices = slide_context.get("indices", [])
        if not indices:
            return slide_context

        deck = self._get_or_load_deck(session_id)
        if not deck:
            return slide_context

        cache_htmls = []
        for i in indices:
            if 0 <= i < len(deck.slides):
                cache_htmls.append(deck.slides[i].html)
            else:
                # Index out of range — keep frontend HTML as fallback
                frontend_htmls = slide_context.get("slide_htmls", [])
                idx_in_list = indices.index(i)
                if idx_in_list < len(frontend_htmls):
                    cache_htmls.append(frontend_htmls[idx_in_list])

        if cache_htmls:
            slide_context = {**slide_context, "slide_htmls": cache_htmls}

        return slide_context

    def _reconstruct_deck_from_dict(self, deck_data: Dict[str, Any]) -> SlideDeck:
        """Reconstruct SlideDeck from stored dict (preserves individual slide scripts).

        Args:
            deck_data: Dictionary from get_slide_deck with slides array

        Returns:
            Reconstructed SlideDeck with proper per-slide scripts and metadata
        """
        return SlideDeck.from_dict(deck_data)

    def reload_deck_from_database(self, session_id: str) -> Optional[SlideDeck]:
        """Force reload deck from database (clears cache first).

        Used after restoring a version to ensure cache is updated.

        Args:
            session_id: Session to reload deck for

        Returns:
            Reloaded SlideDeck or None if not found
        """
        # Clear cache for this session
        with self._cache_lock:
            if session_id in self._deck_cache:
                del self._deck_cache[session_id]

        # Reload from database
        return self._get_or_load_deck(session_id)

    def create_save_point(
        self,
        session_id: str,
        description: str,
        deck: Optional[SlideDeck] = None,
    ) -> Dict[str, Any]:
        """Create a save point for the current deck state.

        Args:
            session_id: Session to create save point for
            description: Auto-generated description of the change
            deck: Optional deck to save (uses cached deck if not provided)

        Returns:
            Version info dictionary
        """
        if deck is None:
            deck = self._get_or_load_deck(session_id)

        if not deck:
            raise ValueError("No slide deck available to save")

        session_manager = get_session_manager()

        # Get current verification map
        verification_map = session_manager.get_verification_map(session_id)

        # Create the version
        version_info = session_manager.create_version(
            session_id=session_id,
            description=description,
            deck_dict=deck.to_dict(),
            verification_map=verification_map,
        )

        logger.info(
            "Created save point",
            extra={
                "session_id": session_id,
                "version_number": version_info.get("version_number"),
                "description": description,
            },
        )

        return version_info

    def _apply_slide_replacements(
        self,
        replacement_info: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Apply slide replacements to the session's slide deck.

        Handles variable-length replacements by removing the original block
        and inserting the new Slide objects at the same start index.
        
        For add operations (RC2), new slides are appended without removing originals.
        
        Scripts are attached directly to Slide objects, so when a slide
        is removed its scripts go with it automatically.

        Args:
            replacement_info: Information about the replacement operation
                - replacement_slides: List of Slide objects (with scripts attached)
                - replacement_css: Optional CSS to merge
                - start_index, original_count: Position info
                - is_add_operation: (RC2) Whether this is an add operation
            session_id: Session ID
        """
        current_deck = self._get_or_load_deck(session_id)

        if current_deck is None:
            raise ValueError("No current deck to apply replacements to")

        start_idx = replacement_info["start_index"]
        original_count = replacement_info["original_count"]
        replacement_slides: List[Slide] = replacement_info["replacement_slides"]
        is_add_operation = replacement_info.get("is_add_operation", False)

        # Resolve current user for authorship stamping
        try:
            _user = get_current_username()
        except Exception:
            _user = None

        # RC2: For add operations, insert at appropriate position
        if is_add_operation:
            # Get position intent from replacement_info
            # Format: (position_type, absolute_position) or legacy string
            add_position_info = replacement_info.get("add_position", ("after", None))

            # Handle legacy string format for backward compatibility
            if isinstance(add_position_info, str):
                add_position_info = (add_position_info, None)

            position_type, absolute_position = add_position_info

            # STATE MISMATCH DETECTION: Check if frontend selection is valid for backend deck
            # This can happen if a previous save failed and frontend/backend are out of sync
            state_mismatch = start_idx >= len(current_deck.slides)
            if state_mismatch and start_idx >= 0:
                logger.warning(
                    "DECK STATE MISMATCH: Frontend selected index exceeds backend deck size",
                    extra={
                        "session_id": session_id,
                        "frontend_selected_index": start_idx,
                        "backend_slide_count": len(current_deck.slides),
                        "position_type": position_type,
                        "recommendation": "Frontend and backend decks may be out of sync. "
                                          "User should refresh to resync state.",
                    },
                )

            if position_type == "beginning":
                # ABSOLUTE position 0 (ignores selection)
                insert_position = 0
            elif position_type == "before":
                # Insert BEFORE selected slide, or at beginning if no selection/invalid index
                if start_idx >= 0 and start_idx < len(current_deck.slides):
                    insert_position = start_idx
                else:
                    # Fallback: insert at beginning, but log this as unexpected
                    insert_position = 0
                    if start_idx > 0:  # User had selected a slide but it's out of range
                        logger.warning(
                            "Add 'before' fallback to position 0 due to invalid start_index",
                            extra={
                                "session_id": session_id,
                                "start_idx": start_idx,
                                "deck_size": len(current_deck.slides),
                            },
                        )
            else:
                # Insert AFTER selected slide, or at end if no selection/invalid index
                if start_idx >= 0 and start_idx < len(current_deck.slides):
                    insert_position = start_idx + max(original_count, 1)
                else:
                    # Fallback: insert at end, but log this as unexpected
                    insert_position = len(current_deck.slides)
                    if start_idx > 0:  # User had selected a slide but it's out of range
                        logger.warning(
                            "Add 'after' fallback to end of deck due to invalid start_index",
                            extra={
                                "session_id": session_id,
                                "start_idx": start_idx,
                                "deck_size": len(current_deck.slides),
                            },
                        )
            
            logger.info(
                "Add operation detected - inserting slides",
                extra={
                    "session_id": session_id,
                    "current_slide_count": len(current_deck.slides),
                    "new_slides_count": len(replacement_slides),
                    "insert_position": insert_position,
                    "position_type": position_type,
                    "selected_start_idx": start_idx,
                    "original_count": original_count,
                },
            )
            
            # Insert new slides at the calculated position
            for idx, slide in enumerate(replacement_slides):
                # A NEW slide gets no id here (see _reindex_slide_ids):
                # a positional id can impersonate an existing slide.
                slide.slide_id = None
                if _user:
                    slide.stamp_created(_user)
                current_deck.insert_slide(slide, insert_position + idx)
                logger.info(
                    "Inserted new slide (add operation)",
                    extra={"slide_index": insert_position + idx, "session_id": session_id},
                )
            
            self._reindex_slide_ids(current_deck)
            
            # Merge CSS if provided
            new_css = replacement_info.get("replacement_css", "")
            if new_css:
                current_deck.css = current_deck.css + "\n" + new_css
            
            # Update cache and return
            with self._cache_lock:
                self._deck_cache[session_id] = current_deck
            
            logger.info(
                "Add operation completed successfully",
                extra={
                    "session_id": session_id,
                    "final_slide_count": len(current_deck.slides),
                },
            )
            
            return current_deck.to_dict()

        # Standard replacement logic (non-add operations)
        # Validate replacement range
        if start_idx < 0 or start_idx >= len(current_deck.slides):
            raise ValueError(f"Start index {start_idx} out of range")
        if start_idx + original_count > len(current_deck.slides):
            raise ValueError("Replacement range exceeds deck size")

        # Capture original authorship before removal so replacements inherit it
        original_authors = []
        # The identities being replaced, captured index-wise alongside the authors and
        # for the same reason: a REPLACEMENT of slide N is an edit of slide N, so it
        # must carry slide N's identity forward.  Losing it orphans that slide's
        # verdict, its spec fragment and the frontend's per-slide staleness flag —
        # which is the whole point of the id being durable.
        original_slide_ids = []
        for i in range(original_count):
            orig = current_deck.slides[start_idx + i]
            original_authors.append({
                "created_by": orig.created_by,
                "created_at": orig.created_at,
            })
            original_slide_ids.append(orig.slide_id)

        # Preserve scripts from original slides before removal
        # Map canvas IDs to their scripts for later re-attachment
        canvas_id_to_script: Dict[str, str] = {}
        for i in range(original_count):
            original_slide = current_deck.slides[start_idx + i]
            if original_slide.scripts:
                # Extract canvas IDs from original slide HTML
                original_canvas_ids = extract_canvas_ids_from_html(original_slide.html)
                # Split scripts by canvas and map to canvas IDs
                script_segments = split_script_by_canvas(original_slide.scripts)
                for segment_text, segment_canvas_ids in script_segments:
                    for canvas_id in segment_canvas_ids:
                        if canvas_id in original_canvas_ids:
                            # Store script for this canvas ID
                            if canvas_id not in canvas_id_to_script:
                                canvas_id_to_script[canvas_id] = ""
                            canvas_id_to_script[canvas_id] += segment_text.strip() + "\n"

        # Remove original slides (scripts go with them automatically)
        for _ in range(original_count):
            current_deck.remove_slide(start_idx)

        logger.info(
            "Removed slides for replacement",
            extra={"count": original_count, "start_index": start_idx},
        )

        # Insert replacement slides and preserve scripts if canvas IDs match
        for idx, slide in enumerate(replacement_slides):
            # Update slide_id to reflect new position
            # Carry the replaced slide's identity forward; a replacement beyond the
            # originals is a genuinely new slide, so it gets no id here and
            # _reindex_slide_ids mints a unique one below.  NEVER a positional id:
            # that can collide with a real slide and, winning the collision by being
            # earlier in the list, steal its verdict and spec fragment.
            slide.slide_id = (
                original_slide_ids[idx] if idx < len(original_slide_ids) else None
            )

            # Preserve original creator, stamp current user as modifier
            if idx < len(original_authors):
                slide.created_by = original_authors[idx]["created_by"]
                slide.created_at = original_authors[idx]["created_at"]
            if _user:
                slide.stamp_modified(_user)
                if not slide.created_by:
                    slide.stamp_created(_user)
            
            # Extract canvas IDs from replacement slide HTML
            replacement_canvas_ids = extract_canvas_ids_from_html(slide.html)
            
            # Extract canvas IDs that replacement scripts reference
            replacement_script_canvas_ids = set()
            if slide.scripts:
                script_segments = split_script_by_canvas(slide.scripts)
                for _, segment_canvas_ids in script_segments:
                    replacement_script_canvas_ids.update(segment_canvas_ids)
            
            # Preserve original scripts for canvas IDs that exist in replacement but aren't in replacement scripts
            # RC15: Handle RC4 dedup suffix - try exact match first, then base ID fallback
            preserved_count = 0
            for canvas_id in replacement_canvas_ids:
                if canvas_id in replacement_script_canvas_ids:
                    # Script already provided for this canvas - skip preservation
                    continue
                
                script_to_preserve = None
                matched_id = None
                old_canvas_id = None  # Track the old ID for script update
                
                # 1. Try exact match first (normal case)
                if canvas_id in canvas_id_to_script:
                    script_to_preserve = canvas_id_to_script[canvas_id]
                    matched_id = canvas_id
                else:
                    # 2. Fallback: try without RC4 dedup suffix (optimize case)
                    # RC4 adds suffix like _a1b2c3 (6 hex chars)
                    base_id = re.sub(r'_[a-f0-9]{6}$', '', canvas_id)
                    if base_id != canvas_id and base_id in canvas_id_to_script:
                        script_to_preserve = canvas_id_to_script[base_id]
                        matched_id = f"{base_id} (base of {canvas_id})"
                        old_canvas_id = base_id  # Need to update script references
                
                if script_to_preserve:
                    # RC15: Update canvas ID references in script if they changed
                    if old_canvas_id and old_canvas_id != canvas_id:
                        # Update getElementById calls
                        script_to_preserve = re.sub(
                            rf"getElementById\s*\(\s*['\"]({re.escape(old_canvas_id)})['\"]\s*\)",
                            f"getElementById('{canvas_id}')",
                            script_to_preserve,
                        )
                        # Update querySelector calls
                        script_to_preserve = re.sub(
                            rf"querySelector\s*\(\s*['\"]#({re.escape(old_canvas_id)})['\"]\s*\)",
                            f"querySelector('#{canvas_id}')",
                            script_to_preserve,
                        )
                        logger.info(
                            "Updated canvas ID references in preserved script",
                            extra={"old_id": old_canvas_id, "new_id": canvas_id},
                        )
                    
                    if not slide.scripts:
                        slide.scripts = ""
                    slide.scripts += script_to_preserve
                    preserved_count += 1
                    logger.info(
                        "Preserved script for canvas",
                        extra={"canvas_id": matched_id, "slide_index": start_idx + idx},
                    )
            
            if preserved_count > 0:
                logger.info(
                    "Preserved scripts for replacement slide",
                    extra={
                        "slide_index": start_idx + idx,
                        "preserved_count": preserved_count,
                    },
                )
            
            current_deck.insert_slide(slide, start_idx + idx)

        # Re-index ALL slide IDs after replacement (prevents duplicate React keys)
        self._reindex_slide_ids(current_deck)

        logger.info(
            "Inserted replacement slides",
            extra={
                "replacement_count": len(replacement_slides),
                "net_change": len(replacement_slides) - original_count,
                "start_index": start_idx,
            },
        )

        # Merge replacement CSS into deck
        replacement_css = replacement_info.get("replacement_css", "")
        if replacement_css:
            current_deck.update_css(replacement_css)
            logger.info(
                "Merged replacement CSS",
                extra={"css_length": len(replacement_css)},
            )

        # Update cache (thread-safe)
        with self._cache_lock:
            self._deck_cache[session_id] = current_deck

        return current_deck.to_dict()

    def get_slides(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get slide deck for a session with verification merged.

        Uses session_manager.get_slide_deck() to ensure:
        - Verification is merged from verification_map by content hash
        - content_hash is added to each slide for frontend auto-verify

        Args:
            session_id: Session ID

        Returns:
            Slide deck dictionary with content_hash and verification, or None
        """
        from src.api.services.session_manager import get_session_manager
        
        session_manager = get_session_manager()
        try:
            # Use session_manager to get deck with verification merged
            deck_dict = session_manager.get_slide_deck(session_id)
            if deck_dict and deck_dict.get("slides"):
                deck_dict, _ = self._substitute_images_for_response(
                    deck_dict, session_id=session_id
                )
                return deck_dict
        except Exception as e:
            logger.warning(f"Failed to load deck from session_manager: {e}")

        # Fallback to internal cache (without verification/content_hash)
        deck = self._get_or_load_deck(session_id)
        if not deck:
            return None
        deck_dict = deck.to_dict()
        # Include version from DB even in fallback path (needed for frontend version gating)
        try:
            sm = get_session_manager()
            db_deck = sm.get_slide_deck(session_id)
            if db_deck and "version" in db_deck:
                deck_dict["version"] = db_deck["version"]
        except Exception:
            deck_dict.setdefault("version", 0)
        deck_dict, _ = self._substitute_images_for_response(deck_dict, session_id=session_id)
        return deck_dict

    def reorder_slides(self, session_id: str, new_order: List[int], *, expected_version: Optional[int] = None) -> Dict[str, Any]:
        """Reorder slides based on new index order.

        Args:
            session_id: Session ID
            new_order: List of indices in new order (e.g. [2, 0, 1])

        Returns:
            Updated slide deck

        Raises:
            ValueError: If no slide deck exists or invalid reorder
        """
        current_deck = self._get_or_load_deck(session_id)
        if not current_deck:
            raise ValueError("No slide deck available")

        # Validate indices with detailed logging
        expected_indices = set(range(len(current_deck.slides)))
        received_indices = set(new_order)
        
        if len(new_order) != len(current_deck.slides):
            logger.warning(
                "Reorder validation failed: wrong count",
                extra={
                    "session_id": session_id,
                    "deck_slide_count": len(current_deck.slides),
                    "new_order_count": len(new_order),
                    "new_order": new_order,
                },
            )
            raise ValueError(f"Invalid reorder: wrong number of indices (got {len(new_order)}, expected {len(current_deck.slides)})")

        if received_indices != expected_indices:
            logger.warning(
                "Reorder validation failed: invalid indices",
                extra={
                    "session_id": session_id,
                    "deck_slide_count": len(current_deck.slides),
                    "expected_indices": list(expected_indices),
                    "received_indices": list(received_indices),
                    "missing": list(expected_indices - received_indices),
                    "extra": list(received_indices - expected_indices),
                },
            )
            raise ValueError(f"Invalid reorder: invalid indices (missing: {expected_indices - received_indices}, extra: {received_indices - expected_indices})")

        # Reorder slides
        new_slides = [current_deck.slides[i] for i in new_order]
        current_deck.slides = new_slides

        self._reindex_slide_ids(current_deck)

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        save_result = session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
            expected_version=expected_version,
        )
        self._record_deck_version(session_id, save_result)

        # Create save point
        try:
            self.create_save_point(
                session_id=session_id,
                description=f"Reordered slides",
                deck=current_deck,
            )
        except Exception as e:
            logger.warning(f"Failed to create save point (reorder_slides): {e}")

        logger.info(
            "Reordered slides",
            extra={"new_order": new_order, "session_id": session_id},
        )

        deck_dict, _ = self._substitute_images_for_response(deck_dict, session_id=session_id)
        return deck_dict

    def update_slide(self, session_id: str, index: int, html: str, *, expected_version: Optional[int] = None) -> Dict[str, Any]:
        """Update a single slide's HTML.

        Args:
            session_id: Session ID
            index: Slide index to update
            html: New HTML content (must include <div class="slide">)

        Returns:
            Updated slide information

        Raises:
            ValueError: If no slide deck exists, invalid index, or invalid HTML
        """
        current_deck = self._get_or_load_deck(session_id)
        if not current_deck:
            raise ValueError("No slide deck available")

        if index < 0 or index >= len(current_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")

        # Validate HTML has slide wrapper. Use the token-aware check so the
        # visual editor's DOMParser round-trip (which may reorder attributes,
        # switch quote style, or emit compound classes) doesn't trip a naive
        # substring match on otherwise-valid slides.
        if not has_slide_wrapper(html):
            raise ValueError("HTML must contain <div class='slide'> wrapper")

        # Preserve original slide's metadata and scripts before updating
        original_slide = current_deck.slides[index]
        original_scripts = original_slide.scripts

        # Update slide with preserved scripts, original creation metadata AND ITS
        # OWN IDENTITY.  An edit is the same slide with new HTML, so it must keep its
        # slide_id — this stamped `f"slide_{index}"` and was the most damaging of the
        # positional stamps for two compounding reasons:
        #
        #   * this is the ONLY one of the ten `_reindex_slide_ids` call sites with no
        #     reindex after it, so the stamp reached the database unresolved.  After an
        #     insert has shifted the deck, `slide_{index}` is an id belonging to a
        #     DIFFERENT slide further down: two rows then carried it, attribution
        #     tier 1 handed the edited slide the other slide's verdict and spec
        #     fragment, and that other slide lost both.  Measured end to end.
        #   * `SlideViewer.tsx:117` tracks per-slide staleness in a Set of slide_ids
        #     across exactly this operation, so renaming the slide mid-edit also drops
        #     its "edited since last verified" flag.
        new_slide = Slide(
            html=html,
            slide_id=original_slide.slide_id,
            scripts=original_scripts,
            created_by=original_slide.created_by,
            created_at=original_slide.created_at,
        )
        try:
            _user = get_current_username()
        except Exception:
            _user = None
        if _user:
            new_slide.stamp_modified(_user)
        current_deck.slides[index] = new_slide

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        save_result = session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
            expected_version=expected_version,
        )
        self._record_deck_version(session_id, save_result)

        # Create save point immediately after persisting
        try:
            self.create_save_point(
                session_id=session_id,
                description=f"Edited slide {index + 1} (HTML)",
                deck=current_deck,
            )
        except Exception as e:
            logger.warning(f"Failed to create save point (update_slide): {e}")

        logger.info(
            "Updated slide",
            extra={"index": index, "session_id": session_id},
        )

        # The slide's REAL id, not its position: a caller handed a positional id will
        # store it and send it back, reintroducing the impersonation from outside.
        return {"index": index, "slide_id": new_slide.slide_id, "html": html}

    def duplicate_slide(self, session_id: str, index: int, *, expected_version: Optional[int] = None) -> Dict[str, Any]:
        """Duplicate a slide.

        Args:
            session_id: Session ID
            index: Slide index to duplicate

        Returns:
            Updated slide deck

        Raises:
            ValueError: If no slide deck exists or invalid index
        """
        current_deck = self._get_or_load_deck(session_id)
        if not current_deck:
            raise ValueError("No slide deck available")

        if index < 0 or index >= len(current_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")

        # Clone slide and stamp as newly created by current user
        cloned = current_deck.slides[index].clone()
        # A clone is a NEW slide, so it gets an identity of its own.  `Slide.clone()`
        # copies slide_id (deliberately — it is a deep copy, and two tests pin that),
        # and this used to rely on `_reindex_slide_ids` rewriting every id to pull the
        # two apart again, which is the rewrite that destroyed durability.
        #
        # MEASURED REDUNDANT, KEPT DELIBERATELY: removing this line reddens nothing,
        # because the clone is inserted at index+1 and `_reindex_slide_ids` resolves a
        # collision in favour of the FIRST holder — so the source keeps its id and the
        # clone is minted anyway.  That outcome depends entirely on the clone landing
        # AFTER its source: insert it before, and the collision pass would take the id
        # off the existing slide and leave it on the copy.  Assigning here states the
        # fact `duplicate_slide` actually knows — which of the two is new — instead of
        # leaving it to be inferred from list order.
        cloned.slide_id = str(uuid.uuid4())
        try:
            _user = get_current_username()
        except Exception:
            _user = None
        if _user:
            cloned.stamp_created(_user)
            cloned.created_by = _user  # override original author

        # Insert after original
        current_deck.insert_slide(cloned, index + 1)

        self._reindex_slide_ids(current_deck)

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        save_result = session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
            expected_version=expected_version,
        )
        self._record_deck_version(session_id, save_result)

        # Create save point
        try:
            self.create_save_point(
                session_id=session_id,
                description=f"Duplicated slide {index + 1}",
                deck=current_deck,
            )
        except Exception as e:
            logger.warning(f"Failed to create save point (duplicate_slide): {e}")

        logger.info(
            "Duplicated slide",
            extra={
                "index": index,
                "new_count": len(current_deck.slides),
                "session_id": session_id,
            },
        )

        deck_dict, _ = self._substitute_images_for_response(deck_dict, session_id=session_id)
        return deck_dict

    def insert_slide(
        self,
        session_id: str,
        position: int,
        *,
        html: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insert a new slide at *position*, shifting every higher slide up.

        Follows ``duplicate_slide``'s shape (insert, ``_reindex_slide_ids``,
        ``save_slide_deck``, ONE save point) and adds the deck-spec half: the spec
        gains an entry for the new position and every entry above it shifts, so
        spec positions stay contiguous and keep describing the right slides.

        WHICH LAYER OWNS THE OUT-OF-RANGE CLAMP
        ---------------------------------------
        The DOMAIN does, and this method deliberately does not re-implement it.
        ``SlideDeck.insert_slide`` delegates to ``list.insert``, which clamps: a
        position past the end appends rather than raising, whatever that method's
        docstring used to claim about ``IndexError``.  So "insert beyond the end
        appends" is free, and the only thing left to decide here is the LOWER
        bound — where ``list.insert`` would silently count backwards from the end
        (``insert(-1, x)`` lands second-to-last, not last).  A negative position is
        therefore rejected rather than clamped: it almost certainly means the
        caller computed it wrongly, and quietly inserting somewhere else is worse
        than a 400.

        ``landed_at`` is computed BEFORE the insert precisely because of that
        clamp — after it, ``position`` may not be where the slide actually is, and
        the deck-spec entry has to go where the slide really landed.

        Args:
            session_id: Session ID.  A contributor session resolves to its deck
                owner in the layers below, exactly as every other mutation does.
            position: 0-based position to insert at.  Beyond the end appends.
            html: HTML for the new slide.  Must carry a ``<div class="slide">``
                wrapper.  Omitted, an empty slide is inserted for a human or the
                architect to fill.
            expected_version: If provided, reject the write when the deck has moved on.

        Returns:
            Updated slide deck dictionary.

        Raises:
            ValueError: If no slide deck exists, position is negative, or the
                supplied HTML has no slide wrapper.
        """
        current_deck = self._get_or_load_deck(session_id)
        if not current_deck:
            raise ValueError("No slide deck available")

        if position < 0:
            raise ValueError(f"Invalid slide position: {position}")

        slide_html = html if html is not None else BLANK_SLIDE_HTML
        if not has_slide_wrapper(slide_html):
            raise ValueError("HTML must contain <div class='slide'> wrapper")

        # Where the slide will ACTUALLY be, given the domain's clamp.
        landed_at = min(position, len(current_deck.slides))

        new_slide = Slide(html=slide_html)
        try:
            _user = get_current_username()
        except Exception:
            _user = None
        if _user:
            new_slide.stamp_created(_user)

        current_deck.insert_slide(new_slide, position)

        self._reindex_slide_ids(current_deck)

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        save_result = session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
            expected_version=expected_version,
        )
        self._record_deck_version(session_id, save_result)

        # The deck spec's slide list has to move with the deck's.  AFTER
        # save_slide_deck, never before: the spec write bumps deck.version, which
        # would make the caller's expected_version stale and 409 a legitimate save.
        spec_result = self._insert_deck_spec_slide(session_id, landed_at)
        if spec_result:
            self._record_deck_version(session_id, spec_result)

        # ONE save point for the whole operation, after the work commits.
        # VERSION_LIMIT evicts the OLDEST version, so a save point per shifted
        # position would delete real history rather than merely bloat it.
        try:
            self.create_save_point(
                session_id=session_id,
                description=f"Inserted slide {landed_at + 1}",
                deck=current_deck,
            )
        except Exception as e:
            logger.warning(f"Failed to create save point (insert_slide): {e}")

        logger.info(
            "Inserted slide",
            extra={
                "requested_position": position,
                "position": landed_at,
                "new_count": len(current_deck.slides),
                "session_id": session_id,
            },
        )

        deck_dict, _ = self._substitute_images_for_response(deck_dict, session_id=session_id)
        return deck_dict

    def _insert_deck_spec_slide(
        self,
        session_id: str,
        position: int,
    ) -> Optional[Dict[str, Any]]:
        """Give the deck spec an entry at *position* and shift the entries above it.

        A deck spec describes the deck slide by slide, keyed on ``position``
        (``SlideSpec.position`` is the canonical identity, looked up by
        ``DeckSpec.slide_at`` and never by list index).  Inserting a slide without
        renumbering would leave every entry above the insertion point describing
        its neighbour.

        The new entry is a PLACEHOLDER — empty purpose and brief.  The route that
        reaches this fires the spec-dirty marker, and the arc-review sweeper is
        what actually describes the new slide; inventing a purpose here would put
        words in the architect's mouth, and leaving the entry out entirely would
        break the contiguity ``slide_at`` depends on.

        Operates on the RAW spec dict rather than parsing a ``DeckSpec``: a spec
        that no longer validates (an older shape, a hand-edited column) must not be
        destroyed by a renumber, and this only touches ``slides[*].position``.

        Returns:
            The writer's result dict (carrying the new deck ``version``), or None
            when there was no spec to shift — a deck built before the spec existed
            is not an error.
        """
        # Imported here, not at module scope: src.api.services.__init__ imports
        # chat_service, so a module-level import of a sibling service is circular.
        from src.api.services.deck_level_writer import (
            read_deck_spec,
            write_deck_level_columns,
        )

        try:
            spec = read_deck_spec(session_id)
        except Exception as e:
            logger.warning(f"Failed to read deck spec (insert_slide): {e}")
            return None

        if not spec:
            return None

        slides = spec.get("slides")
        if not isinstance(slides, list):
            logger.warning(
                "deck_spec_json has no slides list; leaving it untouched",
                extra={"session_id": session_id},
            )
            return None

        shifted: List[Dict[str, Any]] = []
        for entry in slides:
            if not isinstance(entry, dict):
                shifted.append(entry)
                continue
            entry = dict(entry)
            entry_position = entry.get("position")
            if isinstance(entry_position, int) and entry_position >= position:
                entry["position"] = entry_position + 1
            shifted.append(entry)

        shifted.append(
            {
                "position": position,
                "purpose": "",
                "content_brief": "",
                "assumes": "",
                "hands_off": "",
                "data_references": [],
            }
        )
        shifted.sort(
            key=lambda e: e.get("position", 0) if isinstance(e, dict) else 0
        )

        spec = dict(spec)
        spec["slides"] = shifted

        try:
            _user = get_current_username()
        except Exception:
            _user = None

        try:
            return write_deck_level_columns(
                session_id,
                deck_spec=spec,
                modified_by=_user,
            )
        except Exception as e:
            # The slide is already saved and the marker will still fire, so a spec
            # write that fails must not fail the insert.
            logger.warning(f"Failed to shift deck spec (insert_slide): {e}")
            return None

    def delete_slide(self, session_id: str, index: int, *, expected_version: Optional[int] = None) -> Dict[str, Any]:
        """Delete a slide.

        Args:
            session_id: Session ID
            index: Slide index to delete

        Returns:
            Updated slide deck

        Raises:
            ValueError: If no slide deck exists, invalid index, or deleting last slide
        """
        current_deck = self._get_or_load_deck(session_id)
        if not current_deck:
            raise ValueError("No slide deck available")

        if index < 0 or index >= len(current_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")

        if len(current_deck.slides) <= 1:
            raise ValueError("Cannot delete last slide")

        # Remove slide
        current_deck.remove_slide(index)

        self._reindex_slide_ids(current_deck)

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        save_result = session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
            expected_version=expected_version,
        )
        self._record_deck_version(session_id, save_result)

        # Create save point
        try:
            self.create_save_point(
                session_id=session_id,
                description=f"Deleted slide {index + 1}",
                deck=current_deck,
            )
        except Exception as e:
            logger.warning(f"Failed to create save point (delete_slide): {e}")

        logger.info(
            "Deleted slide",
            extra={
                "index": index,
                "new_count": len(current_deck.slides),
                "session_id": session_id,
            },
        )

        deck_dict, _ = self._substitute_images_for_response(deck_dict, session_id=session_id)
        return deck_dict


# Global service instance
_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get the global ChatService instance.

    Returns:
        ChatService instance
    """
    global _chat_service_instance

    if _chat_service_instance is None:
        _chat_service_instance = ChatService()

    return _chat_service_instance
