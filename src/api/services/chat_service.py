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
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import SessionNotFoundError, get_session_manager
from src.core.databricks_client import (
    get_current_username,
    get_service_principal_folder,
    get_system_client,
)
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.agent import create_agent
from src.services.streaming_callback import StreamingCallbackHandler
from src.utils.html_utils import (
    extract_canvas_ids_from_html,
    split_script_by_canvas,
)

logger = logging.getLogger(__name__)


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


class ChatService:
    """Service for managing chat interactions with the AI agent.

    All session state is persisted in the database via SessionManager.
    This service handles the AI agent lifecycle and message processing.

    Attributes:
        agent: SlideGeneratorAgent instance
    """

    def __init__(self):
        """Initialize the chat service with agent."""
        logger.info("Initializing ChatService")

        # Thread lock for safe agent reloading
        self._reload_lock = threading.Lock()

        # Thread lock for safe deck cache access
        self._cache_lock = threading.Lock()

        # Create agent instance
        self.agent = create_agent()

        # In-memory cache of slide decks (keyed by session_id)
        # This avoids re-parsing HTML on every request
        self._deck_cache: Dict[str, SlideDeck] = {}

        logger.info("ChatService initialized successfully")

    def reload_agent(self, profile_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Reload agent with new settings from database.

        This allows hot-reload of configuration without restarting the application.
        Genie conversation IDs are preserved - each session tracks its profile_id
        and the genie_conversation_id remains valid for that profile's Genie space.

        Args:
            profile_id: Profile ID to load, or None for default profile

        Returns:
            Dictionary with reload status and profile information

        Raises:
            Exception: If reload fails (agent remains in previous state)
        """
        with self._reload_lock:
            logger.info(
                "Reloading agent with new configuration",
                extra={"profile_id": profile_id},
            )

            try:
                # Reload settings from database
                from src.core.settings_db import reload_settings

                new_settings = reload_settings(profile_id)
                logger.info(
                    "Loaded new settings",
                    extra={
                        "profile_id": new_settings.profile_id,
                        "profile_name": new_settings.profile_name,
                        "llm_endpoint": new_settings.llm.endpoint,
                        "genie_space_id": new_settings.genie.space_id if new_settings.genie else None,
                        "prompt_only_mode": new_settings.genie is None,
                    },
                )

                # Note: Genie conversation IDs are no longer cleared on profile switch.
                # Each session is associated with a profile_id, and the genie_conversation_id
                # remains valid when the user switches back to that profile.
                # See: profile-switch-genie-flow.md for details.

                # Create new agent with new settings
                new_agent = create_agent()
                logger.info("Created new agent instance")

                # Atomic swap
                self.agent = new_agent

                # Clear deck cache (settings may affect rendering)
                with self._cache_lock:
                    self._deck_cache.clear()

                logger.info(
                    "Agent reloaded successfully",
                    extra={
                        "profile_id": new_settings.profile_id,
                        "profile_name": new_settings.profile_name,
                    },
                )

                return {
                    "status": "reloaded",
                    "profile_id": new_settings.profile_id,
                    "profile_name": new_settings.profile_name,
                    "llm_endpoint": new_settings.llm.endpoint,
                }

            except Exception as e:
                logger.error(
                    f"Failed to reload agent: {e}",
                    exc_info=True,
                    extra={"profile_id": profile_id},
                )
                raise Exception(f"Agent reload failed: {e}") from e

    def send_message(
        self,
        session_id: str,
        message: str,
        slide_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a message to the agent and get response.

        Args:
            session_id: Session ID (auto-created if doesn't exist)
            message: User's message
            slide_context: Optional context for slide editing

        Returns:
            Dictionary containing:
                - messages: List of message dicts for UI display
                - slide_deck: Parsed slide deck dict (if generated)
                - metadata: Execution metadata
                - session_id: The session ID used

        Raises:
            Exception: If agent fails to generate slides
        """
        logger.info(
            "Processing message",
            extra={
                "message_length": len(message),
                "session_id": session_id,
                "has_slide_context": slide_context is not None,
            },
        )

        # Get or create session in database (auto-create on first message)
        session_manager = get_session_manager()
        
        # Get current profile info for session association
        from src.core.settings_db import get_settings
        settings = get_settings()
        profile_id = getattr(settings, 'profile_id', None)
        profile_name = getattr(settings, 'profile_name', None)
        
        try:
            db_session = session_manager.get_session(session_id)
            # Update profile for existing session without one
            if db_session.get("profile_id") is None and profile_id is not None:
                session_manager.set_session_profile(session_id, profile_id, profile_name)
                db_session["profile_id"] = profile_id
                db_session["profile_name"] = profile_name
        except SessionNotFoundError:
            # Auto-create session on first message
            db_session = session_manager.create_session(
                session_id=session_id,
                profile_id=profile_id,
                profile_name=profile_name,
            )
            logger.info(
                "Auto-created session on first message",
                extra={"session_id": session_id, "profile_id": profile_id},
            )

        # Ensure session is registered with the agent
        # The agent maintains its own in-memory session store for conversation state
        experiment_url = self._ensure_agent_session(session_id, db_session.get("genie_conversation_id"))

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
                        "messages": [{"role": "assistant", "content": clarification_msg}],
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
                        "messages": [{"role": "assistant", "content": clarification_msg}],
                        "slide_deck": existing_deck.to_dict(),
                        "raw_html": existing_deck.knit(),
                        "metadata": {"clarification_needed": True},
                        "replacement_info": None,
                        "session_id": session_id,
                    }

        # RC13: Auto-create slide_context from text reference (sync path)
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

        try:
            # Call agent to generate slides
            result = self.agent.generate_slides(
                question=message,
                session_id=session_id,
                slide_context=slide_context,
            )

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
                        
                        for idx, slide in enumerate(new_deck.slides):
                            slide.slide_id = f"slide_{insert_position + idx}"
                            existing_deck.insert_slide(slide, insert_position + idx)
                        
                        # Update ALL slide IDs to reflect new positions (prevents duplicate keys)
                        for idx, slide in enumerate(existing_deck.slides):
                            slide.slide_id = f"slide_{idx}"
                        
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
                session_manager.save_slide_deck(
                    session_id=session_id,
                    title=current_deck.title,
                    html_content=current_deck.knit(),
                    scripts_content=current_deck.scripts,
                    slide_count=len(current_deck.slides),
                    deck_dict=slide_deck_dict,
                )

                # NOTE: Save point creation moved to frontend after auto-verification completes
                # Frontend calls POST /api/slides/versions/create after verification

            # Update session activity
            session_manager.update_last_activity(session_id)

            # RC11: Check for conflict between selection and text reference (sync path)
            conflict_note = None
            if slide_context:
                text_refs, _ = self._parse_slide_references(message)
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

            # Build response
            messages = result["messages"]
            if conflict_note:
                messages = messages + [{"role": "assistant", "content": conflict_note}]
            
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

        Yields:
            StreamEvent objects for real-time display

        Raises:
            Exception: If agent fails to generate slides
        """
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
        
        # Get current profile info for session association
        from src.core.settings_db import get_settings
        settings = get_settings()
        profile_id = getattr(settings, 'profile_id', None)
        profile_name = getattr(settings, 'profile_name', None)
        
        try:
            db_session = session_manager.get_session(session_id)
            # Update profile for existing session without one
            if db_session.get("profile_id") is None and profile_id is not None:
                session_manager.set_session_profile(session_id, profile_id, profile_name)
                db_session["profile_id"] = profile_id
                db_session["profile_name"] = profile_name
        except SessionNotFoundError:
            db_session = session_manager.create_session(
                session_id=session_id,
                profile_id=profile_id,
                profile_name=profile_name,
            )
            logger.info(
                "Auto-created session on first streaming message",
                extra={"session_id": session_id, "profile_id": profile_id},
            )

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

        # Ensure session is registered with the agent (hydrates history)
        experiment_url = self._ensure_agent_session(session_id, db_session.get("genie_conversation_id"))

        # Issue 2 FIX: Detect intent ONCE and store for reuse throughout the function
        # This avoids running regex patterns twice on every request
        _is_edit = self._detect_edit_intent(message)
        _is_generation = self._detect_generation_intent(message)
        _is_add = self._detect_add_intent(message)
        _slide_refs, _ref_position = self._parse_slide_references(message)
        _is_explicit_replace = self._detect_explicit_replace_intent(message)

        # RC10: Early clarification check BEFORE calling LLM
        # If user seems to want to edit but didn't specify which slide, ask for clarification
        if not slide_context:
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and len(existing_deck.slides) > 0:
                # Generation intent with existing deck - ask add or replace
                # Skip if user explicitly said "add" or "replace"
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
                    # Persist clarification as assistant message
                    session_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=clarification_msg,
                        message_type="clarification",
                    )
                    # Return clarification without calling LLM
                    yield StreamEvent(
                        type=StreamEventType.ASSISTANT,
                        content=clarification_msg,
                    )
                    yield StreamEvent(
                        type=StreamEventType.COMPLETE,
                        slides=existing_deck.to_dict(),
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
                    # Persist clarification as assistant message
                    session_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=clarification_msg,
                        message_type="clarification",
                    )
                    # Return clarification without calling LLM
                    yield StreamEvent(
                        type=StreamEventType.ASSISTANT,
                        content=clarification_msg,
                    )
                    yield StreamEvent(
                        type=StreamEventType.COMPLETE,
                        slides=existing_deck.to_dict(),
                    )
                    return

        # RC14: Validate slide_context indices against current backend deck state
        # This catches state mismatches where frontend and backend are out of sync
        if slide_context:
            selected_indices = slide_context.get("indices", [])
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and selected_indices:
                max_index = max(selected_indices)
                if max_index >= len(existing_deck.slides):
                    # State mismatch detected - frontend shows more slides than backend has
                    logger.error(
                        "RC14: Frontend/backend deck state mismatch detected",
                        extra={
                            "session_id": session_id,
                            "selected_indices": selected_indices,
                            "backend_slide_count": len(existing_deck.slides),
                            "max_selected_index": max_index,
                        },
                    )
                    # Return error to user with instructions to refresh
                    error_msg = (
                        f"⚠️ Deck sync error: You selected slide {max_index + 1}, but only "
                        f"{len(existing_deck.slides)} slide(s) exist in the saved deck. "
                        "This can happen if a previous save failed. "
                        "Please refresh the page to resync your session."
                    )
                    session_manager.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=error_msg,
                        message_type="error",
                    )
                    yield StreamEvent(
                        type=StreamEventType.ASSISTANT,
                        content=error_msg,
                    )
                    yield StreamEvent(
                        type=StreamEventType.COMPLETE,
                        slides=existing_deck.to_dict() if existing_deck else None,
                    )
                    return

        # RC11: Detect conflict between selection and text reference
        conflict_note = None
        if slide_context:
            # Reuse _slide_refs from early detection (Issue 2 optimization)
            if _slide_refs:
                selected_indices = slide_context.get("indices", [])
                # Check if text references differ from selection
                if set(_slide_refs) != set(selected_indices):
                    # Convert to 1-based for user display
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

        # RC13: Auto-create slide_context from text reference (e.g., "edit slide 7")
        # If user mentioned a slide number but didn't select in panel, look up the slide
        if _is_edit and _slide_refs and not slide_context:
            existing_deck = self._get_or_load_deck(session_id)
            if existing_deck and len(existing_deck.slides) > 0:
                # Validate indices are in range
                valid_refs = [i for i in _slide_refs if 0 <= i < len(existing_deck.slides)]
                if valid_refs:
                    # Look up the actual slide HTML(s)
                    slide_htmls = [existing_deck.slides[i].html for i in valid_refs]
                    # Create context in same format as frontend selection
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

        # Create event queue and callback handler
        event_queue: queue.Queue[StreamEvent] = queue.Queue()
        callback_handler = StreamingCallbackHandler(
            event_queue, session_id, request_id=request_id
        )

        # Run agent in thread and yield events
        result_container: Dict[str, Any] = {}
        error_container: Dict[str, Exception] = {}

        # Capture context BEFORE starting thread to preserve user auth
        ctx = contextvars.copy_context()

        def run_agent():
            try:
                result = self.agent.generate_slides_streaming(
                    question=message,
                    session_id=session_id,
                    callback_handler=callback_handler,
                    slide_context=slide_context,
                )
                result_container["result"] = result
            except Exception as e:
                error_container["error"] = e
                callback_handler.event_queue.put(
                    StreamEvent(type=StreamEventType.ERROR, error=str(e))
                )
            finally:
                # Signal completion by putting None
                event_queue.put(None)

        # Start agent thread with context preserved for user auth
        agent_thread = threading.Thread(target=lambda: ctx.run(run_agent), daemon=True)
        agent_thread.start()

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
                        
                        for idx, slide in enumerate(new_deck.slides):
                            slide.slide_id = f"slide_{insert_position + idx}"
                            existing_deck.insert_slide(slide, insert_position + idx)
                        
                        # Update ALL slide IDs to reflect new positions (prevents duplicate keys)
                        for idx, slide in enumerate(existing_deck.slides):
                            slide.slide_id = f"slide_{idx}"
                        
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
                    
                    for idx, slide in enumerate(new_deck.slides):
                        slide.slide_id = f"slide_{insert_position + idx}"
                        existing_deck.insert_slide(slide, insert_position + idx)
                    
                    # Update ALL slide IDs to reflect new positions (prevents duplicate keys)
                    for idx, slide in enumerate(existing_deck.slides):
                        slide.slide_id = f"slide_{idx}"
                    
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
            session_manager.save_slide_deck(
                session_id=session_id,
                title=current_deck.title,
                html_content=current_deck.knit(),
                scripts_content=current_deck.scripts,
                slide_count=len(current_deck.slides),
                deck_dict=slide_deck_dict,
            )

            # NOTE: Save point creation moved to frontend after auto-verification completes
            # Frontend calls POST /api/slides/versions/create after verification

        # Update session activity
        session_manager.update_last_activity(session_id)

        # RC11: Yield conflict note if selection differed from text reference
        if conflict_note:
            yield StreamEvent(
                type=StreamEventType.ASSISTANT,
                content=conflict_note,
            )
            # Persist the note
            session_manager.add_message(
                session_id=session_id,
                role="assistant",
                content=conflict_note,
                message_type="info",
            )

        # Yield final complete event (sanitize replacement_info for JSON serialization)
        yield StreamEvent(
            type=StreamEventType.COMPLETE,
            slides=slide_deck_dict,
            raw_html=raw_html,
            replacement_info=_sanitize_replacement_info(replacement_info),
            metadata=result.get("metadata"),
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

    def _ensure_agent_session(
        self, session_id: str, genie_conversation_id: Optional[str] = None
    ) -> Optional[str]:
        """Ensure the session is registered with the agent.

        The agent maintains its own in-memory session store for conversation
        state (chat history, Genie conversation, MLflow experiment). This method
        ensures the database session is registered with the agent and hydrates
        the chat history from persisted messages.

        Args:
            session_id: Session ID from database
            genie_conversation_id: Optional existing Genie conversation ID

        Returns:
            experiment_url for the session, or None if experiment creation failed
        """
        # Check if agent already has this session
        if session_id in self.agent.sessions:
            # Update profile_name if settings have changed (handles profile switching)
            from src.core.settings_db import get_settings
            current_settings = get_settings()
            current_profile = current_settings.profile_name or "default"
            if self.agent.sessions[session_id].get("profile_name") != current_profile:
                self.agent.sessions[session_id]["profile_name"] = current_profile
                logger.info(
                    "Updated session profile after switch",
                    extra={"session_id": session_id, "profile_name": current_profile},
                )
            
            # Agent session exists - ensure genie_conversation_id is persisted to DB
            agent_genie_id = self.agent.sessions[session_id].get("genie_conversation_id")
            if agent_genie_id and not genie_conversation_id:
                # Agent has genie ID but DB doesn't - save it now
                session_manager = get_session_manager()
                session_manager.set_genie_conversation_id(session_id, agent_genie_id)
                logger.info(
                    "Persisted existing genie_conversation_id to database",
                    extra={"session_id": session_id, "genie_conversation_id": agent_genie_id},
                )
            return self.agent.sessions[session_id].get("experiment_url")

        logger.info(
            "Registering session with agent",
            extra={"session_id": session_id, "genie_conversation_id": genie_conversation_id},
        )

        from src.core.settings_db import get_settings
        from src.services.tools import initialize_genie_conversation

        settings = get_settings()

        try:
            # Get current username for experiment path and permissions
            try:
                username = get_current_username()
                logger.warning(f"ChatService: Got current username: {username}")
            except Exception as e:
                logger.warning(f"ChatService: Failed to get current username: {e}")
                username = "unknown"

            # Ensure user's MLflow experiment exists (one per user)
            profile_name = settings.profile_name or "default"
            experiment_id, experiment_url = self._ensure_user_experiment(
                session_id, username
            )

            # Use existing Genie conversation or create new one (only if Genie configured)
            if genie_conversation_id:
                genie_conv_id = genie_conversation_id
            elif settings.genie:
                genie_conv_id = initialize_genie_conversation()
                # Save the new Genie conversation ID to database
                session_manager = get_session_manager()
                session_manager.set_genie_conversation_id(session_id, genie_conv_id)
            else:
                # Prompt-only mode - no Genie conversation needed
                genie_conv_id = None
                logger.info(
                    "Prompt-only mode - skipping Genie conversation initialization",
                    extra={"session_id": session_id},
                )

            # Create chat history and hydrate from database
            chat_history = ChatMessageHistory()
            message_count = self._hydrate_chat_history(session_id, chat_history)

            # Initialize agent session data with experiment info and session metadata
            session_timestamp = datetime.utcnow().isoformat()
            self.agent.sessions[session_id] = {
                "chat_history": chat_history,
                "genie_conversation_id": genie_conv_id,
                "experiment_id": experiment_id,
                "experiment_url": experiment_url,
                "username": username,
                "profile_name": profile_name,
                "created_at": session_timestamp,
                "message_count": message_count,
            }

            # Persist experiment_id to database for verification endpoint access
            if experiment_id:
                session_manager = get_session_manager()
                session_manager.set_experiment_id(session_id, experiment_id)

            logger.info(
                "Session registered with agent",
                extra={
                    "session_id": session_id,
                    "genie_conversation_id": genie_conv_id,
                    "experiment_id": experiment_id,
                    "experiment_url": experiment_url,
                    "hydrated_messages": message_count,
                },
            )

            return experiment_url

        except Exception as e:
            logger.error(f"Failed to register session with agent: {e}", exc_info=True)
            raise

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
            
            # Check if experiment already exists
            experiment = mlflow.get_experiment_by_name(experiment_path)
            
            if experiment:
                experiment_id = experiment.experiment_id
                logger.info(
                    f"Using existing user experiment: {experiment_id}",
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
                
                # Create new experiment for user
                experiment_id = mlflow.create_experiment(experiment_path)
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

    def _get_user_experiment_id(self, username: str) -> Optional[str]:
        """Get the MLflow experiment ID for a user (lookup only, no create).

        Uses the same path convention as _ensure_user_experiment.
        Returns None if the experiment does not exist.
        """
        import mlflow

        sp_folder = get_service_principal_folder()
        experiment_path = (
            f"{sp_folder}/{username}/ai-slide-generator"
            if sp_folder
            else f"/Workspace/Users/{username}/ai-slide-generator"
        )
        try:
            mlflow.set_tracking_uri("databricks")
            experiment = mlflow.get_experiment_by_name(experiment_path)
            return experiment.experiment_id if experiment else None
        except Exception as e:
            logger.warning(
                f"Failed to get user experiment for invocations: {e}",
                extra={"username": username, "experiment_path": experiment_path},
            )
            return None

    def list_invocations(self, username: str, limit: int = 100) -> List[Dict[str, Any]]:
        """List MLflow runs (invocations) for the current user's experiment.

        Returns runs ordered by start_time descending, filtered to the user's
        experiment. Each run may have a session_id tag for restore.
        """
        import mlflow

        experiment_id = self._get_user_experiment_id(username)
        if not experiment_id:
            return []

        try:
            mlflow.set_tracking_uri("databricks")
            runs = mlflow.search_runs(
                experiment_ids=[experiment_id],
                order_by=["start_time DESC"],
                max_results=limit,
            )
            if runs.empty:
                return []

            invocations: List[Dict[str, Any]] = []
            for _, row in runs.iterrows():
                run_id = row.get("run_id") or row.get("run_uuid")
                start_time = row.get("start_time")
                end_time = row.get("end_time")
                status = row.get("status", "UNKNOWN")
                raw_sid = row.get("tags.session_id")
                session_id = raw_sid if (isinstance(raw_sid, str) and raw_sid.strip()) else None
                duration_seconds = None
                if start_time is not None and end_time is not None:
                    try:
                        duration_seconds = (end_time - start_time).total_seconds()
                    except Exception:
                        pass
                invocations.append({
                    "run_id": str(run_id) if run_id else None,
                    "session_id": session_id,
                    "start_time": start_time.isoformat() if hasattr(start_time, "isoformat") and start_time else None,
                    "end_time": end_time.isoformat() if hasattr(end_time, "isoformat") and end_time else None,
                    "duration_seconds": duration_seconds,
                    "status": status,
                })
            return invocations
        except Exception as e:
            logger.error(f"Failed to list invocations: {e}", exc_info=True)
            return []

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
        for msg in db_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not content:
                continue

            if role == "user":
                chat_history.add_message(HumanMessage(content=content))
                count += 1
            elif role == "assistant":
                chat_history.add_message(AIMessage(content=content))
                count += 1
            # Skip tool messages for history (they're included via intermediate steps)

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
                    extra={"message": message[:50], "matched_pattern": pattern},
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
                    extra={"message": message[:50], "matched_pattern": pattern},
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
                    extra={"message": message[:50], "matched_pattern": pattern},
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
            r"\bmake\s+me\b.*\bslides?\b",
            r"\b\d+\s+slides?\s+(about|on|for)\b",  # "5 slides about X"
            r"\bcreate\b.*\b\d+\s+slides?\b",  # "create 3 slides"
            # Removed overly broad pattern r"\b\d+\s+slides?\b" to prevent false positives
            # e.g., "edit slide 5 slides look broken" would incorrectly match
            r"\bnew\s+(presentation|deck)\b",
            r"\bbuild\b.*\b(presentation|deck|slides)\b",
            r"\bprepare\b.*\bslides?\b",
        ]
        
        lower_message = message.lower()
        for pattern in generation_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected generation intent",
                    extra={"message": message[:50], "matched_pattern": pattern},
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
                    extra={"message": message[:50], "matched_pattern": pattern},
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
                    extra={"message": message[:50], "matched_pattern": pattern},
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

    def _get_or_load_deck(self, session_id: str) -> Optional[SlideDeck]:
        """Get deck from cache or load from database.

        Thread-safe access to deck cache using _cache_lock.
        
        Uses deck_dict (slides array with individual scripts) when available,
        falling back to from_html_string for legacy data.
        """
        # Check cache first (with lock)
        with self._cache_lock:
            if session_id in self._deck_cache:
                return self._deck_cache[session_id]

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
            return deck
        except Exception as e:
            logger.warning(f"Failed to load deck from database: {e}")

        return None
    
    def _reconstruct_deck_from_dict(self, deck_data: Dict[str, Any]) -> SlideDeck:
        """Reconstruct SlideDeck from stored dict (preserves individual slide scripts).
        
        Args:
            deck_data: Dictionary from get_slide_deck with slides array
            
        Returns:
            Reconstructed SlideDeck with proper per-slide scripts
        """
        slides = []
        for slide_data in deck_data.get("slides", []):
            slide = Slide(
                html=slide_data.get("html", ""),
                slide_id=slide_data.get("slide_id", f"slide_{len(slides)}"),
                scripts=slide_data.get("scripts", ""),
            )
            slides.append(slide)
        
        deck = SlideDeck(
            slides=slides,
            css=deck_data.get("css", ""),
            external_scripts=deck_data.get("external_scripts", []),
            title=deck_data.get("title"),
        )
        return deck

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
                slide.slide_id = f"slide_{insert_position + idx}"
                current_deck.insert_slide(slide, insert_position + idx)
                logger.info(
                    "Inserted new slide (add operation)",
                    extra={"slide_index": insert_position + idx, "session_id": session_id},
                )
            
            # Update ALL slide IDs to reflect new positions (prevents duplicate keys)
            for idx, slide in enumerate(current_deck.slides):
                slide.slide_id = f"slide_{idx}"
            
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
            slide.slide_id = f"slide_{start_idx + idx}"
            
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
                return deck_dict
        except Exception as e:
            logger.warning(f"Failed to load deck from session_manager: {e}")
        
        # Fallback to internal cache (without verification/content_hash)
        deck = self._get_or_load_deck(session_id)
        if not deck:
            return None
        return deck.to_dict()

    def reorder_slides(self, session_id: str, new_order: List[int]) -> Dict[str, Any]:
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

        # Update indices
        for idx, slide in enumerate(current_deck.slides):
            slide.slide_id = f"slide_{idx}"

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
        )

        # Create save point
        self.create_save_point(
            session_id=session_id,
            description=f"Reordered slides",
            deck=current_deck,
        )

        logger.info(
            "Reordered slides",
            extra={"new_order": new_order, "session_id": session_id},
        )

        return deck_dict

    def update_slide(self, session_id: str, index: int, html: str) -> Dict[str, Any]:
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

        # Validate HTML has slide wrapper
        if '<div class="slide"' not in html:
            raise ValueError("HTML must contain <div class='slide'> wrapper")

        # Preserve original slide's scripts (charts, etc.) before updating
        original_scripts = current_deck.slides[index].scripts

        # Update slide with preserved scripts
        current_deck.slides[index] = Slide(
            html=html,
            slide_id=f"slide_{index}",
            scripts=original_scripts,
        )

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
        )

        # NOTE: Save point creation moved to frontend after auto-verification completes
        # Frontend calls POST /api/slides/versions/create after verification

        logger.info(
            "Updated slide",
            extra={"index": index, "session_id": session_id},
        )

        return {"index": index, "slide_id": f"slide_{index}", "html": html}

    def duplicate_slide(self, session_id: str, index: int) -> Dict[str, Any]:
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

        # Clone slide
        cloned = current_deck.slides[index].clone()

        # Insert after original
        current_deck.insert_slide(cloned, index + 1)

        # Update slide IDs
        for idx, slide in enumerate(current_deck.slides):
            slide.slide_id = f"slide_{idx}"

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
        )

        # Create save point
        self.create_save_point(
            session_id=session_id,
            description=f"Duplicated slide {index + 1}",
            deck=current_deck,
        )

        logger.info(
            "Duplicated slide",
            extra={
                "index": index,
                "new_count": len(current_deck.slides),
                "session_id": session_id,
            },
        )

        return deck_dict

    def delete_slide(self, session_id: str, index: int) -> Dict[str, Any]:
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

        # Update slide IDs
        for idx, slide in enumerate(current_deck.slides):
            slide.slide_id = f"slide_{idx}"

        # Persist to database
        deck_dict = current_deck.to_dict()
        session_manager = get_session_manager()
        session_manager.save_slide_deck(
            session_id=session_id,
            title=current_deck.title,
            html_content=current_deck.knit(),
            scripts_content=current_deck.scripts,
            slide_count=len(current_deck.slides),
            deck_dict=deck_dict,
        )

        # Create save point
        self.create_save_point(
            session_id=session_id,
            description=f"Deleted slide {index + 1}",
            deck=current_deck,
        )

        logger.info(
            "Deleted slide",
            extra={
                "index": index,
                "new_count": len(current_deck.slides),
                "session_id": session_id,
            },
        )

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
