"""Chat service wrapper around the agent.

Phase 1: Single global session, stored in memory.
Phase 4: Support multiple sessions with session_id parameter.
"""

import logging
from typing import Any, Dict, Optional

from src.models.slide_deck import SlideDeck
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

