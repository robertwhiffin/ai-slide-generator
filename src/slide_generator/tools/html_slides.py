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
        """
    
    


class HtmlDeck:
    """Accumulates slides and writes a single-page HTML deck."""

    def __init__(self, theme: SlideTheme | None = None) -> None:
        self.theme = theme or SlideTheme()
        self._slides_html: List[str] = []
        self.TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "tool_add_title_slide",
      "description": "Add or replace the title slide at position 0 (first slide).",
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
      "description": "Add or replace the agenda slide at position 1 (second slide); auto-splits to two columns if more than 8 points.",
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
      "description": "Append a content slide with 1–3 columns of bullets.",
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
  }
]

    def add_raw_slide(self, inner_html: str) -> None:
        """Add a slide to the end of the deck"""
        self._slides_html.append(f"<section>{inner_html}</section>")
    
    def set_slide_at_position(self, position: int, inner_html: str) -> None:
        """Set a slide at a specific position, extending the list if necessary"""
        slide_html = f"<section>{inner_html}</section>"
        
        # Extend the list with empty slides if position is beyond current length
        while len(self._slides_html) <= position:
            self._slides_html.append("")
        
        self._slides_html[position] = slide_html
    
    def insert_slide_at_position(self, position: int, inner_html: str) -> None:
        """Insert a slide at a specific position, shifting other slides down
        
        Example: If deck has slides [0, 1, 2, 3, 4] and we insert at position 2,
        the result will be [0, 1, NEW, 2, 3, 4] - slides 2+ shift right by 1
        """
        slide_html = f"<section>{inner_html}</section>"
        
        # If position is beyond current length, just append
        if position >= len(self._slides_html):
            self._slides_html.append(slide_html)
        else:
            self._slides_html.insert(position, slide_html)
    
    def reorder_slide(self, from_position: int, to_position: int) -> None:
        """Move a slide from one position to another, shifting other slides as needed
        
        This function removes the slide at from_position and inserts it at to_position.
        All slides between these positions shift to fill the gap.
        
        Example: Moving slide 5 to position 3 in deck [0, 1, 2, 3, 4, 5, 6, 7]
        - Remove slide 5: [0, 1, 2, 3, 4, _, 6, 7] -> [0, 1, 2, 3, 4, 6, 7] 
        - Insert at position 3: [0, 1, 2, 5, 3, 4, 6, 7]
        - Final result: Slide 5 is now at position 3, old slides 3-4 shifted right
        """
        if from_position < 0 or from_position >= len(self._slides_html):
            raise ValueError(f"from_position {from_position} is out of range")
        if to_position < 0:
            raise ValueError(f"to_position {to_position} cannot be negative")
        
        # Remove the slide from its current position
        slide = self._slides_html.pop(from_position)
        
        # Insert it at the new position (clamp to valid range)
        actual_to_position = min(to_position, len(self._slides_html))
        self._slides_html.insert(actual_to_position, slide)

    def add_title_slide(self, *, title: str, subtitle: str, authors: List[str], date: str) -> None:
        """Add or replace the title slide at position 0 (first slide)"""
        authors_str = ", ".join(authors) if authors else ""
        byline = " • ".join([p for p in [authors_str, date] if p])
        inner = (
            f"<div class=\"title-slide\">"
            f"  <div class=\"title-bar\"></div>"
            f"  <h1 class=\"title\">{_escape(title)}</h1>"
            f"  <div class=\"subtitle\">{_escape(subtitle)}</div>"
            f"  <div class=\"body\">{_escape(byline)}</div>"
            f"</div>"
        )
        self.set_slide_at_position(0, inner)

    def add_agenda_slide(self, *, agenda_points: List[str]) -> None:
        """Add or replace the agenda slide at position 1 (second slide)"""
        count = len(agenda_points)
        # Adaptive font size based on number of points (good default at <=4)
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

        inner = (
            f"<div class=\"agenda-slide\">"
            f"  <h2 class=\"title\">Agenda</h2>"
            f"  <div class=\"title-bar\"></div>"
            f"  {lists_html}"
            f"</div>"
        )
        self.set_slide_at_position(1, inner)

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

        cols_html: List[str] = []
        for idx in range(num_columns):
            items = column_contents[idx] if idx < len(column_contents) else []
            bullets = "".join(f"<li>{_escape(i)}</li>" for i in items)
            cols_html.append(f"<div class=\"col\"><ul>{bullets}</ul></div>")

        dividers_class = " with-dividers" if num_columns > 1 else ""
        inner = (
            f"<div class=\"content-slide\">"
            f"  <h2 class=\"title\">{_escape(title)}</h2>"
            f"  <div class=\"title-bar\"></div>"
            f"  <div class=\"subtitle\">{_escape(subtitle)}</div>"
            f"  <div class=\"columns{dividers_class}\" style=\"--cols:{num_columns}\">{''.join(cols_html)}</div>"
            f"</div>"
        )
        self.add_raw_slide(inner)

    def to_html(self) -> str:
        css_overrides = self.theme.build_base_css()
        slides = "".join(self._slides_html)
        header_logo = (
            f"<img class=\"logo\" src=\"{_escape(self.theme.logo_url)}\" alt=\"logo\"/>"
            if self.theme.logo_url else ""
        )
        footer = _escape(self.theme.footer_text) if self.theme.footer_text else ""
        header_html = f"<div class=\"brand-header\">{header_logo}</div>" if self.theme.header_bar_height_px else ""
        footer_html = f"<div class=\"brand-footer\">{footer}</div>" if footer else ""
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

