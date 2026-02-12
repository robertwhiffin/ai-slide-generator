"""Request schemas for the API."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SlideContext(BaseModel):
    """Context about selected slides for editing."""

    indices: list[int] = Field(
        ...,
        description="Contiguous list of slide indices (0-based) to edit",
        min_length=1,
    )
    slide_htmls: list[str] = Field(
        ...,
        description="HTML content of selected slides in order",
        min_length=1,
    )

    @field_validator("indices")
    @classmethod
    def validate_contiguous(cls, value: list[int]) -> list[int]:
        """Ensure indices are contiguous and sorted."""
        if not value:
            raise ValueError("At least one slide index is required")

        sorted_indices = sorted(value)
        for idx in range(len(sorted_indices) - 1):
            if sorted_indices[idx + 1] - sorted_indices[idx] != 1:
                raise ValueError("Slide indices must be contiguous")

        if value != sorted_indices:
            raise ValueError("Slide indices must be provided in ascending order")

        return value

    @model_validator(mode="after")
    def validate_lengths(self) -> "SlideContext":
        """Ensure number of slide HTML blocks matches number of indices."""
        if len(self.indices) != len(self.slide_htmls):
            raise ValueError("Number of slide_htmls must match number of indices")
        return self


class ChatRequest(BaseModel):
    """Request model for chat endpoint.

    Attributes:
        session_id: Session ID (required, create via POST /api/sessions)
        message: User's natural language message
        slide_context: Optional context for slide editing
    """

    session_id: str = Field(
        ...,
        description="Session ID (required, create via POST /api/sessions first)",
        min_length=1,
    )
    message: str = Field(
        ...,
        description="Natural language message to the AI agent",
        min_length=1,
    )
    slide_context: Optional[SlideContext] = Field(
        default=None,
        description="Optional context containing the slides to edit",
    )
    image_ids: Optional[list[int]] = Field(
        default=None,
        description="IDs of images attached to this message (from upload or paste)",
    )

    @field_validator("message")
    @classmethod
    def validate_message_not_whitespace(cls, value: str) -> str:
        """Validate message is not just whitespace."""
        if not value.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return value

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "session_id": "abc123xyz",
                "message": "Create slides about Q3 sales performance",
                "slide_context": {
                    "indices": [1, 2],
                    "slide_htmls": [
                        "<div class=\"slide\">...</div>",
                        "<div class=\"slide\">...</div>",
                    ],
                },
            }
        }


class CreateSessionRequest(BaseModel):
    """Request model for creating a new session."""

    user_id: Optional[str] = Field(
        default=None,
        description="Optional user identifier for session isolation",
    )
    title: Optional[str] = Field(
        default=None,
        description="Optional session title",
        max_length=255,
    )
    profile_id: Optional[int] = Field(
        default=None,
        description="Profile ID to associate this session with",
    )
    profile_name: Optional[str] = Field(
        default=None,
        description="Profile name (cached for display)",
    )
