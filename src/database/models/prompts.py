"""Prompts configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship

from src.core.database import Base


class ConfigPrompts(Base):
    """Prompts configuration.
    
    Contains:
    - Reference to optional slide deck prompt from the global library (WHAT to create)
    - Reference to optional slide style from the global library (HOW it should look)

    The former ``system_prompt`` / ``slide_editing_instructions`` override columns are
    RETIRED: prompts are assembled from ``src.core.prompt_modules`` and a per-profile
    override no longer takes effect. The ORM declarations are removed here BEFORE the
    physical ``DROP COLUMN`` so no ``db.query(ConfigPrompts)`` ever names a dropped
    column (``create_all()`` only creates missing TABLES and would not re-add one).
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

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile = relationship("ConfigProfile", back_populates="prompts")
    selected_deck_prompt = relationship("SlideDeckPromptLibrary")
    selected_slide_style = relationship("SlideStyleLibrary")

    def __repr__(self):
        return f"<ConfigPrompts(id={self.id}, profile_id={self.profile_id}, deck_prompt_id={self.selected_deck_prompt_id}, style_id={self.selected_slide_style_id})>"

