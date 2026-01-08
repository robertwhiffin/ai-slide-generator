## HTML Manipulation Architecture

This document explains how agent-generated HTML flows through the system, how CSS and scripts are managed during edits, and how the frontend renders slides. It walks through key files plus code excerpts so new contributors can jump in quickly.

Use this alongside:
- `frontend-overview.md` for UI layout/state ownership and API usage.
- `backend-overview.md` for FastAPI/LangChain architecture, session model, and endpoint contracts.

The pipeline narrative below focuses on the shared HTML/CSS/script path that connects those two layers.

---

### 1. High-Level Data Flow
1. **Agent Output** (LLM via prompts from database)
   - Returns full HTML or replacement slide blocks plus scripts and CSS.
   - Prompt enforces "one canvas per script" (`// Canvas: <id>` comment, unique variable names).
   - Prompt assembly order: Deck Prompt → Slide Style → System Prompt → Editing Instructions.
2. **Backend Parsing & Storage**
   - `SlideDeck.from_html_string` (`src/domain/slide_deck.py`) parses HTML into slides with scripts attached directly to each `Slide` object.
   - `_parse_slide_replacements` (`src/services/agent.py`) extracts slides as `Slide` objects with scripts via canvas ID matching.
   - `ChatService` (`src/api/services/chat_service.py`) merges CSS and replaces slides (scripts travel with them).
3. **API Layer**
   - REST endpoints in `src/api/routes/slides.py` expose deck operations (get, reorder, update, duplicate, delete).
4. **Frontend Consumption**
   - `frontend/src/services/api.ts` talks to `/api/chat` and `/api/slides`.
   - `ChatPanel` feeds new decks into React state; `SlidePanel` renders individual slides using `slide.scripts`.

---

### 2. Inline Scripts Architecture

Scripts are stored directly on `Slide` objects. This ensures that when a slide is deleted or replaced, its scripts are automatically removed—no orphaned scripts possible.

```
Slide {
    html: str       # The <div class="slide">...</div> HTML
    slide_id: str   # Unique identifier like "slide_0"
    scripts: str    # JavaScript for this slide's charts
}
```

#### 2.1 SlideDeck Parsing

```python
# src/domain/slide_deck.py
@classmethod
def from_html_string(cls, html_content: str) -> 'SlideDeck':
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Phase 1: Parse slides and build canvas-to-slide index
    slide_elements = soup.find_all('div', class_='slide')
    slides = []
    canvas_to_slide: Dict[str, int] = {}  # canvas_id -> slide_index
    
    for idx, slide_element in enumerate(slide_elements):
        slide = Slide(html=str(slide_element), slide_id=f"slide_{idx}")
        slides.append(slide)
        # Index canvases in this slide
        for canvas in slide_element.find_all('canvas'):
            canvas_id = canvas.get('id')
            if canvas_id:
                canvas_to_slide[canvas_id] = idx
    
    # Phase 2: Parse scripts and assign to slides via canvas matching
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
```

Key points:
- **Canvas-to-slide index**: Maps canvas IDs to slide indices for script assignment.
- **Multi-canvas splitting**: `split_script_by_canvas()` splits monolithic scripts into per-canvas segments.
- **Fallback assignment**: Scripts without recognizable canvas IDs go to the last slide.

#### 2.2 IIFE Wrapping for Aggregated Scripts

When all scripts need to run in the same document (presentation mode, `knit()` output), they're wrapped in IIFEs to prevent variable collisions:

```python
# src/domain/slide_deck.py
@property
def scripts(self) -> str:
    """Aggregate all slide scripts with IIFE wrapping for scope isolation."""
    parts = []
    for slide in self.slides:
        if slide.scripts and slide.scripts.strip():
            wrapped = f"(function() {{\n{slide.scripts.strip()}\n}})();"
            parts.append(wrapped)
    return "\n\n".join(parts)
```

This ensures that `const canvas1` in one slide doesn't conflict with `const canvas1` in another slide.

#### 2.3 Script Splitting Heuristics

The `split_script_by_canvas()` function (`src/utils/html_utils.py`) detects chart block boundaries by looking for:

1. `// Canvas: <id>` comment markers (most specific)
2. `// Chart N:` comment patterns
3. Variable declarations near `getElementById()` calls

This prevents the "Identifier already declared" error when editing a single chart in a deck that originally had a monolithic multi-chart script block.

#### 2.4 Canvas Extraction Heuristics
```python
# src/utils/html_utils.py
CANVAS_ID_PATTERN = re.compile(r"getElementById\s*\(\s*['\"]([\w\-.:]+)['\"]\s*\)")
QUERY_SELECTOR_PATTERN = re.compile(r"querySelector\s*\(\s*['\"]#([\w\-.:]+)['\"]\s*\)")
CANVAS_COMMENT_PATTERN = re.compile(r"//\s*Canvas:\s*([\w\-.:]+)", re.IGNORECASE)

def extract_canvas_ids_from_script(script_text: str) -> List[str]:
    matches = CANVAS_ID_PATTERN.findall(script_text)
    matches.extend(QUERY_SELECTOR_PATTERN.findall(script_text))
    matches.extend(CANVAS_COMMENT_PATTERN.findall(script_text))
    ...
```

- Detects canvases mentioned via `getElementById`, `querySelector('#id')`, or an explicit `// Canvas: foo` comment.
- Order is preserved and duplicates removed.

#### 2.5 CSS Parsing & Merging

When editing slides, the LLM may return updated CSS (e.g., changing a box color). The system extracts and merges CSS selectors so edits override matching rules while preserving unrelated styles.

```python
# src/utils/css_utils.py
def merge_css(existing_css: str, replacement_css: str) -> str:
    """Merge replacement CSS rules into existing CSS.
    
    - Rules in replacement_css override matching selectors
    - New selectors from replacement_css are appended
    - Existing selectors not in replacement_css are preserved
    """
    existing_rules = parse_css_rules(existing_css)
    replacement_rules = parse_css_rules(replacement_css)
    existing_rules.update(replacement_rules)
    # Reconstruct CSS...
```

- Uses `tinycss2` for robust CSS parsing (handles complex selectors, gradients, etc.).
- `SlideDeck.update_css(replacement_css)` wraps the merge and updates `self.css`.
- Graceful fallback: if parsing fails, the original CSS is preserved unchanged.

---

### 3. Agent Parsing & Slide Replacement

#### 3.1 Agent Response Parsing

`_parse_slide_replacements` (`src/services/agent.py`) returns `Slide` objects with scripts attached:

```python
def _parse_slide_replacements(self, llm_response: str, original_indices: list[int]) -> dict:
    soup = BeautifulSoup(llm_response, "html.parser")
    slide_divs = soup.find_all("div", class_="slide")
    
    # Build slides and canvas-to-slide index
    replacement_slides: list[Slide] = []
    canvas_to_slide: dict[str, int] = {}
    
    for idx, slide_div in enumerate(slide_divs):
        slide = Slide(html=str(slide_div), slide_id=f"slide_{idx}")
        replacement_slides.append(slide)
        for canvas in slide_div.find_all("canvas"):
            canvas_id = canvas.get("id")
            if canvas_id:
                canvas_to_slide[canvas_id] = idx
    
    # Assign scripts to slides via canvas matching
    for script_tag in soup.find_all("script", src=False):
        script_text = script_tag.get_text() or ""
        segments = split_script_by_canvas(script_text)
        for segment_text, canvas_ids in segments:
            for canvas_id in canvas_ids:
                if canvas_id in canvas_to_slide:
                    replacement_slides[canvas_to_slide[canvas_id]].scripts += segment_text
                    break
    
    return {
        "replacement_slides": replacement_slides,  # Slide objects with scripts
        "replacement_css": ...,
        ...
    }
```

#### 3.2 ChatService Replacement Flow

`ChatService` coordinates agent interactions and handles targeted edits:

```python
# src/api/services/chat_service.py
def _apply_slide_replacements(self, replacement_info: dict, session_id: str) -> dict:
    current_deck = self._get_or_load_deck(session_id)
    
    start_idx = replacement_info["start_index"]
    original_count = replacement_info["original_count"]
    replacement_slides: List[Slide] = replacement_info["replacement_slides"]
    
    # Remove original slides (scripts go with them automatically)
    for _ in range(original_count):
        current_deck.remove_slide(start_idx)
    
    # Insert replacement slides (scripts already attached)
    for idx, slide in enumerate(replacement_slides):
        slide.slide_id = f"slide_{start_idx + idx}"
        current_deck.insert_slide(slide, start_idx + idx)
    
    # Merge replacement CSS
    if replacement_info.get("replacement_css"):
        current_deck.update_css(replacement_info["replacement_css"])
    
    return current_deck.to_dict()
```

Key simplification: **No manual script cleanup needed**. When a slide is removed, its scripts are removed automatically. When a slide is inserted, its scripts come with it.

---

### 4. API Surface
- `POST /api/chat` (see `src/api/routes/chat.py` via `ChatService.send_message`) returns:
  - `slide_deck`: serialized `SlideDeck` with per-slide scripts.
  - `raw_html`: canonical HTML string.
  - `replacement_info`: metadata for UI messaging (sanitized to remove Slide objects).
- `GET /api/slides`, `PUT /api/slides/reorder`, `PATCH /api/slides/{index}`, etc. are thin wrappers around `ChatService` helpers.

`frontend/src/services/api.ts` wraps these endpoints. Example:
```typescript
export const api = {
  async getSlides(): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides`);
    ...
  },
  async reorderSlides(newOrder: number[]): Promise<SlideDeck> { ... },
  async updateSlide(index: number, html: string): Promise<Slide> { ... },
};
```

---

### 5. Frontend Rendering & Editing

#### 5.1 React State Ownership
- `frontend/src/components/Layout/AppLayout.tsx` keeps `slideDeck` and `rawHtml` in React state.
- `ChatPanel` receives only `rawHtml`; once the backend responds, it calls `onSlidesGenerated(deck, raw)` to update global state.

#### 5.2 SlideTile Rendering

Each slide is rendered in its own `<iframe>` using **only that slide's scripts** (no IIFE needed since each iframe has isolated scope):

```tsx
// frontend/src/components/SlidePanel/SlideTile.tsx
const slideHTML = useMemo(() => {
  const slideScripts = slide.scripts || '';
  return `
<!DOCTYPE html>
<html lang="en">
<head>
  ${slideDeck.external_scripts.map(src => `<script src="${src}"></script>`).join('\n')}
  <style>${slideDeck.css}</style>
</head>
<body>
  ${slide.html}
  ${slideScripts ? `<script>${slideScripts}</script>` : ''}
</body>
</html>`.trim();
}, [slide.html, slide.scripts, slideDeck.css, slideDeck.external_scripts]);
```

Key improvement: No more try-catch around scripts—each slide only runs its own code.

#### 5.3 Presentation Mode & Raw HTML

For presentation mode and raw HTML views, all slides are rendered together. These use `slideDeck.scripts` which returns IIFE-wrapped aggregated scripts:

```tsx
// Used in PresentationMode.tsx, SlidePanel.tsx (raw view)
${slideDeck.scripts}  // IIFE-wrapped, safe for shared scope
```

#### 5.4 Slide Selection & Context
- `SelectionContext` tracks selected slide indices/HTML.
- `SlideSelection` and `SlideTile` share this context so the user can highlight slides before requesting edits.
- Backend becomes the single source of truth for script state.

---

### 6. Integrity Guarantees

#### 6.1 Script Integrity
1. **Inline storage**: Scripts are stored on `Slide` objects—when a slide is removed, its scripts are automatically removed.
2. **Canvas-aware splitting**: Multi-canvas scripts are split and assigned to the correct slides during parsing.
3. **IIFE wrapping**: Aggregated scripts (for presentation mode) are wrapped in IIFEs to prevent variable collisions.
4. **Fallback assignment**: Scripts without canvas IDs are assigned to the last slide.
5. **No orphans**: The slide-owns-scripts model eliminates orphaned script blocks.

#### 6.2 CSS Integrity
1. **Selector-level merging** ensures edits only affect the CSS rules they modify; unrelated styles are preserved.
2. **Graceful fallback** preserves original CSS if parsing fails (e.g., malformed LLM output).
3. **Consistent formatting** reconstructs CSS with uniform spacing after merge.

#### 6.3 Slide Validation
- Slides are identified by BeautifulSoup's `find_all("div", class_="slide")`, which correctly matches multi-class elements like `class="slide title-slide"`.
- Empty slide content is rejected with a descriptive error.

---

### 7. Key Files to Review
| Concern | File |
| --- | --- |
| Prompt / LLM Output Rules | `config/prompts.yaml` |
| Slide class with scripts | `src/domain/slide.py` |
| SlideDeck parsing & IIFE aggregation | `src/domain/slide_deck.py` |
| Canvas heuristics & script splitting | `src/utils/html_utils.py` (`split_script_by_canvas`, `extract_canvas_ids_from_script`) |
| CSS parsing & merging | `src/utils/css_utils.py` |
| Agent response extraction | `src/services/agent.py` (`_parse_slide_replacements`) |
| Chat orchestration & replacements | `src/api/services/chat_service.py` |
| REST endpoints | `src/api/routes/slides.py`, `src/api/routes/chat.py` |
| React state & views | `frontend/src/components/Layout/AppLayout.tsx`, `frontend/src/components/ChatPanel`, `frontend/src/components/SlidePanel` |
| API client | `frontend/src/services/api.ts` |
| TypeScript types | `frontend/src/types/slide.ts` |
| Tests | `tests/unit/test_html_utils.py`, `tests/unit/test_slide_deck.py`, `tests/unit/test_slide_replacements.py` |

---

### 8. Future Enhancements
- Consider storing per-slide script hashes so we can detect no-op edits.
- CSS diff visualization: show users which selectors were modified during edits.
- Scoped CSS: consider prefixing selectors per-slide to prevent style leakage between slides.
- Global scripts: add a `SlideDeck.global_scripts` field for truly shared utility functions.

With these pieces, contributors can trace exactly how HTML is parsed, transformed, and rendered across the stack. For deeper dives, start with `Slide` and `SlideDeck`, then follow the API responses into `ChatPanel` and `SlidePanel`. See the companion overview docs for broader context on how the UI and API are structured around this pipeline.
