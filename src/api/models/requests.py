"""Request models for the API.

Phase 1: Simple chat request with message and max_slides.
Phase 4: Add session_id support.
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request model for chat endpoint.
    
    Attributes:
        message: User's natural language message
        max_slides: Maximum number of slides to generate
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
    
    class Config:
        """Pydantic model configuration."""
        
        json_schema_extra = {
            "example": {
                "message": "Create slides about Q3 sales performance",
                "max_slides": 5,
            }
        }

