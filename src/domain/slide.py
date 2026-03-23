"""Slide class for representing individual slides as raw HTML."""

import copy
from datetime import datetime
from typing import Optional


class Slide:
    """Represents a single slide as raw HTML content.
    
    This class wraps a complete slide HTML (including the <div class="slide"> wrapper)
    and provides basic operations like cloning and string representation.
    
    Attributes:
        html: The complete HTML for this slide
        slide_id: Optional unique identifier for this slide
        scripts: JavaScript code for this slide's charts (e.g., Chart.js initialization)
        created_by: Username of the user who created this slide
        created_at: ISO timestamp when the slide was first created
        modified_by: Username of the last user who modified this slide
        modified_at: ISO timestamp of the last modification
    """

    def __init__(
        self,
        html: str,
        slide_id: Optional[str] = None,
        scripts: str = "",
        created_by: Optional[str] = None,
        created_at: Optional[str] = None,
        modified_by: Optional[str] = None,
        modified_at: Optional[str] = None,
    ):
        self.html = html
        self.slide_id = slide_id
        self.scripts = scripts
        self.created_by = created_by
        self.created_at = created_at
        self.modified_by = modified_by
        self.modified_at = modified_at

    def to_html(self) -> str:
        """Return the HTML string for this slide."""
        return self.html

    def stamp_created(self, user: str) -> None:
        """Set creation metadata. Only sets if not already stamped."""
        if not self.created_by:
            now = datetime.utcnow().isoformat() + "Z"
            self.created_by = user
            self.created_at = now
            self.modified_by = user
            self.modified_at = now

    def stamp_modified(self, user: str) -> None:
        """Update modification metadata."""
        self.modified_by = user
        self.modified_at = datetime.utcnow().isoformat() + "Z"

    def clone(self) -> 'Slide':
        """Create a deep copy of this slide."""
        return Slide(
            html=copy.deepcopy(self.html),
            slide_id=self.slide_id,
            scripts=copy.deepcopy(self.scripts),
            created_by=self.created_by,
            created_at=self.created_at,
            modified_by=self.modified_by,
            modified_at=self.modified_at,
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
        return f"Slide(slide_id={self.slide_id!r}, html_length={len(self.html)}, scripts_length={len(self.scripts)})"

