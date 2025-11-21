"""Request models for the API."""

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
        message: User's natural language message
        max_slides: Maximum number of slides to generate
        slide_context: Optional context for slide editing
        # session_id: Optional[str] = None  # For Phase 4
    """

    message: str = Field(
        ...,
        description="Natural language message to the AI agent",
        min_length=1,
        max_length=5000,
    )
    max_slides: int = Field(
        default=10,
        description="Maximum number of slides to generate",
        ge=1,
        le=50,
    )
    slide_context: Optional[SlideContext] = Field(
        default=None,
        description="Optional context containing the slides to edit",
    )

    class Config:
        """Pydantic model configuration."""

        json_schema_extra = {
            "example": {
                "message": "Create slides about Q3 sales performance",
                "max_slides": 5,
                "slide_context": {
                    "indices": [1, 2],
                    "slide_htmls": [
                        "<div class=\"slide\">...</div>",
                        "<div class=\"slide\">...</div>",
                    ],
                },
            }
        }
