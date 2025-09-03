"""Generate HTML slide decks with Reveal.js and a shared theme.

This module mirrors the API of the PowerPoint generator, but emits a self-
contained HTML file that renders a Reveal.js slide deck. It provides:

- `SlideTheme` for background, fonts, and colors (applied via CSS overrides)
- `add_title_slide`, `add_agenda_slide`, `add_content_slide`
- `create_basic_html` helper and demo in the `__main__` guard

Slides are emitted as `<section>` elements inside the Reveal.js container.
We load Reveal.js from a CDN by default (no local assets required).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Union, Dict, Optional, Any
import json


@dataclass
class Slide:
    """Represents a single slide with its content and metadata.
    
    This class can represent different types of slides (title, agenda, content)
    by using the slide_type field and storing type-specific data in metadata.
    """
    title: str = ""
    subtitle: str = ""
    content: str = ""
    slide_type: str = "content"  # "title", "agenda", "content", or "custom"
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_html(self, theme: 'SlideTheme') -> str:
        """Convert this slide to HTML based on its type."""
        if self.slide_type == "title":
            return self._render_title_slide(theme)
        elif self.slide_type == "agenda":
            return self._render_agenda_slide(theme)
        elif self.slide_type == "content":
            return self._render_content_slide(theme)
        elif self.slide_type == "custom":
            return self._render_custom_slide(theme)
        else:
            raise ValueError(f"Unknown slide_type: {self.slide_type}")
    
    def _render_title_slide(self, theme: 'SlideTheme') -> str:
        """Render a title slide."""
        authors = self.metadata.get('authors', [])
        date = self.metadata.get('date', '')
        authors_str = ", ".join(authors) if authors else ""
        byline = " • ".join([p for p in [authors_str, date] if p])
        
        return (
            f"<div class=\"title-slide\">"
            f"  <div class=\"title-bar\"></div>"
            f"  <h1 class=\"title\">{_escape(self.title)}</h1>"
            f"  <div class=\"subtitle\">{_escape(self.subtitle)}</div>"
            f"  <div class=\"body\">{_escape(byline)}</div>"
            f"</div>"
        )
    
    def _render_agenda_slide(self, theme: 'SlideTheme') -> str:
        """Render an agenda slide."""
        agenda_points = self.metadata.get('agenda_points', [])
        count = len(agenda_points)
        
        # Adaptive font size based on number of points
        if count <= 4:
            size_class = "agenda-size-large"
        elif count <= 8:
            size_class = "agenda-size-medium"
        else:
            size_class = "agenda-size-small"
        
        def render_list(items: List[str], start_index: int) -> str:
            lis: List[str] = []
            for i, text in enumerate(items, start=start_index):
                lis.append(
                    f"<li class=\"agenda-item\"><span class=\"agenda-num\">{i}</span><span>{_escape(text)}</span></li>"
                )
            inner = ''.join(lis) or '<li class="agenda-item">(No agenda items)</li>'
            return f'<ul class="agenda-list">{inner}</ul>'

        if count > 8:
            import math
            first_len = math.ceil(count / 2)
            first_col = render_list(list(agenda_points[:first_len]), 1)
            second_col = render_list(list(agenda_points[first_len:]), first_len + 1)
            lists_html = f"<div class=\"agenda-columns {size_class}\"><div>{first_col}</div><div>{second_col}</div></div>"
        else:
            lists_html = f"<div class=\"{size_class}\">{render_list(list(agenda_points), 1)}</div>"

        return (
            f"<div class=\"agenda-slide\">"
            f"  <h2 class=\"title\">{_escape(self.title or 'Agenda')}</h2>"
            f"  <div class=\"title-bar\"></div>"
            f"  {lists_html}"
            f"</div>"
        )
    
    def _render_content_slide(self, theme: 'SlideTheme') -> str:
        """Render a content slide."""
        num_columns = self.metadata.get('num_columns', 1)
        column_contents = self.metadata.get('column_contents', [[]])
        
        if num_columns not in (1, 2, 3):
            num_columns = 1
        if len(column_contents) != num_columns:
            column_contents = [[] for _ in range(num_columns)]

        cols_html: List[str] = []
        for idx in range(num_columns):
            items = column_contents[idx] if idx < len(column_contents) else []
            bullets = "".join(f"<li>{_escape(i)}</li>" for i in items)
            cols_html.append(f"<div class=\"col\"><ul>{bullets}</ul></div>")

        dividers_class = " with-dividers" if num_columns > 1 else ""
        return (
            f"<div class=\"content-slide\">"
            f"  <h2 class=\"title\">{_escape(self.title)}</h2>"
            f"  <div class=\"title-bar\"></div>"
            f"  <div class=\"subtitle\">{_escape(self.subtitle)}</div>"
            f"  <div class=\"columns{dividers_class}\" style=\"--cols:{num_columns}\">{''.join(cols_html)}</div>"
            f"</div>"
        )
    
    def _render_custom_slide(self, theme: 'SlideTheme') -> str:
        """Render a custom slide with title, subtitle, and custom content."""
        # Only show title/subtitle if they are provided
        title_html = f"<h2 class=\"title\">{_escape(self.title)}</h2>" if self.title else ""
        title_bar_html = "<div class=\"title-bar\"></div>" if self.title else ""
        subtitle_html = f"<div class=\"subtitle\">{_escape(self.subtitle)}</div>" if self.subtitle else ""
        
        return (
            f"<div class=\"content-slide\">"
            f"  {title_html}"
            f"  {title_bar_html}"
            f"  {subtitle_html}"
            f"  <div class=\"custom-content\">{self.content}</div>"
            f"</div>"
        )


@dataclass
class SlideTheme:
    """Common theme for HTML slides.

    Customize these fields to control visual identity:
    - background_rgb: (R, G, B) background color
    - font_family: CSS font-family stack (e.g., "-apple-system, Segoe UI, Arial")
    - title_font_size_px, subtitle_font_size_px, body_font_size_px: sizes
    - title_color_rgb, subtitle_color_rgb, body_color_rgb: text colors

    Fill in with your corporate fonts and colors. If you need further control
    (margins, logo, footer), extend this class and update CSS builders below.
    """

    background_rgb: Tuple[int, int, int] = (255, 255, 255)
    font_family: str = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    title_font_size_px: int = 44
    subtitle_font_size_px: int = 26
    body_font_size_px: int = 18
    title_color_rgb: Tuple[int, int, int] = (0, 0, 0)
    subtitle_color_rgb: Tuple[int, int, int] = (80, 80, 80)
    body_color_rgb: Tuple[int, int, int] = (20, 20, 20)
    # Optional brand accents and chrome
    primary_rgb: Tuple[int, int, int] = (46, 46, 56)
    accent_rgb: Tuple[int, int, int] = (255, 102, 0)
    header_bar_height_px: int = 0
    logo_url: str | None = None
    footer_text: str | None = None
    # Bottom-right logo configuration
    bottom_right_logo_url: str | None = None
    bottom_right_logo_height_px: int = 40
    bottom_right_logo_margin_px: int = 20
    # Title slide specific styling
    title_bar_rgb: Tuple[int, int, int] = (0, 122, 255)  # short blue bar above title
    title_font_family: str = "'DM Sans', 'Liberation Sans', Arial, Helvetica, sans-serif"
    subtitle_font_family: str = "'DM Sans', 'Liberation Sans', Arial, Helvetica, sans-serif"

    def rgb(self, triplet: Tuple[int, int, int]) -> str:
        r, g, b = triplet
        return f"rgb({r}, {g}, {b})"

    def build_base_css(self) -> str:
        return f"""
        /* Reveal.js overrides */
        html, body {{ height: 100%; margin: 0; }}
        body {{ background: {self.rgb(self.background_rgb)}; }}
        .reveal {{ font-family: {self.font_family}; }}
        .reveal h1.title, .reveal h2.title {{
          font-size: {self.title_font_size_px}px;
          color: {self.rgb(self.title_color_rgb)};
        }}
        .reveal .subtitle {{
          font-size: {self.subtitle_font_size_px}px;
          color: {self.rgb(self.subtitle_color_rgb)};
        }}
        .reveal .body {{
          font-size: {self.body_font_size_px}px;
          color: {self.rgb(self.body_color_rgb)};
        }}
        .reveal .columns {{
          display: grid;
          grid-template-columns: repeat(var(--cols), 1fr);
          gap: 24px;
          margin-top: 16px;
        }}
        .reveal .col ul {{ margin: 0; padding-left: 20px; }}
        /* Optional spacing tweaks */
        .reveal section {{ padding: 16px 24px; }}
        /* Title slide layout */
        .reveal .title-slide {{
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          justify-content: flex-start;
          margin-top: 25vh; /* 1/4 down the slide */
          text-align: left;
        }}
        .reveal .title-slide .title-bar {{
          width: 120px;
          height: 6px;
          background: {self.rgb(self.title_bar_rgb)};
          margin-bottom: 12px;
        }}
        .reveal .title-slide h1.title {{
          font-family: {self.title_font_family};
          font-weight: 700;
          font-size: 40px; /* override requested */
          color: {self.rgb((0,0,0))};
          margin: 0 0 8px 0;
        }}
        .reveal .title-slide .subtitle {{
          font-family: {self.subtitle_font_family};
          font-weight: 400;
          font-size: 24px; /* override requested */
          color: {self.rgb((102, 163, 255))}; /* light blue */
        }}
        /* Agenda slide layout */
        .reveal .agenda-slide {{
          margin-top: 10vh;
          text-align: left;
        }}
        .reveal .agenda-slide h2.title {{
          font-family: {self.title_font_family};
          font-weight: 700;
        }}
        .reveal .agenda-columns {{
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
          align-items: start;
        }}
        .reveal .agenda-list {{
          list-style: none;
          padding-left: 0;
          margin: 8px 0 0 0;
        }}
        /* Agenda title underline bar (same as title-slide length/color) */
        .reveal .agenda-slide .title-bar {{
          width: 120px;
          height: 6px;
          background: {self.rgb(self.title_bar_rgb)};
          margin: 8px 0 12px 0;
        }}
        /* Adaptive sizes */
        .reveal .agenda-size-large {{ font-size: 28px; }}
        .reveal .agenda-size-medium {{ font-size: 22px; }}
        .reveal .agenda-size-small {{ font-size: 18px; }}
        .reveal .agenda-item {{
          display: flex;
          align-items: flex-start;
          gap: 12px;
          margin: 14px 0; /* increased spacing between agenda points */
        }}
        .reveal .agenda-num {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 1.8em; /* scale with text size */
          height: 1.8em; /* scale with text size */
          border-radius: 50%;
          background: {self.rgb(self.title_bar_rgb)};
          color: #ffffff;
          font-weight: 700;
          font-size: 0.9em; /* number size relative to text */
          line-height: 1.8em;
          flex: 0 0 1.8em;
        }}
        /* Content slide layout */
        .reveal .content-slide {{
          text-align: left;
        }}
        .reveal .content-slide h2.title {{
          font-family: {self.title_font_family};
          font-weight: 700;
        }}
        .reveal .content-slide .title-bar {{
          width: 120px;
          height: 6px;
          background: {self.rgb(self.title_bar_rgb)};
          margin: 8px 0 12px 0;
        }}
        .reveal .content-slide .subtitle {{
          font-family: {self.subtitle_font_family};
          font-weight: 400;
          font-size: 24px;
          color: {self.rgb((102, 163, 255))};
          margin-bottom: 8px;
        }}
        .reveal .columns.with-dividers .col {{
          border-right: 2px solid rgba(102, 163, 255, 0.25); /* faint blue */
          padding-right: 16px;
        }}
        .reveal .columns.with-dividers .col:last-child {{
          border-right: none;
          padding-right: 0;
        }}
        /* Custom slide content styling */
        .reveal .custom-content {{
          margin-top: 16px;
          line-height: 1.6;
        }}
        /* Optional brand chrome */
        .brand-header {{
          position: absolute; left: 0; top: 0; right: 0;
          height: {self.header_bar_height_px}px;
          background: {self.rgb(self.primary_rgb)};
          z-index: 5;
        }}
        .brand-header .logo {{
          position: absolute; top: {self.header_bar_height_px + 8}px; left: 24px;
          max-height: 36px; width: auto;
        }}
        .brand-footer {{
          position: absolute; left: 24px; right: 24px; bottom: 12px;
          color: {self.rgb(self.subtitle_color_rgb)}; font-size: 12px;
          display: flex; align-items: center; justify-content: space-between;
        }}
        /* Bottom-right logo styling */
        .bottom-right-logo {{
          position: fixed;
          bottom: {self.bottom_right_logo_margin_px}px;
          right: {self.bottom_right_logo_margin_px}px;
          height: {self.bottom_right_logo_height_px}px;
          width: auto;
          z-index: 1000;
          opacity: 0.9;
        }}
        """
    
    


class HtmlDeck:
    """Accumulates slides and writes a single-page HTML deck."""

    def __init__(self, theme: SlideTheme | None = None) -> None:
        self.theme = theme or SlideTheme()
        self._slides: List[Slide] = []
        self.TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "tool_add_title_slide",
      "description": "Add or replace the title slide at position 0 (first slide). Creates a Slide object with title slide type.",
      "parameters": {
        "type": "object",
        "properties": {
          "title": { "type": "string" },
          "subtitle": { "type": "string" },
          "authors": { "type": "array", "items": { "type": "string" } },
          "date": { "type": "string" }
        },
        "required": ["title", "subtitle", "authors", "date"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_add_agenda_slide",
      "description": "Add or replace the agenda slide at position 1 (second slide). Creates a Slide object with agenda slide type; auto-splits to two columns if more than 8 points.",
      "parameters": {
        "type": "object",
        "properties": {
          "agenda_points": { "type": "array", "items": { "type": "string" } }
        },
        "required": ["agenda_points"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_add_content_slide",
      "description": "Append a content slide with 1–3 columns of bullets. Creates a Slide object with content slide type.",
      "parameters": {
        "type": "object",
        "properties": {
          "title": { "type": "string" },
          "subtitle": { "type": "string" },
          "num_columns": { "type": "integer", "enum": [1, 2, 3] },
          "column_contents": {
            "type": "array",
            "items": { "type": "array", "items": { "type": "string" } }
          }
        },
        "required": ["title", "subtitle", "num_columns", "column_contents"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_add_custom_html_slide",
      "description": "Add a slide with custom HTML content directly from LLM. Creates a Slide object with custom slide type.",
      "parameters": {
        "type": "object",
        "properties": {
          "html_content": { "type": "string" },
          "title": { "type": "string" },
          "subtitle": { "type": "string" }
        },
        "required": ["html_content"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_get_slide_details",
      "description": "Get details for a specific slide. If attribute is specified, returns that attribute value. If no attribute, returns full slide HTML. Attribute can be title, subtitle, or content.",
      "parameters": {
        "type": "object",
        "properties": {
          "slide_number": { "type": "integer", "minimum": 0 },
          "attribute": { "type": "string" }
        },
        "required": ["slide_number"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_modify_slide_details",
      "description": "Modify a specific attribute of a slide in place. Can modify title, subtitle, content, slide_type, or metadata fields.",
      "parameters": {
        "type": "object",
        "properties": {
          "slide_number": { "type": "integer", "minimum": 0 },
          "attribute": { "type": "string" },
          "content": { "type": ["string", "array", "object", "integer", "boolean"] }
        },
        "required": ["slide_number", "attribute", "content"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_get_html",
      "description": "Return the current full HTML string for the deck.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_write_html",
      "description": "Write the current HTML string to disk and return the saved path.",
      "parameters": {
        "type": "object",
        "properties": {
          "output_path": { "type": "string" }
        },
        "required": ["output_path"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_reorder_slide",
      "description": "Move a slide from one position to another. Slides are 0-indexed. Moving a slide shifts other slides: if slide 5 moves to position 3, slides 3-4 shift right to positions 4-5.",
      "parameters": {
        "type": "object",
        "properties": {
          "from_position": { "type": "integer", "minimum": 0 },
          "to_position": { "type": "integer", "minimum": 0 }
        },
        "required": ["from_position", "to_position"],
        "additionalProperties": False
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "tool_delete_slide",
      "description": "Delete a slide at the specified position. Slides are 0-indexed. Deleting a slide shifts all subsequent slides left by 1 position.",
      "parameters": {
        "type": "object",
        "properties": {
          "position": { "type": "integer", "minimum": 0 }
        },
        "required": ["position"],
        "additionalProperties": False
      }
    }
  }
]

    def reset_slides(self) -> None:
        """Reset the slides to the initial empty deck"""
        self._slides = []

    def add_raw_slide(self, inner_html: str) -> None:
        """Add a slide to the end of the deck"""
        slide = Slide(content=inner_html, slide_type="custom")
        self._slides.append(slide)
    
    def set_slide_at_position(self, position: int, slide: Slide) -> None:
        """Set a slide at a specific position, extending the list if necessary"""
        # Extend the list with empty slides if position is beyond current length
        while len(self._slides) <= position:
            self._slides.append(Slide())
        
        self._slides[position] = slide
    
    def insert_slide_at_position(self, position: int, slide: Slide) -> None:
        """Insert a slide at a specific position, shifting other slides down
        
        Example: If deck has slides [0, 1, 2, 3, 4] and we insert at position 2,
        the result will be [0, 1, NEW, 2, 3, 4] - slides 2+ shift right by 1
        """
        # If position is beyond current length, just append
        if position >= len(self._slides):
            self._slides.append(slide)
        else:
            self._slides.insert(position, slide)
    
    def reorder_slide(self, from_position: int, to_position: int) -> None:
        """Move a slide from one position to another, shifting other slides as needed
        
        This function removes the slide at from_position and inserts it at to_position.
        All slides between these positions shift to fill the gap.
        
        Example: Moving slide 5 to position 3 in deck [0, 1, 2, 3, 4, 5, 6, 7]
        - Remove slide 5: [0, 1, 2, 3, 4, _, 6, 7] -> [0, 1, 2, 3, 4, 6, 7] 
        - Insert at position 3: [0, 1, 2, 5, 3, 4, 6, 7]
        - Final result: Slide 5 is now at position 3, old slides 3-4 shifted right
        """
        if from_position < 0 or from_position >= len(self._slides):
            raise ValueError(f"from_position {from_position} is out of range")
        if to_position < 0:
            raise ValueError(f"to_position {to_position} cannot be negative")
        
        # Remove the slide from its current position
        slide = self._slides.pop(from_position)
        
        # Insert it at the new position (clamp to valid range)
        actual_to_position = min(to_position, len(self._slides))
        self._slides.insert(actual_to_position, slide)

    def delete_slide(self, position: int) -> None:
        """Delete a slide at the specified position
        
        Args:
            position: 0-based index of the slide to delete
            
        Raises:
            ValueError: If position is out of range
            
        Example: Deleting slide 2 from deck [0, 1, 2, 3, 4] results in [0, 1, 3, 4]
                 - Slides after the deleted position shift left by 1
        """
        if position < 0 or position >= len(self._slides):
            raise ValueError(f"Position {position} is out of range (0-{len(self._slides)-1})")
        
        # Remove the slide at the specified position
        self._slides.pop(position)

    def add_title_slide(self, *, title: str, subtitle: str, authors: List[str], date: str) -> None:
        """Add or replace the title slide at position 0 (first slide)"""
        slide = Slide(
            title=title,
            subtitle=subtitle,
            slide_type="title",
            metadata={"authors": authors, "date": date}
        )
        self.set_slide_at_position(0, slide)

    def add_agenda_slide(self, *, agenda_points: List[str]) -> None:
        """Add or replace the agenda slide at position 1 (second slide)"""
        slide = Slide(
            title="Agenda",
            slide_type="agenda",
            metadata={"agenda_points": agenda_points}
        )
        self.set_slide_at_position(1, slide)

    def add_content_slide(
        self,
        *,
        title: str,
        subtitle: str,
        num_columns: int,
        column_contents: List[List[str]],
    ) -> None:
        if num_columns not in (1, 2, 3):
            raise ValueError("num_columns must be 1, 2, or 3")
        if len(column_contents) != num_columns:
            raise ValueError("len(column_contents) must equal num_columns")

        slide = Slide(
            title=title,
            subtitle=subtitle,
            slide_type="content",
            metadata={"num_columns": num_columns, "column_contents": column_contents}
        )
        self._slides.append(slide)

    def add_custom_html_slide(self, html_content: str, title: str = "", subtitle: str = "") -> None:
        """Add a slide with custom HTML content directly from LLM.
        
        Args:
            html_content: Raw HTML content for the slide
            title: Optional title for reference
            subtitle: Optional subtitle for reference
        """
        slide = Slide(
            title=title,
            subtitle=subtitle,
            content=html_content,
            slide_type="custom"
        )
        self._slides.append(slide)

    def get_slide_details(self, slide_number: int, attribute: str = None) -> Union[str, Any]:
        """Get slide details for a specific slide number and optional attribute.
        
        Args:
            slide_number: 0-based slide index
            attribute: Optional attribute to retrieve ('title', 'subtitle', 'content', 'slide_type', etc.)
                      If None, returns the full slide HTML for LLM consumption
        
        Returns:
            If attribute is specified, returns that attribute value
            If attribute is None, returns the full slide HTML string
        """
        slide_number = int(slide_number)
        if slide_number < 0 or slide_number >= len(self._slides):
            raise ValueError(f"Slide number {slide_number} is out of range (0-{len(self._slides)-1})")
        
        slide = self._slides[slide_number]
        
        if attribute is None:
            # Return full slide HTML for LLM
            return f"<section>{slide.to_html(self.theme)}</section>"
        
        # Return specific attribute
        if hasattr(slide, attribute):
            return getattr(slide, attribute)
        elif attribute in slide.metadata:
            return slide.metadata[attribute]
        else:
            raise ValueError(f"Attribute '{attribute}' not found in slide {slide_number}")

    def modify_slide_details(self, slide_number: int, attribute: str, content: Any) -> None:
        """Modify slide details for a specific slide number and attribute.
        
        Args:
            slide_number: 0-based slide index
            attribute: Attribute to modify ('title', 'subtitle', 'content', 'slide_type', etc.)
            content: New value for the attribute
        """
        if slide_number < 0 or slide_number >= len(self._slides):
            raise ValueError(f"Slide number {slide_number} is out of range (0-{len(self._slides)-1})")
        
        slide = self._slides[slide_number]
        
        # Modify the attribute
        if hasattr(slide, attribute):
            setattr(slide, attribute, content)
        else:
            # Store in metadata if it's not a direct attribute
            slide.metadata[attribute] = content

    # Tool functions for LLM integration
    def tool_add_title_slide(self, **kwargs) -> str:
        """Tool function for add_title_slide"""
        self.add_title_slide(**kwargs)
        return f"Title slide added/updated at position 0"

    def tool_add_agenda_slide(self, **kwargs) -> str:
        """Tool function for add_agenda_slide"""  
        self.add_agenda_slide(**kwargs)
        return f"Agenda slide added/updated at position 1"

    def tool_add_content_slide(self, **kwargs) -> str:
        """Tool function for add_content_slide"""
        self.add_content_slide(**kwargs)
        return f"Content slide added at position {len(self._slides)-1}"

    def tool_add_custom_html_slide(self, **kwargs) -> str:
        """Tool function for add_custom_html_slide"""
        self.add_custom_html_slide(**kwargs)
        return f"Custom HTML slide added at position {len(self._slides)-1}"

    def tool_get_html(self, **kwargs) -> str:
        """Tool function to get full HTML"""
        return self.to_html()

    def tool_write_html(self, output_path: str, **kwargs) -> str:
        """Tool function to write HTML to file"""
        html_content = self.to_html()
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        return f"HTML saved to: {output_path}"

    def tool_reorder_slide(self, from_position: int, to_position: int, **kwargs) -> str:
        """Tool function for reorder_slide"""
        self.reorder_slide(from_position, to_position)
        return f"Moved slide from position {from_position} to {to_position}"

    def tool_delete_slide(self, position: int, **kwargs) -> str:
        """Tool function for delete_slide"""
        position = int(position)
        if position < 0 or position >= len(self._slides):
            return f"Error: Position {position} is out of range (0-{len(self._slides)-1})"
        
        # Get slide info before deletion for confirmation message
        slide = self._slides[position]
        slide_info = f"slide {position}"
        if hasattr(slide, 'title') and slide.title:
            slide_info += f" ('{slide.title}')"
        
        self.delete_slide(position)
        return f"Deleted {slide_info}. Deck now has {len(self._slides)} slides."

    def tool_get_slide_details(self, slide_number: int, attribute: str = None, **kwargs) -> str:
        """Tool function for get_slide_details"""
        result = self.get_slide_details(slide_number, attribute)
        if attribute is None:
            return f"Full HTML for slide {slide_number}:\n{result}"
        else:
            return f"Slide {slide_number} {attribute}: {result}"

    def tool_modify_slide_details(self, slide_number: int, attribute: str, content: Any, **kwargs) -> str:
        """Tool function for modify_slide_details"""
        self.modify_slide_details(slide_number, attribute, content)
        return f"Modified slide {slide_number} {attribute} to: {content}"

    def to_html(self) -> str:
        css_overrides = self.theme.build_base_css()
        slides = "".join(f"<section>{slide.to_html(self.theme)}</section>" for slide in self._slides)
        header_logo = (
            f"<img class=\"logo\" src=\"{_escape(self.theme.logo_url)}\" alt=\"logo\"/>"
            if self.theme.logo_url else ""
        )
        footer = _escape(self.theme.footer_text) if self.theme.footer_text else ""
        header_html = f"<div class=\"brand-header\">{header_logo}</div>" if self.theme.header_bar_height_px else ""
        footer_html = f"<div class=\"brand-footer\">{footer}</div>" if footer else ""
        
        # Add bottom-right logo if configured
        bottom_right_logo_html = (
            f"<img class=\"bottom-right-logo\" src=\"{_escape(self.theme.bottom_right_logo_url)}\" alt=\"EY Parthenon Logo\"/>"
            if self.theme.bottom_right_logo_url else ""
        )
        return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Slide Deck</title>
  <link rel="stylesheet" href="https://unpkg.com/reveal.js/dist/reveal.css" />
  <link rel="stylesheet" href="https://unpkg.com/reveal.js/dist/theme/white.css" id="theme" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;700&display=swap" rel="stylesheet">
  <style>
  {css_overrides}
  </style>
</head>
<body>
  {header_html}
  <div class="reveal">
    <div class="slides">
      {slides}
    </div>
  </div>
  {footer_html}
  {bottom_right_logo_html}
  <script src="https://unpkg.com/reveal.js/dist/reveal.js"></script>
  <script>
    const deck = new Reveal({{
      hash: true,
      slideNumber: true,
      transition: 'slide',
      center: false
    }});
    deck.initialize();
  </script>
</body>
<!-- Generated by html_slides.py (Reveal.js) -->
</html>
"""




def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

