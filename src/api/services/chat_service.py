"""Chat service wrapper around the agent.

All session state is stored in the database (PostgreSQL in dev, Lakebase in prod).
Sessions are auto-created on first message if they don't exist.

Scripts are stored directly on Slide objects. When a slide is replaced,
its scripts are automatically replaced with it - no separate cleanup needed.
"""

import logging
import queue
import threading
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import get_session_manager, SessionNotFoundError
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.agent import create_agent
from src.services.streaming_callback import StreamingCallbackHandler

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
        Genie conversation IDs are cleared from all sessions in the database.

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
                        "genie_space_id": new_settings.genie.space_id,
                    },
                )

                # Clear Genie conversation IDs from all sessions
                # (they're tied to the old Genie space)
                session_manager = get_session_manager()
                sessions = session_manager.list_sessions(limit=1000)
                for session in sessions:
                    session_manager.set_genie_conversation_id(
                        session["session_id"], None
                    )
                logger.info(
                    "Cleared Genie conversation IDs",
                    extra={"session_count": len(sessions)},
                )

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
                    "sessions_updated": len(sessions),
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
        try:
            db_session = session_manager.get_session(session_id)
        except SessionNotFoundError:
            # Auto-create session on first message
            db_session = session_manager.create_session(session_id=session_id)
            logger.info(
                "Auto-created session on first message",
                extra={"session_id": session_id},
            )

        # Ensure session is registered with the agent
        # The agent maintains its own in-memory session store for conversation state
        self._ensure_agent_session(session_id, db_session.get("genie_conversation_id"))

        try:
            # Call agent to generate slides
            result = self.agent.generate_slides(
                question=message,
                session_id=session_id,
                slide_context=slide_context,
            )

            html_output = result.get("html")
            replacement_info = result.get("replacement_info")

            # Get cached deck for this session (thread-safe)
            with self._cache_lock:
                current_deck = self._deck_cache.get(session_id)

            if slide_context and replacement_info:
                slide_deck_dict = self._apply_slide_replacements(
                    replacement_info=result["parsed_output"],
                    session_id=session_id,
                )
                with self._cache_lock:
                    current_deck = self._deck_cache.get(session_id)
                raw_html = current_deck.knit() if current_deck else None
            elif html_output and html_output.strip():
                raw_html = html_output

                try:
                    current_deck = SlideDeck.from_html_string(html_output)
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

            # Update session activity
            session_manager.update_last_activity(session_id)

            # Build response
            response = {
                "messages": result["messages"],
                "slide_deck": slide_deck_dict,
                "raw_html": raw_html,
                "metadata": result["metadata"],
                "replacement_info": _sanitize_replacement_info(replacement_info),
                "session_id": session_id,
            }

            logger.info(
                "Message processed successfully",
                extra={
                    "message_count": len(response["messages"]),
                    "has_slide_deck": response["slide_deck"] is not None,
                    "session_id": session_id,
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
        try:
            db_session = session_manager.get_session(session_id)
        except SessionNotFoundError:
            db_session = session_manager.create_session(session_id=session_id)
            logger.info(
                "Auto-created session on first streaming message",
                extra={"session_id": session_id},
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
        self._ensure_agent_session(session_id, db_session.get("genie_conversation_id"))

        # Create event queue and callback handler
        event_queue: queue.Queue[StreamEvent] = queue.Queue()
        callback_handler = StreamingCallbackHandler(
            event_queue, session_id, request_id=request_id
        )

        # Run agent in thread and yield events
        result_container: Dict[str, Any] = {}
        error_container: Dict[str, Exception] = {}

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

        # Start agent thread
        agent_thread = threading.Thread(target=run_agent, daemon=True)
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

        # Get cached deck for this session (thread-safe)
        with self._cache_lock:
            current_deck = self._deck_cache.get(session_id)

        slide_deck_dict = None
        raw_html = None

        if slide_context and replacement_info:
            slide_deck_dict = self._apply_slide_replacements(
                replacement_info=replacement_info,
                session_id=session_id,
            )
            with self._cache_lock:
                current_deck = self._deck_cache.get(session_id)
            raw_html = current_deck.knit() if current_deck else None
        elif html_output and html_output.strip():
            raw_html = html_output
            try:
                current_deck = SlideDeck.from_html_string(html_output)
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

        # Update session activity
        session_manager.update_last_activity(session_id)

        # Yield final complete event (sanitize replacement_info for JSON serialization)
        yield StreamEvent(
            type=StreamEventType.COMPLETE,
            slides=slide_deck_dict,
            raw_html=raw_html,
            replacement_info=_sanitize_replacement_info(replacement_info),
            metadata=result.get("metadata"),
        )

        logger.info(
            "Streaming message completed",
            extra={
                "session_id": session_id,
                "has_slide_deck": slide_deck_dict is not None,
            },
        )

    def _ensure_agent_session(
        self, session_id: str, genie_conversation_id: Optional[str] = None
    ) -> None:
        """Ensure the session is registered with the agent.

        The agent maintains its own in-memory session store for conversation
        state (chat history, Genie conversation). This method ensures the
        database session is registered with the agent and hydrates the
        chat history from persisted messages.

        Args:
            session_id: Session ID from database
            genie_conversation_id: Optional existing Genie conversation ID
        """
        # Check if agent already has this session
        if session_id in self.agent.sessions:
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
            return

        logger.info(
            "Registering session with agent",
            extra={"session_id": session_id, "genie_conversation_id": genie_conversation_id},
        )

        from src.services.tools import initialize_genie_conversation

        try:
            # Use existing Genie conversation or create new one
            if genie_conversation_id:
                genie_conv_id = genie_conversation_id
            else:
                genie_conv_id = initialize_genie_conversation()
                # Save the new Genie conversation ID to database
                session_manager = get_session_manager()
                session_manager.set_genie_conversation_id(session_id, genie_conv_id)

            # Create chat history and hydrate from database
            chat_history = ChatMessageHistory()
            message_count = self._hydrate_chat_history(session_id, chat_history)

            # Initialize agent session data
            self.agent.sessions[session_id] = {
                "chat_history": chat_history,
                "genie_conversation_id": genie_conv_id,
                "created_at": datetime.utcnow().isoformat(),
                "message_count": message_count,
            }

            logger.info(
                "Session registered with agent",
                extra={
                    "session_id": session_id,
                    "genie_conversation_id": genie_conv_id,
                    "hydrated_messages": message_count,
                },
            )

        except Exception as e:
            logger.error(f"Failed to register session with agent: {e}", exc_info=True)
            raise

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

    def _get_or_load_deck(self, session_id: str) -> Optional[SlideDeck]:
        """Get deck from cache or load from database.

        Thread-safe access to deck cache using _cache_lock.
        """
        # Check cache first (with lock)
        with self._cache_lock:
            if session_id in self._deck_cache:
                return self._deck_cache[session_id]

        # Try to load from database (outside lock to avoid blocking)
        session_manager = get_session_manager()
        deck_data = session_manager.get_slide_deck(session_id)

        if deck_data and deck_data.get("html_content"):
            try:
                deck = SlideDeck.from_html_string(deck_data["html_content"])
                # Store in cache (with lock)
                with self._cache_lock:
                    self._deck_cache[session_id] = deck
                return deck
            except Exception as e:
                logger.warning(f"Failed to load deck from database: {e}")

        return None

    def _apply_slide_replacements(
        self,
        replacement_info: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Apply slide replacements to the session's slide deck.

        Handles variable-length replacements by removing the original block
        and inserting the new Slide objects at the same start index.
        
        Scripts are attached directly to Slide objects, so when a slide
        is removed its scripts go with it automatically.

        Args:
            replacement_info: Information about the replacement operation
                - replacement_slides: List of Slide objects (with scripts attached)
                - replacement_css: Optional CSS to merge
                - start_index, original_count: Position info
            session_id: Session ID
        """
        current_deck = self._get_or_load_deck(session_id)

        if current_deck is None:
            raise ValueError("No current deck to apply replacements to")

        start_idx = replacement_info["start_index"]
        original_count = replacement_info["original_count"]
        replacement_slides: List[Slide] = replacement_info["replacement_slides"]

        # Validate replacement range
        if start_idx < 0 or start_idx >= len(current_deck.slides):
            raise ValueError(f"Start index {start_idx} out of range")
        if start_idx + original_count > len(current_deck.slides):
            raise ValueError("Replacement range exceeds deck size")

        # Remove original slides (scripts go with them automatically)
        for _ in range(original_count):
            current_deck.remove_slide(start_idx)

        logger.info(
            "Removed slides for replacement",
            extra={"count": original_count, "start_index": start_idx},
        )

        # Insert replacement slides (scripts already attached)
        for idx, slide in enumerate(replacement_slides):
            # Update slide_id to reflect new position
            slide.slide_id = f"slide_{start_idx + idx}"
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

        # Validate indices
        if len(new_order) != len(current_deck.slides):
            raise ValueError("Invalid reorder: wrong number of indices")

        if set(new_order) != set(range(len(current_deck.slides))):
            raise ValueError("Invalid reorder: invalid indices")

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

        # Update slide
        current_deck.slides[index] = Slide(html=html, slide_id=f"slide_{index}")

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
