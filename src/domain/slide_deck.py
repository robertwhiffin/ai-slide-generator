"""SlideDeck class for parsing, manipulating, and reconstructing HTML slide decks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.utils.css_utils import merge_css
from src.utils.html_utils import split_script_by_canvas

from .slide import Slide


class SlideDeck:
    """Container for an entire slide deck with operations for manipulation and rendering.
    
    This class parses HTML slide decks, stores slides as raw HTML with their
    associated scripts, and provides methods for reordering, inserting, 
    removing slides, and reconstructing HTML.
    
    Scripts are stored directly on each Slide object. When a slide is removed,
    its scripts are automatically removed with it.
    
    Attributes:
        title: Deck title (extracted from HTML title or first slide)
        css: All CSS extracted from <style> tags
        external_scripts: List of CDN script URLs (Tailwind, Chart.js, etc.)
        slides: List of Slide objects (each containing its own scripts)
        head_meta: Other metadata from HTML head (charset, viewport, etc.)
    """

    CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js"

    def __init__(
        self,
        title: Optional[str] = None,
        css: str = "",
        external_scripts: Optional[List[str]] = None,
        slides: Optional[List[Slide]] = None,
        head_meta: Optional[Dict[str, str]] = None,
    ):
        """Initialize a SlideDeck.
        
        Args:
            title: Deck title
            css: CSS content
            external_scripts: List of external script URLs
            slides: List of Slide objects (each may contain scripts)
            head_meta: Metadata from HTML head
        """
        self.title = title
        self.css = css
        self.external_scripts = external_scripts or []
        self.slides = slides or []
        self.head_meta = head_meta or {}
        self._ensure_default_external_scripts()

    def _ensure_default_external_scripts(self) -> None:
        """Ensure required third-party scripts are included when knitting."""
        if self.CHART_JS_URL not in self.external_scripts:
            self.external_scripts.append(self.CHART_JS_URL)

    @property
    def scripts(self) -> str:
        """Aggregate all slide scripts with IIFE wrapping for scope isolation.
        
        Each slide's scripts are wrapped in an IIFE to prevent variable
        name collisions when all scripts run in the same document context
        (e.g., presentation mode, knit() output).
        
        Returns:
            Aggregated JavaScript from all slides, IIFE-wrapped
        """
        parts = []
        for slide in self.slides:
            if slide.scripts and slide.scripts.strip():
                wrapped = f"(function() {{\n{slide.scripts.strip()}\n}})();"
                parts.append(wrapped)
        return "\n\n".join(parts)

    def update_css(self, replacement_css: str) -> None:
        """Merge replacement CSS rules into deck CSS.
        
        Selectors in replacement_css override matching selectors in existing CSS.
        New selectors are appended. Existing selectors not in replacement are preserved.
        
        Args:
            replacement_css: CSS from edit response to merge
        """
        if not replacement_css or not replacement_css.strip():
            return
        self.css = merge_css(self.css, replacement_css)

    @classmethod
    def from_html(cls, html_path: str) -> 'SlideDeck':
        """Parse an HTML file and create a SlideDeck.
        
        Args:
            html_path: Path to the HTML file
            
        Returns:
            A new SlideDeck instance
            
        Raises:
            FileNotFoundError: If the HTML file doesn't exist
        """
        path = Path(html_path)
        if not path.exists():
            raise FileNotFoundError(f"HTML file not found: {html_path}")

        html_content = path.read_text(encoding='utf-8')
        return cls.from_html_string(html_content)

    @classmethod
    def from_html_string(cls, html_content: str) -> 'SlideDeck':
        """Parse an HTML string and create a SlideDeck.
        
        Scripts are associated with slides via canvas ID matching:
        1. Parse all slides and build a canvas-to-slide index
        2. For each script, split by canvas using split_script_by_canvas()
        3. Assign each segment to the slide containing its canvas
        4. Fallback: assign to last slide if no canvas match
        
        Args:
            html_content: HTML content as a string
            
        Returns:
            A new SlideDeck instance
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        # Phase 1: Extract Head Components

        # Extract title
        title_tag = soup.find('title')
        title = title_tag.get_text() if title_tag else None

        # Extract metadata
        head_meta: Dict[str, str] = {}
        for meta in soup.find_all('meta'):
            if meta.get('charset'):
                head_meta['charset'] = meta.get('charset')
            elif meta.get('name') and meta.get('content'):
                head_meta[meta.get('name')] = meta.get('content')

        # Extract CSS from <style> tags
        css_parts = []
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                css_parts.append(style_tag.string)
        css = '\n'.join(css_parts)

        # Extract external scripts
        external_scripts = []
        for script_tag in soup.find_all('script', src=True):
            external_scripts.append(script_tag['src'])

        # Phase 2: Parse slides and build canvas-to-slide index
        slide_elements = soup.find_all('div', class_='slide')
        slides: List[Slide] = []
        canvas_to_slide: Dict[str, int] = {}  # canvas_id -> slide_index

        for idx, slide_element in enumerate(slide_elements):
            slide_html = str(slide_element)
            slide = Slide(html=slide_html, slide_id=f"slide_{idx}")
            slides.append(slide)
            # Index canvases in this slide
            for canvas in slide_element.find_all('canvas'):
                canvas_id = canvas.get('id')
                if canvas_id:
                    canvas_to_slide[canvas_id] = idx

        # Phase 3: Parse scripts and assign to slides via canvas matching
        for script_tag in soup.find_all('script', src=False):
            script_text = script_tag.string or script_tag.get_text()
            if not script_text or not script_text.strip():
                continue

            # Split multi-canvas scripts into per-canvas segments
            segments = split_script_by_canvas(script_text)

            for segment_text, canvas_ids in segments:
                # Find slide by canvas ID
                assigned = False
                for canvas_id in canvas_ids:
                    if canvas_id in canvas_to_slide:
                        slide_idx = canvas_to_slide[canvas_id]
                        slides[slide_idx].scripts += segment_text.strip() + "\n"
                        assigned = True
                        break

                # Fallback: assign to last slide if no canvas match
                if not assigned and slides:
                    slides[-1].scripts += segment_text.strip() + "\n"

        return cls(
            title=title,
            css=css,
            external_scripts=external_scripts,
            slides=slides,
            head_meta=head_meta,
        )

    def insert_slide(self, slide: Slide, position: int) -> None:
        """Insert slide at the specified position.
        
        Args:
            slide: The Slide object to insert
            position: Index to insert at
        Raises:
            IndexError: If position is out of range
        """
        self.slides.insert(position, slide)

    def append_slide(self, slide: Slide) -> None:
        """Append a slide to the end of the slide deck.
        
        Args:
            slide: The Slide object to append
        """
        self.slides.append(slide)

    def remove_slide(self, index: int) -> Slide:
        """Remove and return slide at index.
        
        Args:
            index: Index of slide to remove
            
        Returns:
            The removed Slide object
            
        Raises:
            IndexError: If index is out of range
        """
        return self.slides.pop(index)

    def get_slide(self, index: int) -> Slide:
        """Retrieve slide by index.
        
        Args:
            index: Index of slide to retrieve
            
        Returns:
            The Slide object at the specified index
            
        Raises:
            IndexError: If index is out of range
        """
        return self.slides[index]

    def move_slide(self, from_index: int, to_index: int) -> None:
        """Move slide from one position to another.
        
        Args:
            from_index: Current index of slide
            to_index: Target index for slide
            
        Raises:
            IndexError: If either index is out of range
        """
        slide = self.slides.pop(from_index)
        self.slides.insert(to_index, slide)

    def swap_slides(self, index1: int, index2: int) -> None:
        """Swap two slides.
        
        Args:
            index1: Index of first slide
            index2: Index of second slide
            
        Raises:
            IndexError: If either index is out of range
        """
        self.slides[index1], self.slides[index2] = self.slides[index2], self.slides[index1]

    def knit(self) -> str:
        """Reconstruct complete HTML with all slides.
        
        Returns:
            Complete HTML document as a string
        """
        self._ensure_default_external_scripts()
        # Build external script tags
        external_script_tags = '\n    '.join(
            f'<script src="{src}"></script>'
            for src in self.external_scripts
        )

        # Build meta tags
        meta_tags = []
        if 'charset' in self.head_meta:
            meta_tags.append(f'<meta charset="{self.head_meta["charset"]}">')
        else:
            meta_tags.append('<meta charset="UTF-8">')

        for name, content in self.head_meta.items():
            if name != 'charset':
                meta_tags.append(f'<meta name="{name}" content="{content}">')

        # If no viewport meta, add default
        if 'viewport' not in self.head_meta:
            meta_tags.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')

        meta_tags_html = '\n    '.join(meta_tags)

        # Build slide HTML
        slides_html = '\n\n'.join(slide.to_html() for slide in self.slides)

        # Build complete HTML
        title_text = self.title or "Slide Deck"

        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="en">',
            '<head>',
            f'    {meta_tags_html}',
            f'    <title>{title_text}</title>',
        ]

        if external_script_tags:
            html_parts.append(f'    {external_script_tags}')

        if self.css:
            html_parts.extend([
                '    <style>',
                self.css,
                '    </style>',
            ])

        html_parts.extend([
            '</head>',
            '<body>',
            '',
            slides_html,
            '',
        ])

        if self.scripts:
            html_parts.extend([
                '<script>',
                self.scripts,
                '</script>',
            ])

        html_parts.extend([
            '',
            '</body>',
            '</html>',
        ])

        return '\n'.join(html_parts)

    def render_slide(self, index: int) -> str:
        """Render a single slide as complete HTML page.
        
        Uses only this slide's scripts (no IIFE wrapping needed since
        it's rendered in isolation).
        
        Args:
            index: Index of slide to render
            
        Returns:
            Complete HTML document with just the specified slide
            
        Raises:
            IndexError: If index is out of range
        """
        slide = self.get_slide(index)
        self._ensure_default_external_scripts()

        # Build external script tags
        external_script_tags = '\n    '.join(
            f'<script src="{src}"></script>'
            for src in self.external_scripts
        )

        # Build meta tags
        meta_tags = []
        if 'charset' in self.head_meta:
            meta_tags.append(f'<meta charset="{self.head_meta["charset"]}">')
        else:
            meta_tags.append('<meta charset="UTF-8">')

        for name, content in self.head_meta.items():
            if name != 'charset':
                meta_tags.append(f'<meta name="{name}" content="{content}">')

        if 'viewport' not in self.head_meta:
            meta_tags.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')

        meta_tags_html = '\n    '.join(meta_tags)

        # Build title with slide number
        title_text = f"{self.title or 'Slide Deck'} - Slide {index + 1}"

        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="en">',
            '<head>',
            f'    {meta_tags_html}',
            f'    <title>{title_text}</title>',
        ]

        if external_script_tags:
            html_parts.append(f'    {external_script_tags}')

        if self.css:
            html_parts.extend([
                '    <style>',
                self.css,
                '    </style>',
            ])

        html_parts.extend([
            '</head>',
            '<body>',
            '',
            slide.to_html(),
            '',
        ])

        # Use only this slide's scripts (no IIFE needed for isolated render)
        if slide.scripts and slide.scripts.strip():
            html_parts.extend([
                '<script>',
                slide.scripts.strip(),
                '</script>',
            ])

        html_parts.extend([
            '',
            '</body>',
            '</html>',
        ])

        return '\n'.join(html_parts)

    def save(self, output_path: str) -> None:
        """Write knitted HTML to file.
        
        Args:
            output_path: Path to write the HTML file
        """
        html = self.knit()
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding='utf-8')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary for API use.
        
        Returns:
            Dictionary representation of the slide deck including:
            - Aggregated scripts (IIFE-wrapped) at deck level
            - Individual scripts on each slide
        """
        return {
            'title': self.title,
            'slide_count': len(self.slides),
            'css': self.css,
            'external_scripts': self.external_scripts,
            'scripts': self.scripts,  # Aggregated, IIFE-wrapped
            'slides': [
                {
                    'index': idx,
                    'html': slide.to_html(),
                    'slide_id': slide.slide_id,
                    'scripts': slide.scripts,  # Individual slide scripts
                }
                for idx, slide in enumerate(self.slides)
            ]
        }

    def __len__(self) -> int:
        """Return number of slides.
        
        Returns:
            Number of slides in the deck
        """
        return len(self.slides)

    def __iter__(self):
        """Allow iteration over slides.
        
        Returns:
            Iterator over slides
        """
        return iter(self.slides)

    def __getitem__(self, index: int) -> Slide:
        """Allow bracket notation: deck[5].
        
        Args:
            index: Index of slide to retrieve
            
        Returns:
            The Slide object at the specified index
            
        Raises:
            IndexError: If index is out of range
        """
        return self.slides[index]

    def __str__(self) -> str:
        """String representation of the slide deck.
        
        Returns:
            Summary of the slide deck
        """
        return f"SlideDeck(title={self.title!r}, slides={len(self.slides)})"

    def __repr__(self) -> str:
        """Developer-friendly representation of the slide deck.
        
        Returns:
            Detailed string representation for debugging
        """
        return (
            f"SlideDeck(title={self.title!r}, slides={len(self.slides)}, "
            f"css_length={len(self.css)}, scripts_length={len(self.scripts)})"
        )

