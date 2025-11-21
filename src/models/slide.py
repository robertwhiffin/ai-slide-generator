"""Slide class for representing individual slides as raw HTML."""

import copy
from typing import Optional


class Slide:
    """Represents a single slide as raw HTML content.
    
    This class wraps a complete slide HTML (including the <div class="slide"> wrapper)
    and provides basic operations like cloning and string representation.
    
    Attributes:
        html: The complete HTML for this slide
        slide_id: Optional unique identifier for this slide
    """

    def __init__(self, html: str, slide_id: Optional[str] = None):
        """Initialize a Slide with HTML content.
        
        Args:
            html: The complete HTML for this slide (including outer <div class="slide">)
            slide_id: Optional unique identifier for this slide
        """
        self.html = html
        self.slide_id = slide_id

    def to_html(self) -> str:
        """Return the HTML string for this slide.
        
        Returns:
            The complete HTML content of the slide
        """
        return self.html

    def clone(self) -> 'Slide':
        """Create a deep copy of this slide.
        
        Returns:
            A new Slide instance with copied HTML content
        """
        return Slide(
            html=copy.deepcopy(self.html),
            slide_id=self.slide_id
        )

    def __str__(self) -> str:
        """String representation showing slide preview.
        
        Returns:
            A preview of the slide's HTML content (first 100 characters)
        """
        preview_length = 100
        preview = self.html[:preview_length]
        if len(self.html) > preview_length:
            preview += "..."

        id_str = f" (id: {self.slide_id})" if self.slide_id else ""
        return f"Slide{id_str}: {preview}"

    def __repr__(self) -> str:
        """Developer-friendly representation of the Slide.
        
        Returns:
            String representation for debugging
        """
        return f"Slide(slide_id={self.slide_id!r}, html_length={len(self.html)})"

