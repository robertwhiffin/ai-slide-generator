"""Chat service wrapper around the agent.

Phase 1: Single global session, stored in memory.
Phase 4: Support multiple sessions with session_id parameter.
"""

import logging
from typing import Any, Dict, List, Optional

from src.models.slide_deck import SlideDeck
from src.models.slide import Slide
from src.services.agent import create_agent

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat interactions with the AI agent.
    
    Phase 1: Maintains a single session for the application lifetime.
    Phase 4: Will support multiple sessions with persistence.
    
    Attributes:
        agent: SlideGeneratorAgent instance
        session_id: Current session ID (Phase 1: single session)
        slide_deck: Current parsed slide deck
    """
    
    def __init__(self):
        """Initialize the chat service with agent and session."""
        logger.info("Initializing ChatService")
        
        # Create agent instance
        self.agent = create_agent()
        
        # Phase 1: Create single session on startup
        self.session_id = self.agent.create_session()
        logger.info("Created single session", extra={"session_id": self.session_id})
        
        # Store current slide deck
        self.slide_deck: Optional[SlideDeck] = None
        
        logger.info("ChatService initialized successfully")
    
    def send_message(
        self,
        message: str,
        max_slides: int = 10,
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
            )
            
            # Parse HTML into SlideDeck if present
            html_output = result.get("html")
            if html_output and html_output.strip():
                try:
                    self.slide_deck = SlideDeck.from_html_string(html_output)
                    logger.info(
                        "Parsed slide deck",
                        extra={
                            "slide_count": len(self.slide_deck.slides),
                            "title": self.slide_deck.title,
                        },
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to parse HTML into SlideDeck: {e}",
                        exc_info=True,
                    )
                    # Continue without parsed slide deck
                    self.slide_deck = None
            
            # Build response
            response = {
                "messages": result["messages"],
                "slide_deck": self.slide_deck.to_dict() if self.slide_deck else None,
                "metadata": result["metadata"],
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
    
    def get_slides(self) -> Optional[Dict[str, Any]]:
        """Get current slide deck.
        
        Phase 4: Add session_id parameter
        
        Returns:
            Slide deck dictionary or None if no slides exist
        """
        if not self.slide_deck:
            return None
        return self.slide_deck.to_dict()
    
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
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        # Validate indices
        if len(new_order) != len(self.slide_deck.slides):
            raise ValueError("Invalid reorder: wrong number of indices")
        
        if set(new_order) != set(range(len(self.slide_deck.slides))):
            raise ValueError("Invalid reorder: invalid indices")
        
        # Reorder slides
        new_slides = [self.slide_deck.slides[i] for i in new_order]
        self.slide_deck.slides = new_slides
        
        # Update indices
        for idx, slide in enumerate(self.slide_deck.slides):
            slide.slide_id = f"slide_{idx}"
        
        logger.info(
            "Reordered slides",
            extra={"new_order": new_order, "session_id": self.session_id},
        )
        
        return self.slide_deck.to_dict()
    
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
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        if index < 0 or index >= len(self.slide_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")
        
        # Validate HTML has slide wrapper
        if '<div class="slide"' not in html:
            raise ValueError("HTML must contain <div class='slide'> wrapper")
        
        # Update slide
        self.slide_deck.slides[index] = Slide(html=html, slide_id=f"slide_{index}")
        
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
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        if index < 0 or index >= len(self.slide_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")
        
        # Clone slide
        cloned = self.slide_deck.slides[index].clone()
        
        # Insert after original
        self.slide_deck.insert_slide(cloned, index + 1)
        
        # Update slide IDs
        for idx, slide in enumerate(self.slide_deck.slides):
            slide.slide_id = f"slide_{idx}"
        
        logger.info(
            "Duplicated slide",
            extra={"index": index, "new_count": len(self.slide_deck.slides), "session_id": self.session_id},
        )
        
        return self.slide_deck.to_dict()
    
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
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        if index < 0 or index >= len(self.slide_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")
        
        if len(self.slide_deck.slides) <= 1:
            raise ValueError("Cannot delete last slide")
        
        # Remove slide
        self.slide_deck.remove_slide(index)
        
        # Update slide IDs
        for idx, slide in enumerate(self.slide_deck.slides):
            slide.slide_id = f"slide_{idx}"
        
        logger.info(
            "Deleted slide",
            extra={"index": index, "new_count": len(self.slide_deck.slides), "session_id": self.session_id},
        )
        
        return self.slide_deck.to_dict()


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

