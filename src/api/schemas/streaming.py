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
    SESSION_CREATED = "session_created"  # New session created on first message
    SLIDE_READY = "slide_ready"  # One committed slide released by the reorder buffer


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
        position: 0-based slide position (for slide_ready events)
        html: One slide's body HTML (for slide_ready events)
        scripts: One slide's per-slide JavaScript (for slide_ready events)
        agent: Which agent produced this event's subject (§7.3 attribution)
        slide_cursor: The next position not yet released (for slide_ready events)
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
    session_id: Optional[str] = Field(default=None, description="Session ID (for session_created events)")
    # ws4d D3 — incremental slide delivery.  `position`/`html`/`scripts` are the
    # payload the spec (§6.2) puts on a `slide_ready` event; `agent` is §7.3's
    # attribution; `slide_cursor` tells the client the next position it has NOT
    # yet been sent, so an SSE consumer that later falls back to polling can hand
    # the same number to `GET /chat/poll`'s `slide_cursor` query parameter.
    position: Optional[int] = Field(default=None, description="0-based slide position")
    html: Optional[str] = Field(default=None, description="One slide's body HTML")
    # `scripts: str = ""`, NOT `Optional[str] = None`.  "No per-slide JavaScript"
    # already has exactly one spelling everywhere else in the slide chain —
    # `SlideWriter.write_slide(scripts: str = "")`, `commit_placeholder`'s
    # `scripts=""`, and the backfill's `slide_dict.get("scripts") or ""` — so a
    # second spelling here would make every consumer handle both.
    scripts: str = Field(default="", description="One slide's per-slide JavaScript")
    agent: Optional[str] = Field(default=None, description="Agent this event is attributed to")
    slide_cursor: Optional[int] = Field(
        default=None, description="Next slide position not yet released"
    )

    def to_sse(self) -> str:
        """Format event as SSE data line.

        Returns:
            SSE-formatted string with event type and JSON data
        """
        return f"event: {self.type.value}\ndata: {self.model_dump_json()}\n\n"

