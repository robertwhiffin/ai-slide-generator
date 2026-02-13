"""SSE streaming event types for real-time chat updates.

These schemas define the events emitted during agent execution for
real-time progress display in the frontend.
"""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class StreamEventType(str, Enum):
    """Types of events emitted during streaming generation."""

    ASSISTANT = "assistant"  # LLM text response
    TOOL_CALL = "tool_call"  # Tool invocation started
    TOOL_RESULT = "tool_result"  # Tool returned result
    ERROR = "error"  # Error occurred
    COMPLETE = "complete"  # Generation finished
    SESSION_TITLE = "session_title"  # Auto-generated session title


class StreamEvent(BaseModel):
    """SSE event payload for streaming chat updates.

    Attributes:
        type: Event type
        content: Text content (for assistant messages)
        tool_name: Tool being called (for tool_call events)
        tool_input: Tool input arguments (for tool_call events)
        tool_output: Tool result (for tool_result events)
        slides: Slide deck data (for complete event)
        error: Error message (for error events)
        message_id: Database ID of persisted message
    """

    type: StreamEventType = Field(..., description="Event type")
    content: Optional[str] = Field(default=None, description="Text content")
    tool_name: Optional[str] = Field(default=None, description="Tool name")
    tool_input: Optional[Dict[str, Any]] = Field(default=None, description="Tool input")
    tool_output: Optional[str] = Field(default=None, description="Tool output")
    slides: Optional[Dict[str, Any]] = Field(default=None, description="Slide deck")
    error: Optional[str] = Field(default=None, description="Error message")
    message_id: Optional[int] = Field(default=None, description="Persisted message ID")
    raw_html: Optional[str] = Field(default=None, description="Raw HTML output")
    replacement_info: Optional[Dict[str, Any]] = Field(
        default=None, description="Slide replacement info"
    )
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Execution metadata")
    experiment_url: Optional[str] = Field(default=None, description="MLflow experiment URL")
    session_title: Optional[str] = Field(default=None, description="Auto-generated session title")

    def to_sse(self) -> str:
        """Format event as SSE data line.

        Returns:
            SSE-formatted string with event type and JSON data
        """
        return f"event: {self.type.value}\ndata: {self.model_dump_json()}\n\n"

