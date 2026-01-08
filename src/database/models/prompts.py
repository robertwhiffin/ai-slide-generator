"""Prompts configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from src.core.database import Base


class ConfigPrompts(Base):
    """Prompts configuration.
    
    Contains:
    - Reference to optional slide deck prompt from the global library (WHAT to create)
    - Reference to optional slide style from the global library (HOW it should look)
    - Advanced settings (system_prompt, slide_editing_instructions) for power users/debug mode
    """

    __tablename__ = "config_prompts"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Optional reference to a slide deck prompt from the global library
    selected_deck_prompt_id = Column(
        Integer, 
        ForeignKey("slide_deck_prompt_library.id", ondelete="SET NULL"), 
        nullable=True
    )

    # Optional reference to a slide style from the global library
    selected_slide_style_id = Column(
        Integer,
        ForeignKey("slide_style_library.id", ondelete="SET NULL"),
        nullable=True
    )

    # Advanced settings - system-level prompts for slide generation (hidden from regular users)
    system_prompt = Column(Text, nullable=False)
    slide_editing_instructions = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile = relationship("ConfigProfile", back_populates="prompts")
    selected_deck_prompt = relationship("SlideDeckPromptLibrary")
    selected_slide_style = relationship("SlideStyleLibrary")

    def __repr__(self):
        return f"<ConfigPrompts(id={self.id}, profile_id={self.profile_id}, deck_prompt_id={self.selected_deck_prompt_id}, style_id={self.selected_slide_style_id})>"

