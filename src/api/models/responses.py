"""Response models for the API.

Phase 1: Return messages, slide_deck, and metadata.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """Individual chat message for UI display.
    
    Attributes:
        role: Message role (user, assistant, tool)
        content: Message content
        timestamp: ISO timestamp
        tool_call: Optional tool call information
        tool_call_id: Optional tool call identifier
    """
    
    role: str = Field(
        ...,
        description="Message role",
        pattern="^(user|assistant|tool)$",
    )
    content: str = Field(
        ...,
        description="Message content",
    )
    timestamp: str = Field(
        ...,
        description="ISO timestamp",
    )
    tool_call: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Tool call information (name, arguments)",
    )
    tool_call_id: Optional[str] = Field(
        default=None,
        description="Tool call identifier",
    )


class ChatResponse(BaseModel):
    """Response from chat endpoint.
    
    Attributes:
        messages: List of all messages in the conversation
        slide_deck: Parsed slide deck structure (if generated)
        metadata: Execution metadata (latency, tool_calls, etc.)
    """
    
    messages: List[MessageResponse] = Field(
        ...,
        description="All messages from the conversation turn",
    )
    slide_deck: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parsed slide deck structure",
    )
    metadata: Dict[str, Any] = Field(
        ...,
        description="Execution metadata",
    )
    
    class Config:
        """Pydantic model configuration."""
        
        json_schema_extra = {
            "example": {
                "messages": [
                    {
                        "role": "user",
                        "content": "Create slides about Q3 sales",
                        "timestamp": "2024-01-01T12:00:00Z",
                    },
                    {
                        "role": "assistant",
                        "content": "Using tool: query_genie_space",
                        "timestamp": "2024-01-01T12:00:01Z",
                        "tool_call": {
                            "name": "query_genie_space",
                            "arguments": {"query": "Q3 sales data"},
                        },
                    },
                ],
                "slide_deck": {
                    "title": "Q3 Sales Performance",
                    "slide_count": 3,
                    "slides": [],
                },
                "metadata": {
                    "latency_seconds": 2.5,
                    "tool_calls": 1,
                },
            }
        }

