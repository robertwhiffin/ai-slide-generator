"""Slide Deck Prompt Library model.

This model stores reusable presentation-specific prompts that guide
the agent in creating specific types of slide decks (e.g., "Consumption
Review Deck", "Quarterly Business Review").

These are distinct from the system prompts which control slide styling
and formatting - deck prompts control WHAT content to include and HOW
to structure the narrative for a specific presentation type.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from src.core.database import Base


class SlideDeckPromptLibrary(Base):
    """Global library of slide deck prompts.
    
    Each entry represents a reusable template for a specific type of
    presentation. Profiles can optionally select one of these prompts
    to guide the agent's content generation.
    """

    __tablename__ = "slide_deck_prompt_library"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)  # e.g., "Review", "Report", "Analysis"
    prompt_content = Column(Text, nullable=False)
    
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<SlideDeckPromptLibrary(id={self.id}, name='{self.name}', category='{self.category}')>"

