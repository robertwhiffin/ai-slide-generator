"""Chat service wrapper around the agent.

Phase 1: Single global session, stored in memory.
Phase 4: Support multiple sessions with session_id parameter and configuration reload.

Token Optimization (Nov 2025):
- Added support for two-stage generator via USE_TWO_STAGE_GENERATOR flag
- Set USE_TWO_STAGE_GENERATOR=true to enable optimized generation
- Two-stage reduces token usage by 70-80% while maintaining quality
"""

import copy
import logging
import os
import sys
import threading
from typing import Any, Dict, List, Optional

from src.models.slide import Slide
from src.models.slide_deck import SlideDeck
from src.services.agent import create_agent
from src.utils.html_utils import (
    extract_canvas_ids_from_html,
    extract_canvas_ids_from_script,
)

# Set up logging to ensure our messages are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Feature flag for two-stage generator
USE_TWO_STAGE_GENERATOR = os.getenv("USE_TWO_STAGE_GENERATOR", "true").lower() == "true"

# Log the feature flag value immediately
print(f"[ChatService] USE_TWO_STAGE_GENERATOR = {USE_TWO_STAGE_GENERATOR}", flush=True)

logger = logging.getLogger(__name__)


def validate_canvas_scripts(
    canvas_ids: List[str],
    script_text: str,
    existing_scripts: str,
) -> None:
    """
    
    Ensure every canvas id has a corresponding initialization script.

    Raises:
        ValueError: If any canvas lacks an associated script.
    """
    if not canvas_ids:
        return

    missing: list[str] = []
    for canvas_id in canvas_ids:
        if canvas_id in existing_scripts:
            continue
        if script_text and canvas_id in script_text:
            continue
        missing.append(canvas_id)

    if missing:
        raise ValueError(
            "Missing Chart.js initialization for canvas ids: "
            f"{', '.join(missing)}. Include a <script data-slide-scripts> block "
            "with document.getElementById('<id>') for each canvas."
        )


class ChatService:
    """Service for managing chat interactions with the AI agent.
    
    Phase 1: Maintains a single session for the application lifetime.
    Phase 4: Will support multiple sessions with persistence.
    
    Token Optimization:
        Set USE_TWO_STAGE_GENERATOR=true to use the optimized two-stage architecture
        that reduces token usage by 70-80%.
    
    Attributes:
        agent: SlideGeneratorAgent or TwoStageSlideGenerator instance
        session_id: Current session ID (Phase 1: single session)
        current_deck: Current parsed slide deck
        raw_html: Raw HTML from AI (for debugging)
        use_two_stage: Whether using the optimized two-stage generator
    """

    def __init__(self):
        """Initialize the chat service with agent and session."""
        logger.info("Initializing ChatService")

        # Thread lock for safe agent reloading
        self._reload_lock = threading.Lock()

        # Check if using two-stage generator
        self.use_two_stage = USE_TWO_STAGE_GENERATOR
        
        if self.use_two_stage:
            logger.info("Using TWO-STAGE generator (token optimized)")
            from src.services.two_stage_generator import create_two_stage_generator
            self.agent = create_two_stage_generator()
        else:
            logger.info("Using STANDARD agent (LangChain)")
            self.agent = create_agent()

        # Phase 1: Create single session on startup
        self.session_id = self.agent.create_session()
        logger.info(
            "Created single session",
            extra={
                "session_id": self.session_id,
                "generator_type": "two_stage" if self.use_two_stage else "standard",
            },
        )

        # Store current slide deck and raw HTML
        self.current_deck: Optional[SlideDeck] = None
        self.raw_html: Optional[str] = None

        logger.info(
            "ChatService initialized successfully",
            extra={"generator_type": "two_stage" if self.use_two_stage else "standard"},
        )

    def reload_agent(self, profile_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Reload agent with new settings from database.
        
        This allows hot-reload of configuration without restarting the application.
        Session state (conversation history and Genie conversations) is preserved.
        
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
                extra={"profile_id": profile_id, "current_session_id": self.session_id},
            )

            try:
                # Save current session state
                sessions_backup = copy.deepcopy(self.agent.sessions)
                logger.info(
                    "Backed up session state",
                    extra={"session_count": len(sessions_backup)},
                )

                # Reload settings from database
                # This will update the settings cache
                from src.config.settings_db import reload_settings
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

                # Clear Genie conversation IDs from sessions (they're tied to the old space)
                # This forces creation of new conversations in the new Genie space
                for session_id, session in sessions_backup.items():
                    if "genie_conversation_id" in session:
                        logger.info(
                            "Clearing Genie conversation ID for session",
                            extra={
                                "session_id": session_id,
                                "old_conversation_id": session["genie_conversation_id"],
                            },
                        )
                        session["genie_conversation_id"] = None

                # Create new agent with new settings (respecting the flag)
                if USE_TWO_STAGE_GENERATOR:
                    from src.services.two_stage_generator import create_two_stage_generator
                    new_agent = create_two_stage_generator()
                    logger.info("Created new TWO-STAGE agent instance")
                else:
                    new_agent = create_agent()
                    logger.info("Created new STANDARD agent instance")

                # Restore sessions (with cleared Genie conversation IDs)
                new_agent.sessions = sessions_backup
                logger.info(
                    "Restored session state with cleared Genie conversations",
                    extra={"session_count": len(new_agent.sessions)},
                )

                # Atomic swap
                self.agent = new_agent

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
                    "sessions_preserved": len(sessions_backup),
                }

            except Exception as e:
                logger.error(
                    f"Failed to reload agent: {e}",
                    exc_info=True,
                    extra={"profile_id": profile_id},
                )
                # Agent remains in previous state if reload fails
                raise Exception(f"Agent reload failed: {e}") from e

    def send_message(
        self,
        message: str,
        max_slides: int = 10,
        slide_context: Optional[Dict[str, Any]] = None,
        # session_id: Optional[str] = None,  # For Phase 4
    ) -> Dict[str, Any]:
        """Send a message to the agent and get response.
        
        Args:
            message: User's message
            max_slides: Maximum number of slides to generate
            # session_id: Optional session ID (Phase 4)
        
        Returns:
            Dictionary containing:
                - messages: List of message dicts for UI display
                - slide_deck: Parsed slide deck dict (if generated)
                - metadata: Execution metadata
        
        Raises:
            Exception: If agent fails to generate slides
        """
        logger.info(
            "Processing message",
            extra={
                "message_length": len(message),
                "max_slides": max_slides,
                "session_id": self.session_id,
                "has_slide_context": slide_context is not None,
            },
        )

        try:
            # Call agent to generate slides
            # Phase 1: Use single session_id
            # Phase 4: Use provided session_id or create new one
            result = self.agent.generate_slides(
                question=message,
                session_id=self.session_id,
                max_slides=max_slides,
                slide_context=slide_context,
            )

            html_output = result.get("html")
            replacement_info = result.get("replacement_info")

            if slide_context and replacement_info:
                slide_deck_dict = self._apply_slide_replacements(result["parsed_output"])
                # Store knitted HTML for debugging
                if self.current_deck:
                    self.raw_html = self.current_deck.knit()
            elif html_output and html_output.strip():
                self.raw_html = html_output

                try:
                    self.current_deck = SlideDeck.from_html_string(html_output)
                    slide_deck_dict = self.current_deck.to_dict()
                    logger.info(
                        "Parsed slide deck",
                        extra={
                            "slide_count": len(self.current_deck.slides),
                            "title": self.current_deck.title,
                        },
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to parse HTML into SlideDeck: {e}",
                        exc_info=True,
                    )
                    self.current_deck = None
                    slide_deck_dict = None
            else:
                self.raw_html = None
                slide_deck_dict = None

            # Build response
            response = {
                "messages": result["messages"],
                "slide_deck": slide_deck_dict,
                "raw_html": self.raw_html,  # Include raw HTML for debugging
                "metadata": result["metadata"],
                "replacement_info": replacement_info,
            }

            logger.info(
                "Message processed successfully",
                extra={
                    "message_count": len(response["messages"]),
                    "has_slide_deck": response["slide_deck"] is not None,
                },
            )

            return response

        except Exception as e:
            logger.error(f"Failed to process message: {e}", exc_info=True)
            raise

    def _apply_slide_replacements(
        self,
        replacement_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply slide replacements to the current slide deck.

        Handles variable-length replacements by removing the original block
        and inserting the new slides at the same start index.
        """
        if self.current_deck is None:
            raise ValueError("No current deck to apply replacements to")

        start_idx = replacement_info["start_index"]
        original_count = replacement_info["original_count"]
        replacement_slides = replacement_info["replacement_slides"]
        replacement_scripts = replacement_info.get("replacement_scripts", "")
        canvas_ids = replacement_info.get("canvas_ids", [])
        script_canvas_ids = replacement_info.get("script_canvas_ids")

        # Check that the start index for replacement is within the valid range of the slide deck
        if start_idx < 0 or start_idx >= len(self.current_deck.slides):
            raise ValueError(f"Start index {start_idx} out of range")
        # Ensure that the range of slides to be replaced does not exceed the available slides in the deck
        if start_idx + original_count > len(self.current_deck.slides):
            raise ValueError("Replacement range exceeds deck size")

        validate_canvas_scripts(
            canvas_ids=canvas_ids,
            script_text=replacement_scripts,
            existing_scripts=self.current_deck.scripts or "",
        )

        outgoing_canvas_ids: list[str] = []
        for offset in range(original_count):
            slide_html = self.current_deck.slides[start_idx + offset].html
            outgoing_canvas_ids.extend(extract_canvas_ids_from_html(slide_html))

        if outgoing_canvas_ids:
            self.current_deck.remove_canvas_scripts(outgoing_canvas_ids)

        for _ in range(original_count):
            self.current_deck.remove_slide(start_idx)

        logger.info(
            "Removed slides for replacement",
            extra={"count": original_count, "start_index": start_idx},
        )

        for idx, slide_html in enumerate(replacement_slides):
            new_slide = Slide(
                html=slide_html,
                slide_id=f"slide_{start_idx + idx}",
            )
            self.current_deck.insert_slide(new_slide, start_idx + idx)

        logger.info(
            "Inserted replacement slides",
            extra={
                "replacement_count": len(replacement_slides),
                "net_change": len(replacement_slides) - original_count,
                "start_index": start_idx,
            },
        )

        replacement_script_canvas_ids = script_canvas_ids or extract_canvas_ids_from_script(
            replacement_scripts
        )

        if replacement_script_canvas_ids:
            self.current_deck.remove_canvas_scripts(replacement_script_canvas_ids)

        self._append_replacement_scripts(
            replacement_scripts,
            replacement_script_canvas_ids,
        )

        return self.current_deck.to_dict()

    def _append_replacement_scripts(
        self,
        script_text: str,
        script_canvas_ids: Optional[List[str]] = None,
    ) -> None:
        """Append or replace validated replacement scripts on the deck."""
        if not self.current_deck:
            return

        if not script_text or not script_text.strip():
            return

        canvas_ids = script_canvas_ids or []
        self.current_deck.add_script_block(script_text, canvas_ids)

    def get_slides(self) -> Optional[Dict[str, Any]]:
        """Get current slide deck.
        
        Phase 4: Add session_id parameter
        
        Returns:
            Slide deck dictionary or None if no slides exist
        """
        if not self.current_deck:
            return None
        return self.current_deck.to_dict()

    def reorder_slides(self, new_order: List[int]) -> Dict[str, Any]:
        """Reorder slides based on new index order.
        
        Args:
            new_order: List of indices in new order (e.g. [2, 0, 1])
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Updated slide deck
        
        Raises:
            ValueError: If no slide deck exists or invalid reorder
        """
        if not self.current_deck:
            raise ValueError("No slide deck available")

        # Validate indices
        if len(new_order) != len(self.current_deck.slides):
            raise ValueError("Invalid reorder: wrong number of indices")

        if set(new_order) != set(range(len(self.current_deck.slides))):
            raise ValueError("Invalid reorder: invalid indices")

        # Reorder slides
        new_slides = [self.current_deck.slides[i] for i in new_order]
        self.current_deck.slides = new_slides

        # Update indices
        for idx, slide in enumerate(self.current_deck.slides):
            slide.slide_id = f"slide_{idx}"

        logger.info(
            "Reordered slides",
            extra={"new_order": new_order, "session_id": self.session_id},
        )

        return self.current_deck.to_dict()

    def update_slide(self, index: int, html: str) -> Dict[str, Any]:
        """Update a single slide's HTML.
        
        Args:
            index: Slide index to update
            html: New HTML content (must include <div class="slide">)
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Updated slide information
        
        Raises:
            ValueError: If no slide deck exists, invalid index, or invalid HTML
        """
        if not self.current_deck:
            raise ValueError("No slide deck available")

        if index < 0 or index >= len(self.current_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")

        # Validate HTML has slide wrapper
        if '<div class="slide"' not in html:
            raise ValueError("HTML must contain <div class='slide'> wrapper")

        # Update slide
        self.current_deck.slides[index] = Slide(html=html, slide_id=f"slide_{index}")

        logger.info(
            "Updated slide",
            extra={"index": index, "session_id": self.session_id},
        )

        return {
            "index": index,
            "slide_id": f"slide_{index}",
            "html": html
        }

    def duplicate_slide(self, index: int) -> Dict[str, Any]:
        """Duplicate a slide.
        
        Args:
            index: Slide index to duplicate
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Updated slide deck
        
        Raises:
            ValueError: If no slide deck exists or invalid index
        """
        if not self.current_deck:
            raise ValueError("No slide deck available")

        if index < 0 or index >= len(self.current_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")

        # Clone slide
        cloned = self.current_deck.slides[index].clone()

        # Insert after original
        self.current_deck.insert_slide(cloned, index + 1)

        # Update slide IDs
        for idx, slide in enumerate(self.current_deck.slides):
            slide.slide_id = f"slide_{idx}"

        logger.info(
            "Duplicated slide",
            extra={"index": index, "new_count": len(self.current_deck.slides), "session_id": self.session_id},
        )

        return self.current_deck.to_dict()

    def delete_slide(self, index: int) -> Dict[str, Any]:
        """Delete a slide.
        
        Args:
            index: Slide index to delete
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Updated slide deck
        
        Raises:
            ValueError: If no slide deck exists, invalid index, or deleting last slide
        """
        if not self.current_deck:
            raise ValueError("No slide deck available")

        if index < 0 or index >= len(self.current_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")

        if len(self.current_deck.slides) <= 1:
            raise ValueError("Cannot delete last slide")

        # Remove slide
        self.current_deck.remove_slide(index)

        # Update slide IDs
        for idx, slide in enumerate(self.current_deck.slides):
            slide.slide_id = f"slide_{idx}"

        logger.info(
            "Deleted slide",
            extra={"index": index, "new_count": len(self.current_deck.slides), "session_id": self.session_id},
        )

        return self.current_deck.to_dict()


# Phase 1: Create global service instance
# Phase 4: Move to dependency injection with session management
_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get the global ChatService instance (Phase 1).
    
    Phase 1: Single global instance created on first call.
    Phase 4: Replace with proper dependency injection.
    
    Returns:
        ChatService instance
    """
    global _chat_service_instance

    if _chat_service_instance is None:
        _chat_service_instance = ChatService()

    return _chat_service_instance

