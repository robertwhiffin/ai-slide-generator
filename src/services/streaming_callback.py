"""Streaming callback handler for real-time SSE events and message persistence.

This callback handler:
1. Emits SSE events to a queue for real-time streaming to the client
2. Persists all messages to the database for conversation history
"""

import json
import logging
import queue
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.api.schemas.streaming import StreamEvent, StreamEventType

if TYPE_CHECKING:
    from src.api.services.session_manager import SessionManager

logger = logging.getLogger(__name__)


class StreamingCallbackHandler(BaseCallbackHandler):
    """Callback that emits SSE events AND persists messages to database.

    This handler intercepts LLM and tool events from LangChain and:
    - Puts events into a queue for SSE streaming
    - Persists messages to the database for history

    Attributes:
        event_queue: Queue to push events for SSE streaming
        session_id: Session identifier for database persistence
    """

    def __init__(self, event_queue: queue.Queue, session_id: str):
        """Initialize the streaming callback handler.

        Args:
            event_queue: Queue to push StreamEvent objects
            session_id: Session ID for database persistence
        """
        super().__init__()
        self.event_queue = event_queue
        self.session_id = session_id
        self._session_manager = None
        self._current_tool_name: Optional[str] = None

    @property
    def session_manager(self) -> "SessionManager":
        """Lazily get session manager to avoid circular imports."""
        if self._session_manager is None:
            from src.api.services.session_manager import get_session_manager
            self._session_manager = get_session_manager()
        return self._session_manager

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Handle LLM completion - emit assistant message.

        Args:
            response: LLM result containing generated text
            **kwargs: Additional arguments from LangChain
        """
        logger.info("on_llm_end called", extra={"has_generations": bool(response.generations)})
        
        if not response.generations:
            return

        # Get the text from the first generation
        text = response.generations[0][0].text if response.generations[0] else ""
        
        logger.info("LLM response text", extra={"text_length": len(text) if text else 0})

        if not text or not text.strip():
            return

        # Persist to database
        try:
            msg = self.session_manager.add_message(
                session_id=self.session_id,
                role="assistant",
                content=text,
                message_type="llm_response",
            )
            message_id = msg.get("id")
        except Exception as e:
            logger.error(f"Failed to persist LLM response: {e}")
            message_id = None

        # Emit SSE event
        event = StreamEvent(
            type=StreamEventType.ASSISTANT,
            content=text,
            message_id=message_id,
        )
        self.event_queue.put(event)

        logger.debug(
            "Emitted assistant event",
            extra={"content_length": len(text), "message_id": message_id},
        )

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Handle tool invocation start.

        Args:
            serialized: Serialized tool information
            input_str: Tool input as string
            **kwargs: Additional arguments from LangChain
        """
        tool_name = serialized.get("name", "unknown")
        self._current_tool_name = tool_name
        logger.info("on_tool_start called", extra={"tool_name": tool_name})

        # Parse tool input if it's JSON
        try:
            tool_input = json.loads(input_str) if input_str else {}
        except json.JSONDecodeError:
            tool_input = {"query": input_str}

        # Persist to database
        try:
            msg = self.session_manager.add_message(
                session_id=self.session_id,
                role="assistant",
                content=f"Calling {tool_name}",
                message_type="tool_call",
                metadata={"tool_name": tool_name, "tool_input": tool_input},
            )
            message_id = msg.get("id")
        except Exception as e:
            logger.error(f"Failed to persist tool call: {e}")
            message_id = None

        # Emit SSE event
        event = StreamEvent(
            type=StreamEventType.TOOL_CALL,
            tool_name=tool_name,
            tool_input=tool_input,
            message_id=message_id,
        )
        self.event_queue.put(event)

        logger.debug(
            "Emitted tool_call event",
            extra={"tool_name": tool_name, "message_id": message_id},
        )

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Handle tool completion.

        Args:
            output: Tool output as string
            **kwargs: Additional arguments from LangChain
        """
        # Truncate long outputs for display
        preview = output[:500] + "..." if len(output) > 500 else output

        # Persist to database
        try:
            msg = self.session_manager.add_message(
                session_id=self.session_id,
                role="tool",
                content=preview,
                message_type="tool_result",
                metadata={"tool_name": self._current_tool_name, "full_length": len(output)},
            )
            message_id = msg.get("id")
        except Exception as e:
            logger.error(f"Failed to persist tool result: {e}")
            message_id = None

        # Emit SSE event
        event = StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            tool_name=self._current_tool_name,
            tool_output=preview,
            message_id=message_id,
        )
        self.event_queue.put(event)

        logger.debug(
            "Emitted tool_result event",
            extra={"output_length": len(output), "message_id": message_id},
        )

        self._current_tool_name = None

    def on_chain_error(self, error: Exception, **kwargs: Any) -> None:
        """Handle chain/agent error.

        Args:
            error: Exception that occurred
            **kwargs: Additional arguments from LangChain
        """
        error_message = str(error)

        # Emit error event (don't persist errors to message history)
        event = StreamEvent(
            type=StreamEventType.ERROR,
            error=error_message,
        )
        self.event_queue.put(event)

        logger.error(
            "Emitted error event",
            extra={"error": error_message},
        )

    def on_tool_error(self, error: Exception, **kwargs: Any) -> None:
        """Handle tool execution error.

        Args:
            error: Exception from tool execution
            **kwargs: Additional arguments from LangChain
        """
        error_message = f"Tool error: {str(error)}"

        event = StreamEvent(
            type=StreamEventType.ERROR,
            error=error_message,
            tool_name=self._current_tool_name,
        )
        self.event_queue.put(event)

        logger.error(
            "Emitted tool error event",
            extra={"error": error_message, "tool_name": self._current_tool_name},
        )

        self._current_tool_name = None

    def emit_complete(
        self,
        slides: Optional[Dict[str, Any]] = None,
        raw_html: Optional[str] = None,
        replacement_info: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit completion event with final results.

        This should be called after agent execution completes.

        Args:
            slides: Final slide deck dictionary
            raw_html: Raw HTML output
            replacement_info: Slide replacement information
            metadata: Execution metadata
        """
        event = StreamEvent(
            type=StreamEventType.COMPLETE,
            slides=slides,
            raw_html=raw_html,
            replacement_info=replacement_info,
            metadata=metadata,
        )
        self.event_queue.put(event)

        logger.info(
            "Emitted complete event",
            extra={
                "has_slides": slides is not None,
                "has_replacement_info": replacement_info is not None,
            },
        )

