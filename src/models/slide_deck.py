"""SlideDeck class for parsing, manipulating, and reconstructing HTML slide decks."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.utils.html_utils import extract_canvas_ids_from_script

from .slide import Slide


@dataclass
class ScriptBlock:
    """Represents a JavaScript block and its associated canvas ids."""

    key: str
    text: str
    canvas_ids: set[str]


class SlideDeck:
    """Container for an entire slide deck with operations for manipulation and rendering.
    
    This class parses HTML slide decks, stores slides as raw HTML, and provides
    methods for reordering, inserting, removing slides, and reconstructing HTML.
    
    Attributes:
        title: Deck title (extracted from HTML title or first slide)
        css: All CSS extracted from <style> tags
        external_scripts: List of CDN script URLs (Tailwind, Chart.js, etc.)
        scripts: All JavaScript code (Chart.js configurations, etc.)
        script_blocks: Ordered mapping of script blocks and their canvas ids
        slides: List of Slide objects
        head_meta: Other metadata from HTML head (charset, viewport, etc.)
    """
    
    CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js"

    def __init__(
        self,
        title: Optional[str] = None,
        css: str = "",
        external_scripts: Optional[List[str]] = None,
        scripts: str = "",
        slides: Optional[List[Slide]] = None,
        head_meta: Optional[Dict[str, str]] = None,
        script_blocks: Optional[OrderedDict[str, ScriptBlock]] = None,
        canvas_to_script: Optional[Dict[str, str]] = None,
    ):
        """Initialize a SlideDeck.
        
        Args:
            title: Deck title
            css: CSS content
            external_scripts: List of external script URLs
            scripts: JavaScript content
            slides: List of Slide objects
            head_meta: Metadata from HTML head
            script_blocks: Optional ordered mapping of script blocks to metadata
            canvas_to_script: Optional reverse index from canvas id to script key
        """
        self.title = title
        self.css = css
        self.external_scripts = external_scripts or []
        self.scripts = scripts
        self.slides = slides or []
        self.head_meta = head_meta or {}
        self.script_blocks: OrderedDict[str, ScriptBlock] = script_blocks or OrderedDict()
        self.canvas_to_script: Dict[str, str] = canvas_to_script or {}
        self._ensure_default_external_scripts()
        
        if self.script_blocks and not self.canvas_to_script:
            self._rebuild_canvas_index()
        
        if self.script_blocks:
            self.recompute_scripts()

    def _ensure_default_external_scripts(self) -> None:
        """Ensure required third-party scripts are included when knitting."""
        if self.CHART_JS_URL not in self.external_scripts:
            self.external_scripts.append(self.CHART_JS_URL)
    
    def _rebuild_canvas_index(self) -> None:
        """Rebuild mapping of canvas ids to script blocks."""
        self.canvas_to_script = {}
        for block in self.script_blocks.values():
            for canvas_id in block.canvas_ids:
                self.canvas_to_script[canvas_id] = block.key
    
    @staticmethod
    def _generate_script_key(canvas_ids: List[str], index: int) -> str:
        """Generate deterministic key for a script block."""
        if canvas_ids:
            primary = canvas_ids[0]
            return f"canvas:{primary}:{index}"
        return f"script:{index}"
    
    def recompute_scripts(self) -> None:
        """Regenerate aggregated script string from structured blocks."""
        parts = [
            block.text.strip()
            for block in self.script_blocks.values()
            if block.text.strip()
        ]
        self.scripts = "\n\n".join(parts)
    
    def remove_canvas_scripts(self, canvas_ids: List[str]) -> None:
        """Remove script blocks associated with specified canvas ids."""
        if not canvas_ids:
            return
        
        keys_to_remove: set[str] = set()
        for canvas_id in canvas_ids:
            key = self.canvas_to_script.pop(canvas_id, None)
            if not key:
                continue
            block = self.script_blocks.get(key)
            if not block:
                continue
            block.canvas_ids.discard(canvas_id)
            if not block.canvas_ids:
                keys_to_remove.add(key)
        
        if not keys_to_remove:
            return
        
        for key in keys_to_remove:
            self.script_blocks.pop(key, None)
        
        self.recompute_scripts()
    
    def add_script_block(self, script_text: str, canvas_ids: List[str]) -> None:
        """Add (or replace) a script block for the provided canvas ids."""
        if not script_text or not script_text.strip():
            return
        
        cleaned = script_text.strip()
        canvas_ids = [cid for cid in canvas_ids if cid]
        
        if canvas_ids:
            self.remove_canvas_scripts(canvas_ids)
        
        else:
            existing_key = next(
                (
                    key
                    for key, block in self.script_blocks.items()
                    if block.text == cleaned and not block.canvas_ids
                ),
                None,
            )
            if existing_key:
                self.script_blocks[existing_key].text = cleaned
                self.recompute_scripts()
                return
        
        key = self._generate_script_key(canvas_ids, len(self.script_blocks))
        block = ScriptBlock(key=key, text=cleaned, canvas_ids=set(canvas_ids))
        self.script_blocks[key] = block
        for canvas_id in canvas_ids:
            self.canvas_to_script[canvas_id] = key
        
        self.recompute_scripts()
    
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
        head_meta = {}
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
        
        # Extract inline scripts
        script_blocks: OrderedDict[str, ScriptBlock] = OrderedDict()
        canvas_to_script: Dict[str, str] = {}
        inline_scripts = soup.find_all('script', src=False)
        for idx, script_tag in enumerate(inline_scripts):
            script_content = script_tag.string or script_tag.get_text()
            if not script_content:
                continue
            cleaned = script_content.strip()
            canvas_ids = extract_canvas_ids_from_script(cleaned)
            key = cls._generate_script_key(canvas_ids, idx)
            block = ScriptBlock(key=key, text=cleaned, canvas_ids=set(canvas_ids))
            script_blocks[key] = block
            for canvas_id in canvas_ids:
                canvas_to_script[canvas_id] = key
        
        # Phase 2: Extract Slides
        slide_elements = soup.find_all('div', class_='slide')
        slides = []
        for idx, slide_element in enumerate(slide_elements):
            # Get the outer HTML including the <div class="slide"> wrapper
            slide_html = str(slide_element)
            slide = Slide(html=slide_html, slide_id=f"slide_{idx}")
            slides.append(slide)
        
        return cls(
            title=title,
            css=css,
            external_scripts=external_scripts,
            scripts="",
            slides=slides,
            head_meta=head_meta,
            script_blocks=script_blocks,
            canvas_to_script=canvas_to_script,
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
            Dictionary representation of the slide deck
        """
        return {
            'title': self.title,
            'slide_count': len(self.slides),
            'css': self.css,
            'external_scripts': self.external_scripts,
            'scripts': self.scripts,
            'slides': [
                {
                    'index': idx,
                    'html': slide.to_html(),
                    'slide_id': slide.slide_id
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

