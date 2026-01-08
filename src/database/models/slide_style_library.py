"""Slide Style Library model.

This model stores reusable slide styling configurations that control
the visual appearance of generated slides (typography, colors, layout,
card styling, etc.).

These are distinct from:
- Deck prompts: control WHAT content to include
- System prompts: control HOW to generate valid HTML/charts (technical)

Slide styles control HOW slides should LOOK - the visual presentation.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from src.core.database import Base


class SlideStyleLibrary(Base):
    """Global library of slide styles.
    
    Each entry represents a reusable visual style configuration for
    slide generation. Profiles can select one of these styles to
    control the look and feel of generated presentations.
    """

    __tablename__ = "slide_style_library"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)  # e.g., "Brand", "Minimal", "Bold"
    style_content = Column(Text, nullable=False)
    
    is_active = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)  # Protected system styles cannot be edited/deleted
    
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<SlideStyleLibrary(id={self.id}, name='{self.name}', category='{self.category}')>"
