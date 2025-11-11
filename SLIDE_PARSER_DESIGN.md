# Slide Deck Parser and Representation Design

## Overview

This document outlines a **simplified approach** for parsing HTML slide decks into a flexible Python representation that supports extraction, manipulation, reordering, and reconstruction of slides.

The design prioritizes **simplicity and robustness** over deep structural parsing, recognizing that AI-generated HTML can vary significantly and attempting to parse every permutation would be fragile and complex.

## Architecture

### High-Level Structure

```
SlideDeck
├── metadata (title, deck name, etc.)
├── css (extracted styles)
├── external_scripts (CDN links)
├── slides (List of Slide objects - raw HTML)
└── scripts (JavaScript including Chart.js)
```

## Core Classes

### 1. `SlideDeck` Class

**Purpose:** Container for the entire slide deck with operations for manipulation and rendering.

**Attributes:**
- `title: Optional[str]` - Deck title (extracted from HTML title or first slide)
- `css: str` - All CSS extracted from `<style>` tags
- `external_scripts: List[str]` - CDN script URLs (Tailwind, Chart.js, etc.)
- `scripts: str` - All JavaScript code (Chart.js configurations, etc.)
- `slides: List[Slide]` - List of slide objects
- `head_meta: Dict[str, str]` - Other metadata from HTML head (charset, viewport, etc.)

**Methods:**
- `from_html(html_path: str) -> SlideDeck` - Class method to parse HTML file
- `from_html_string(html_content: str) -> SlideDeck` - Class method to parse HTML string
- `add_slide(slide: Slide, position: Optional[int] = None)` - Insert slide at position (end if None)
- `remove_slide(index: int) -> Slide` - Remove and return slide at index
- `get_slide(index: int) -> Slide` - Retrieve slide by index
- `move_slide(from_index: int, to_index: int)` - Move slide from one position to another
- `swap_slides(index1: int, index2: int)` - Swap two slides
- `knit() -> str` - Reconstruct complete HTML with all slides
- `render_slide(index: int) -> str` - Render a single slide as complete HTML page
- `save(output_path: str)` - Write knitted HTML to file
- `to_dict() -> dict` - Convert to JSON-serializable dictionary for API use
- `__len__() -> int` - Number of slides
- `__iter__()` - Iterate through slides
- `__getitem__(index: int) -> Slide` - Access slides by index

### 2. `Slide` Class

**Purpose:** Represents a single slide as raw HTML content.

**Attributes:**
- `html: str` - The complete HTML for this slide (the `<div class="slide">...</div>`)
- `slide_id: Optional[str]` - Optional unique identifier for this slide

**Methods:**
- `to_html() -> str` - Return the HTML string (essentially returns `self.html`)
- `clone() -> Slide` - Create a deep copy of this slide
- `__str__() -> str` - String representation showing slide preview

**Rationale:**
Keeping slides as raw HTML provides maximum flexibility:
- Works with any HTML structure the AI generates
- No fragile parsing of internal structure
- Easy to modify HTML directly if needed
- Simple to serialize and deserialize
- Robust to variations in AI output

## HTML Structure Requirements for AI Generator

For the parser to work correctly, the AI-generated HTML **must follow these conventions**:

### Required Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Presentation Title</title>
    
    <!-- External scripts (optional) -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    
    <!-- CSS in <style> tag (required) -->
    <style>
        /* All CSS styles here */
    </style>
</head>
<body>

<!-- Each slide MUST be a <div> with class="slide" -->
<div class="slide">
    <!-- Slide content can be any HTML structure -->
    <h1>Slide Title</h1>
    <div class="subtitle">Subtitle text</div>
    <div class="content">
        <!-- Any content structure -->
    </div>
</div>

<div class="slide">
    <!-- Second slide -->
</div>

<!-- More slides... -->

<!-- JavaScript at end of body (optional) -->
<script>
    // Chart.js configurations and other scripts
</script>

</body>
</html>
```

### Critical Requirements

1. **Slide Class Name** ⚠️ **REQUIRED**
   - Each slide **must** be a `<div>` with `class="slide"`
   - Parser searches for: `soup.find_all('div', class_='slide')`
   - Slides can have additional classes: `class="slide title-slide"` ✅
   - But must include "slide": `class="slide-container"` ❌ (won't match)

2. **CSS in `<style>` Tags**
   - All CSS must be in `<style>` tags (can have multiple)
   - Inline styles on individual elements are preserved but not extracted to global CSS
   - External stylesheets via `<link>` are not currently supported

3. **JavaScript in `<script>` Tags**
   - Inline scripts: `<script>/* code */</script>` 
   - External scripts: `<script src="url"></script>`
   - Parser handles both and preserves them

### Flexible (No Requirements)

- **Slide internal structure**: Any HTML is fine - the parser keeps it as-is
- **HTML formatting**: Can be minified or pretty-printed
- **Slide ordering**: Any order works
- **Number of slides**: No limits
- **Meta tags**: Any meta tags are preserved
- **DOCTYPE**: Any valid DOCTYPE works

### Examples

**✅ Valid HTML (Parser will work):**
```html
<div class="slide">
    <h1>Title</h1>
</div>

<div class="slide title-slide">
    <h1>Special Title Slide</h1>
</div>

<div class="slide" style="background: red;">
    <h1>Inline Styled Slide</h1>
</div>
```

**❌ Invalid HTML (Parser will NOT find these):**
```html
<!-- Missing "slide" class -->
<div class="presentation-slide">
    <h1>Won't be found</h1>
</div>

<!-- Wrong element type -->
<section class="slide">
    <h1>Won't be found</h1>
</section>

<!-- Class name doesn't match -->
<div class="slide-item">
    <h1>Won't be found</h1>
</div>
```

## Parsing Strategy

**Using BeautifulSoup4:**

The parsing strategy is straightforward with only two phases:

### Phase 1: Extract Head Components

1. **Parse HTML Document**
   ```python
   soup = BeautifulSoup(html_content, 'html.parser')
   ```

2. **Extract Metadata**
   - `<title>` → `SlideDeck.title`
   - `<meta>` tags → `SlideDeck.head_meta` dict

3. **Extract CSS**
   - Find `<style>` tag(s) → concatenate into `SlideDeck.css`

4. **Extract Scripts**
   - Find all `<script src="...">` → `SlideDeck.external_scripts` list
   - Find all `<script>` tags with inline code → concatenate into `SlideDeck.scripts`

### Phase 2: Extract Slides

1. **Find All Slide Elements**
   ```python
   slide_elements = soup.find_all('div', class_='slide')
   ```

2. **Convert to Slide Objects**
   - For each slide element:
     - Extract entire outer HTML including the `<div class="slide">` wrapper
     - Create `Slide` object with this HTML
     - Append to `slides` list

**That's it!** No complex parsing of internal structure, no component identification, no special handling.

## Knitting Strategy (Reconstruction)

### HTML Generation Process

**Template Structure:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {external_script_tags}
    <style>{css}</style>
</head>
<body>
{slide_1_html}
{slide_2_html}
...
{slide_n_html}
<script>{scripts}</script>
</body>
</html>
```

**Step-by-Step Assembly:**

1. **Build HTML Header**
   - Add DOCTYPE and `<html>` tag
   - Add meta tags from `SlideDeck.head_meta`
   - Add `<title>` from `SlideDeck.title`
   - Insert external script tags from `SlideDeck.external_scripts`
   - Insert `<style>` block with `SlideDeck.css`

2. **Add Slide HTML**
   - Iterate through `SlideDeck.slides` list
   - For each slide:
     - Call `slide.to_html()` which returns the raw HTML
     - Append to body

3. **Add JavaScript**
   - Insert `<script>` tag with `SlideDeck.scripts`

4. **Finalize HTML**
   - Close `</body>` and `</html>` tags

**That's it!** No complex rendering logic, just string concatenation.

### Rendering Individual Slides

For web frontends that display one slide at a time, we need to render individual slides with all necessary CSS and scripts.

**`render_slide(index: int)` Method:**

Generates a complete, standalone HTML page for a single slide:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Slide {index + 1}</title>
    {external_script_tags}
    <style>{css}</style>
</head>
<body>
{single_slide_html}
<script>{scripts}</script>
</body>
</html>
```

**Use Cases:**
1. **Web viewer**: Backend serves individual slides via API endpoint
2. **Preview mode**: Show specific slide without loading entire deck
3. **Sharing**: Generate shareable link to specific slide

### JSON Representation for APIs

**`to_dict()` Method:**

Returns a JSON-serializable dictionary for web APIs:

```python
{
    "title": "Deck Title",
    "slide_count": 17,
    "css": "/* full CSS content */",
    "external_scripts": [
        "https://cdn.tailwindcss.com",
        "https://cdn.jsdelivr.net/npm/chart.js"
    ],
    "scripts": "/* full JavaScript */",
    "slides": [
        {"index": 0, "html": "<div class='slide'>..."},
        {"index": 1, "html": "<div class='slide'>..."},
        ...
    ]
}
```

**Frontend Usage:**
- Fetch JSON representation once
- Client-side JavaScript shows/hides slides based on navigation
- Or request individual slides via `GET /api/deck/{deck_id}/slide/{index}`

## Key Design Decisions

### 1. Raw HTML for Slides

**Why Raw HTML:**
- **Simplicity:** No complex parsing logic for slide internals
- **Robustness:** Works with any HTML structure, regardless of how the AI formats it
- **Flexibility:** Slides can be edited directly as HTML strings if needed
- **Maintainability:** Much less code to maintain
- **Future-proof:** Works with evolving AI-generated HTML patterns

**Trade-off:**
- Less structured programmatic access to individual slide elements (title, charts, etc.)
- If you need to modify specific parts of a slide, you'd need to parse/manipulate that slide's HTML

**Mitigation:**
- For common operations, we can add helper methods that parse/modify specific slides
- Most use cases (reordering, inserting, removing, cloning) work perfectly with raw HTML

### 2. Python List for Slides

**Why Python List:**
- **O(1) index access** - Critical for web viewers that need specific slides
- **Simple and familiar** - Everyone knows how to use Python lists
- **Built-in methods** - insert(), pop(), slicing, etc.
- **Efficient for typical use** - Slide decks are small (10-50 slides)

**Performance Characteristics:**
- Index access: O(1) ✅
- Append: O(1) ✅
- Insert at position: O(n) - but acceptable for small collections
- Remove at position: O(n) - but acceptable for small collections
- Iteration: O(n) ✅

**Why Not Custom LinkedList:**
- Random access by index is common (web frontend needs specific slides)
- Added complexity not justified for typical slide deck sizes
- O(n) index access in linked list is problematic for viewer use case

### 3. CSS and Script Storage

**Strategy: Global Storage**
- Store all CSS as a single string in `SlideDeck.css`
- Store all JavaScript as a single string in `SlideDeck.scripts`
- Store external script URLs in `SlideDeck.external_scripts` list

**Rationale:**
- CSS and JavaScript are typically shared across all slides
- Simplifies knitting - just insert once in the header/footer
- Allows global theme changes by modifying CSS
- No need to track which scripts belong to which slides

## Implementation Phases

### Phase 1: Core Data Structures
- Implement `Slide` class (simple wrapper for HTML string)
- Implement basic `SlideDeck` class structure
- Write tests for Slide class

### Phase 2: HTML Parsing
- Implement `SlideDeck` class with attributes
- Implement HTML parsing with BeautifulSoup4:
  - Extract CSS from `<style>` tags
  - Extract scripts from `<script>` tags
  - Extract external script URLs from `<script src="...">`
  - Extract metadata from `<head>`
  - Find all slide divs and extract raw HTML
- Write tests for parsing

### Phase 3: Knitting (Reconstruction)
- Implement `SlideDeck.knit()` method (full deck)
- Implement `SlideDeck.render_slide(index)` method (single slide)
- Generate complete HTML from components
- Handle proper formatting and indentation
- Write tests for round-trip (parse → knit → parse)

### Phase 4: Slide Operations
- Implement `add_slide()`, `remove_slide()`, `get_slide()`
- Implement `move_slide()` and `swap_slides()`
- Add iteration and indexing support
- Write tests for all operations

### Phase 5: Web API Support
- Implement `to_dict()` method for JSON serialization
- Add validation and error handling
- Write tests for API methods

### Phase 6: Convenience Methods
- Implement `save()` method to write HTML to file
- Add `clone()` for slides
- Add helper methods as needed
- Write integration tests

## Testing Strategy

### Unit Tests
- Slide creation and cloning
- SlideDeck list operations (add, remove, move, swap)
- CSS and script extraction
- Individual parsing methods

### Integration Tests
- Parse complete HTML file → verify all components extracted
- Knit reconstructed HTML → verify structure matches
- Manipulate slides (reorder, insert, remove) → verify output

### Round-trip Validation
- Parse → Knit → Parse → Compare structures
- Verify all CSS, scripts, and slides preserved
- Check slide count and order maintained

## File Structure

```
src/
├── models/
│   ├── __init__.py
│   ├── slide_deck.py          # SlideDeck class with parsing and knitting
│   └── slide.py               # Slide class (simple HTML wrapper)
└── utils/
    └── __init__.py

tests/
├── __init__.py
├── test_slide.py              # Test Slide class
├── test_slide_deck.py         # Test SlideDeck parsing, knitting, and operations
└── fixtures/
    └── sample_slides.html     # Sample HTML for testing
```

## Dependencies

- **BeautifulSoup4** (bs4): HTML parsing
- **lxml**: Fast HTML parser backend for BeautifulSoup
- **typing**: Type hints for better code clarity
- **pytest**: Testing framework

## Implementation Notes

### SlideDeck Methods Using Python List

The `SlideDeck` methods are straightforward wrappers around Python list operations:

```python
class SlideDeck:
    def __init__(self):
        self.slides: List[Slide] = []
        # ... other attributes
    
    def add_slide(self, slide: Slide, position: Optional[int] = None):
        """Insert slide at position (or append if position is None)"""
        if position is None:
            self.slides.append(slide)
        else:
            self.slides.insert(position, slide)
    
    def remove_slide(self, index: int) -> Slide:
        """Remove and return slide at index"""
        return self.slides.pop(index)
    
    def get_slide(self, index: int) -> Slide:
        """Get slide at index"""
        return self.slides[index]
    
    def move_slide(self, from_index: int, to_index: int):
        """Move slide from one position to another"""
        slide = self.slides.pop(from_index)
        self.slides.insert(to_index, slide)
    
    def swap_slides(self, index1: int, index2: int):
        """Swap two slides"""
        self.slides[index1], self.slides[index2] = self.slides[index2], self.slides[index1]
    
    def __len__(self) -> int:
        """Return number of slides"""
        return len(self.slides)
    
    def __iter__(self):
        """Allow iteration over slides"""
        return iter(self.slides)
    
    def __getitem__(self, index: int) -> Slide:
        """Allow bracket notation: deck[5]"""
        return self.slides[index]
```

All operations are simple, readable, and efficient!

## Example Usage

```python
from src.models.slide_deck import SlideDeck
from src.models.slide import Slide

# Parse existing HTML file
deck = SlideDeck.from_html("output/slides_20251107_112439.html")

# Access basic info
print(f"Deck title: {deck.title}")
print(f"Number of slides: {len(deck)}")

# Access individual slides
first_slide = deck.get_slide(0)
print(f"First slide HTML preview: {first_slide.html[:100]}...")

# Iterate through all slides
for i, slide in enumerate(deck):
    print(f"Slide {i}: {len(slide.html)} characters")

# Reorder slides (move slide 5 to position 2)
deck.move_slide(from_index=5, to_index=2)  # Uses list.pop() and list.insert()

# Swap two adjacent slides
deck.swap_slides(3, 4)  # Simple list element swap

# Remove a slide
removed_slide = deck.remove_slide(8)  # Uses list.pop(index)
print(f"Removed slide: {len(removed_slide.html)} characters")

# Add a new slide (create from HTML string)
new_slide_html = '''
<div class="slide">
    <h1>New Analysis Slide</h1>
    <div class="subtitle">Q4 Performance Deep Dive</div>
    <div class="content">
        <p>Additional analysis content here...</p>
    </div>
    <div class="footer">Company Name | Report</div>
</div>
'''
new_slide = Slide(html=new_slide_html)
deck.add_slide(new_slide, position=4)  # Insert at position 4

# Clone an existing slide
slide_to_duplicate = deck.get_slide(2)
cloned_slide = slide_to_duplicate.clone()
deck.add_slide(cloned_slide, position=3)  # Insert clone after original

# Modify CSS globally (e.g., change brand color)
deck.css = deck.css.replace('#EB4A34', '#00A3E0')  # Change red to blue

# Reconstruct complete HTML
html_output = deck.knit()

# Save to new file
deck.save("output/modified_slides.html")

# Access by index
last_slide = deck[-1]  # Using __getitem__

# ========================================
# Web Frontend Use Cases
# ========================================

# Render individual slide for web viewer
slide_html = deck.render_slide(5)  # Get complete HTML for slide 5
# This can be served via Flask/FastAPI endpoint

# Get JSON representation for API
deck_json = deck.to_dict()
# Returns dict that can be serialized with json.dumps()

# Example Flask endpoint:
# @app.route('/api/deck/<deck_id>/slide/<int:index>')
# def get_slide(deck_id, index):
#     deck = load_deck(deck_id)  # Load from storage
#     return deck.render_slide(index)

# Example FastAPI endpoint for full deck as JSON:
# @app.get("/api/deck/{deck_id}")
# async def get_deck(deck_id: str):
#     deck = SlideDeck.from_html(f"output/{deck_id}.html")
#     return deck.to_dict()
```

## Web Frontend Architecture Options

There are two main approaches for displaying slides one at a time in a web interface:

### Option 1: Server-Side Rendering (Recommended for Simple Cases)

**How it works:**
1. Backend loads `SlideDeck` from HTML file
2. Client requests specific slide: `GET /api/deck/{deck_id}/slide/{slide_index}`
3. Backend calls `deck.render_slide(slide_index)`
4. Returns complete HTML page with CSS and scripts
5. Client displays the HTML
6. Navigation buttons request next/previous slide

**Pros:**
- Simple implementation
- Each slide loads independently
- Lighter initial page load
- Easy to implement slide sharing (unique URL per slide)

**Cons:**
- Full page reload on navigation (unless using AJAX/fetch)
- Slight delay between slides
- Charts re-initialize on each load

**Code Example:**
```python
from flask import Flask, render_template_string
from src.models.slide_deck import SlideDeck

app = Flask(__name__)

# Load deck once at startup
deck = SlideDeck.from_html("output/slides.html")

@app.route('/deck/slide/<int:index>')
def view_slide(index):
    if 0 <= index < len(deck):
        slide_html = deck.render_slide(index)
        return slide_html
    return "Slide not found", 404

@app.route('/deck/slide/<int:index>/next')
def next_slide(index):
    next_index = min(index + 1, len(deck) - 1)
    return redirect(f'/deck/slide/{next_index}')
```

### Option 2: Client-Side Rendering (Recommended for Smooth Experience)

**How it works:**
1. Backend loads `SlideDeck` from HTML file
2. Client requests deck data: `GET /api/deck/{deck_id}`
3. Backend calls `deck.to_dict()` and returns JSON
4. Client JavaScript receives all slides, CSS, and scripts
5. Client builds page with CSS in `<style>` and scripts in `<script>`
6. JavaScript shows/hides slides based on current index
7. Navigation is instant (no network calls)

**Pros:**
- Instant slide transitions
- Smooth animations possible
- Charts stay alive (no re-initialization)
- Better user experience

**Cons:**
- Larger initial load (all slides at once)
- More complex frontend code
- All slides must fit in memory

**Code Example:**
```python
# Backend (FastAPI)
from fastapi import FastAPI
from src.models.slide_deck import SlideDeck

app = FastAPI()

@app.get("/api/deck/{deck_id}")
async def get_deck(deck_id: str):
    deck = SlideDeck.from_html(f"output/{deck_id}.html")
    return deck.to_dict()
```

```javascript
// Frontend (JavaScript)
async function loadDeck(deckId) {
    const response = await fetch(`/api/deck/${deckId}`);
    const deck = await response.json();
    
    // Inject CSS
    const style = document.createElement('style');
    style.textContent = deck.css;
    document.head.appendChild(style);
    
    // Inject external scripts
    deck.external_scripts.forEach(src => {
        const script = document.createElement('script');
        script.src = src;
        document.head.appendChild(script);
    });
    
    // Inject slides into container (hidden initially)
    const container = document.getElementById('slides-container');
    deck.slides.forEach((slide, idx) => {
        const div = document.createElement('div');
        div.innerHTML = slide.html;
        div.style.display = idx === 0 ? 'block' : 'none';
        div.dataset.slideIndex = idx;
        container.appendChild(div);
    });
    
    // Inject scripts
    const scriptTag = document.createElement('script');
    scriptTag.textContent = deck.scripts;
    document.body.appendChild(scriptTag);
    
    return deck;
}

function showSlide(index) {
    document.querySelectorAll('[data-slide-index]').forEach((slide, idx) => {
        slide.style.display = idx === index ? 'block' : 'none';
    });
}

// Navigation
document.getElementById('next-btn').addEventListener('click', () => {
    currentSlide = Math.min(currentSlide + 1, totalSlides - 1);
    showSlide(currentSlide);
});
```

### Hybrid Approach

Combine both methods:
- Initial load uses `to_dict()` for fast first-slide display
- Lazy load remaining slides in background
- Option to deep-link to specific slides via `render_slide()`

## Future Enhancements (Optional)

If needed, we can add these features later:

1. **Slide Metadata Extraction**: Parse titles, subtitles from HTML for easier slide identification
2. **Theme Support**: Swap CSS easily for different visual themes
3. **Slide Templates**: Pre-built slide HTML templates for creating new slides
4. **Export Formats**: PDF generation via libraries like `weasyprint` or `playwright`
5. **Merge Operations**: Combine multiple SlideDeck objects
6. **Search**: Find slides containing specific text or elements
7. **Diff/Compare**: Visual comparison between slide deck versions

## Conclusion

This **simplified design** provides a robust, maintainable framework for working with AI-generated HTML slide decks:

### Benefits:
- **Simple**: Only 2 core classes (SlideDeck, Slide)
- **Robust**: Works with any HTML structure without fragile parsing
- **Flexible**: Easy to manipulate slides using familiar Python list operations
- **Maintainable**: Minimal code, easy to understand and extend
- **Performant**: O(1) index access for web viewers
- **Future-proof**: Handles evolving AI-generated HTML patterns

### Core Capabilities:
- ✅ Parse HTML slide decks
- ✅ Extract CSS, scripts, and metadata
- ✅ Store slides as Python list
- ✅ Reorder, insert, remove, swap slides with O(1) index access
- ✅ Reconstruct complete HTML (knit)
- ✅ Render individual slides for web frontends
- ✅ JSON serialization for APIs
- ✅ Save to file

### Web Frontend Support:
The design fully supports web-based slide viewers with two approaches:
- **Server-side rendering**: `render_slide(index)` generates complete HTML for each slide
- **Client-side rendering**: `to_dict()` provides JSON for JavaScript-based navigation

Both approaches leverage the same underlying data structure, providing flexibility in how you build the frontend.

The implementation is straightforward and can be completed in a few focused sessions. Using Python's built-in list makes the code simple, familiar, and efficient for the web viewer use case.

## AI Slide Generator Prompt Instructions

Add these instructions to the AI slide generator's system prompt to ensure HTML compatibility with this parser:

### Required Prompt Addition

```markdown
## HTML Structure Requirements

When generating HTML slide decks, you MUST follow these conventions:

### Mandatory Requirements

1. **Slide Container Class**
   - Every slide must be wrapped in: `<div class="slide">...</div>`
   - The class name MUST be exactly "slide" (lowercase)
   - You can add additional classes: `<div class="slide title-slide">` ✅
   - But "slide" class MUST be present

2. **CSS Placement**
   - All CSS must be in `<style>` tags within `<head>`
   - Multiple `<style>` tags are fine
   - Do not use external `<link>` stylesheets

3. **JavaScript Placement**
   - External scripts: `<script src="..."></script>` in `<head>`
   - Inline scripts: `<script>...</script>` at end of `<body>`

### Template Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{Presentation Title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        /* All CSS here */
    </style>
</head>
<body>

<div class="slide">
    <!-- First slide content -->
</div>

<div class="slide">
    <!-- Second slide content -->
</div>

<!-- More slides... -->

<script>
    // Chart.js and other JavaScript here
</script>

</body>
</html>
```

### Flexible (No Constraints)

- Slide internal structure can be any valid HTML
- Use any CSS classes/styles within slides
- Any number of slides
- Any meta tags in head
```

### Integration with Existing Prompts

If your current AI slide generator prompt is in `config/prompts.yaml`, add this section:

```yaml
html_structure_requirements: |
  CRITICAL: All slides must use <div class="slide"> as the container.
  - Use: <div class="slide">content</div> ✅
  - NOT: <section class="slide"> ❌
  - NOT: <div class="presentation-slide"> ❌
  
  CSS must be in <style> tags in <head>.
  JavaScript can be inline <script> or external <script src="">.
  
  The slide class name "slide" is required for the parser to extract slides.
```

### Validation Checklist

Before the AI generates HTML, ensure it will:
- ✅ Wrap each slide in `<div class="slide">`
- ✅ Place all CSS in `<style>` tags
- ✅ Use `<script>` tags for JavaScript
- ✅ Generate valid, well-formed HTML

### Example Verification

After generation, this BeautifulSoup search should find all slides:
```python
soup = BeautifulSoup(html, 'html.parser')
slides = soup.find_all('div', class_='slide')
assert len(slides) > 0, "No slides found! Check class='slide' is present"
```

