"""SlideDeck class for parsing, manipulating, and reconstructing HTML slide decks."""

from typing import List, Optional, Dict, Any
from pathlib import Path
from bs4 import BeautifulSoup
from .slide import Slide


class SlideDeck:
    """Container for an entire slide deck with operations for manipulation and rendering.
    
    This class parses HTML slide decks, stores slides as raw HTML, and provides
    methods for reordering, inserting, removing slides, and reconstructing HTML.
    
    Attributes:
        title: Deck title (extracted from HTML title or first slide)
        css: All CSS extracted from <style> tags
        external_scripts: List of CDN script URLs (Tailwind, Chart.js, etc.)
        scripts: All JavaScript code (Chart.js configurations, etc.)
        slides: List of Slide objects
        head_meta: Other metadata from HTML head (charset, viewport, etc.)
    """
    
    def __init__(
        self,
        title: Optional[str] = None,
        css: str = "",
        external_scripts: Optional[List[str]] = None,
        scripts: str = "",
        slides: Optional[List[Slide]] = None,
        head_meta: Optional[Dict[str, str]] = None
    ):
        """Initialize a SlideDeck.
        
        Args:
            title: Deck title
            css: CSS content
            external_scripts: List of external script URLs
            scripts: JavaScript content
            slides: List of Slide objects
            head_meta: Metadata from HTML head
        """
        self.title = title
        self.css = css
        self.external_scripts = external_scripts or []
        self.scripts = scripts
        self.slides = slides or []
        self.head_meta = head_meta or {}
    
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
        script_parts = []
        for script_tag in soup.find_all('script', src=False):
            if script_tag.string:
                script_parts.append(script_tag.string)
        scripts = '\n'.join(script_parts)
        
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
            scripts=scripts,
            slides=slides,
            head_meta=head_meta
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

