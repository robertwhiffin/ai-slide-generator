## HTML Manipulation Architecture

This document explains how agent-generated HTML flows through the system, how CSS and script blocks are managed during edits, and how the frontend renders slides. It walks through key files plus code excerpts so new contributors can jump in quickly.

Use this alongside:
- `frontend-overview.md` for UI layout/state ownership and API usage.
- `backend-overview.md` for FastAPI/LangChain architecture, session model, and endpoint contracts.

The pipeline narrative below focuses on the shared HTML/CSS/script path that connects those two layers.

---

### 1. High-Level Data Flow
1. **Agent Output** (LLM via `config/prompts.yaml`)
   - Returns full HTML or replacement slide blocks plus scripts and CSS.
   - Prompt enforces "one canvas per script" (`// Canvas: <id>` comment, unique variable names).
2. **Backend Parsing & Storage**
   - `SlideDeck.from_html_string` (`src/domain/slide_deck.py`) splits HTML into slides, CSS, and `ScriptBlock`s.
   - `_parse_slide_replacements` (`src/services/agent.py`) extracts slides, scripts, and CSS from edit responses.
   - `ChatService` (`src/api/services/chat_service.py`) merges CSS and scripts, then caches the updated deck.
3. **API Layer**
   - REST endpoints in `src/api/routes/slides.py` expose deck operations (get, reorder, update, duplicate, delete).
4. **Frontend Consumption**
   - `frontend/src/services/api.ts` talks to `/api/chat` and `/api/slides`.
   - `ChatPanel` feeds new decks into React state; `SlidePanel` renders "Parsed", "Raw HTML", and "Raw Text" views.

---

### 2. Backend Parsing & Script Management
#### 2.1 SlideDeck Parsing
```python
# src/schemas/slide_deck.py
soup = BeautifulSoup(html_content, 'html.parser')
script_blocks: OrderedDict[str, ScriptBlock] = OrderedDict()
inline_scripts = soup.find_all('script', src=False)
for idx, script_tag in enumerate(inline_scripts):
    script_content = script_tag.string or script_tag.get_text()
    cleaned = script_content.strip()
    canvas_ids = extract_canvas_ids_from_script(cleaned)
    key = cls._generate_script_key(canvas_ids, idx)
    block = ScriptBlock(key=key, text=cleaned, canvas_ids=set(canvas_ids))
    script_blocks[key] = block
```

- Each inline `<script>` becomes a `ScriptBlock`.
- `canvas_to_script` maps every canvas ID to the block key for quick removal/replacement.
- Slides are stored as `Slide` objects (`src/models/slide.py`) containing raw `<div class="slide">...</div>` HTML.

#### 2.2 Canvas Extraction Heuristics
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

#### 2.3 Adding & Removing Script Blocks
```python
# src/domain/slide_deck.py
def remove_canvas_scripts(self, canvas_ids: List[str]) -> None:
    for canvas_id in canvas_ids:
        key = self.canvas_to_script.pop(canvas_id, None)
        ...
        if not block.canvas_ids:
            keys_to_remove.add(key)
    for key in keys_to_remove:
        self.script_blocks.pop(key, None)
    self.recompute_scripts()
```

- Removing a canvas updates both `canvas_to_script` and the aggregated `self.scripts`.
- `add_script_block` uses `_generate_script_key` to create deterministic keys (`canvas:<id>:<index>` or `script:n` fallback) and rebuilds `self.scripts`.

#### 2.4 CSS Parsing & Merging

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

### 3. ChatService Replacement Flow
`ChatService` coordinates agent interactions, stores the canonical HTML, and handles targeted edits.

```python
# src/api/services/chat_service.py
# CSS merge (new)
replacement_css = replacement_info.get("replacement_css", "")
if replacement_css:
    current_deck.update_css(replacement_css)

# Canvas ID resolution with fallback chain
incoming_canvas_ids = [extract_canvas_ids_from_html(slide) for slide in replacement_slides]
replacement_script_canvas_ids = (
    script_canvas_ids                                    # from script parsing
    or extract_canvas_ids_from_script(replacement_scripts)  # regex extraction
    or incoming_canvas_ids                               # from slide HTML
)
```

1. **User selects slides; ChatPanel sends message** (see frontend below).
2. **Agent returns `replacement_info`** with new slide HTML, optional `replacement_scripts`, and optional `replacement_css`.
3. `_apply_slide_replacements` removes outgoing slides and their canvases based on HTML:
   - collects canvas IDs from removed slides via `extract_canvas_ids_from_html`.
   - splices new `Slide` objects into `self.current_deck`.
4. **CSS merge**: if the LLM returned CSS, `update_css()` merges it into the deck, overriding matching selectors.
5. **Per-canvas script overwrite** with fallback chain:
   - Determine canvas IDs from: (1) parsed script tags, (2) regex extraction, (3) canvas elements in slide HTML.
   - Always remove existing script blocks for those IDs (even if associated slides persist).
   - Append the new block via `add_script_block`.
6. **Raw HTML**: after replacements, `self.raw_html = self.current_deck.knit()`. Only chat operations mutate `raw_html`, preserving a single agent-controlled source.

Relevant methods:
- `_apply_slide_replacements` – orchestrates slide/CSS/script merging
- `_append_replacement_scripts` – adds validated script blocks
- `update_css` – merges CSS rules
- `remove_canvas_scripts`, `add_script_block` – script block management

---

### 4. API Surface
- `POST /api/chat` (see `src/api/routes/chat.py` via `ChatService.send_message`) returns:
  - `slide_deck`: serialized `SlideDeck`.
  - `raw_html`: canonical HTML string.
  - `replacement_info`: metadata for UI messaging.
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
- `ChatPanel` receives only `rawHtml`; once the backend responds, it calls `onSlidesGenerated(deck, raw)` to update global state. The frontend no longer performs optimistic script merging.

#### 5.2 ChatPanel → Backend
```typescript
// frontend/src/components/ChatPanel/ChatPanel.tsx
const slideContext = hasSelection ? { indices, slide_htmls } : undefined;
const response = await api.sendMessage({ message, maxSlides, slideContext });
if (response.slide_deck) {
  onSlidesGenerated(response.slide_deck, nextRawHtml);
  clearSelection();
}
if (response.replacement_info && slideContext) {
  setLastReplacement(response.replacement_info);
}
```

#### 5.3 SlidePanel Views
- **Parsed Slides**: `SlideTile` renders each slide inside an `<iframe>` built from the deck.
```tsx
// frontend/src/components/SlidePanel/SlideTile.tsx
const slideHTML = `
<!DOCTYPE html>
<html>
<head>
  ...
  ${slideDeck.external_scripts.map(...) }
  <style>${slideDeck.css}</style>
</head>
<body>
  ${slide.html}
  <script>
    try { ${slideDeck.scripts} } catch (error) { ... }
  </script>
</body>
</html>`;
```
- **Raw HTML (Rendered/Text)**: use `rawHtml` from backend to show the canonical response for debugging mismatches.

#### 5.4 Slide Selection & Context
- `SelectionContext` tracks selected slide indices/HTML.
- `SlideSelection` and `SlideTile` share this context so the user can highlight slides before requesting edits.
- `applyReplacements` helper was removed; backend becomes the single source of truth for script state.

---

### 6. Integrity Guarantees

#### 6.1 Script Integrity
1. **Prompt constraints** ensure the LLM emits one script per canvas with clear markers and unique variables.
2. **Extraction heuristics** pick up canvas IDs from multiple patterns and from the comment marker.
3. **Fallback chain** ensures canvas IDs are resolved even if script parsing fails: parsed script → regex extraction → slide HTML canvas elements.
4. **Backend logic** removes any existing script block tied to canvases mentioned in the new script, even if the slide wasn't removed.
5. **Frontend** only ever renders the backend deck, so charts run with the exact scripts produced by the server.

If the prompt is ever violated (e.g., multi-canvas blocks reappear), the backend still deduplicates because every referenced canvas triggers `remove_canvas_scripts`.

#### 6.2 CSS Integrity
1. **Selector-level merging** ensures edits only affect the CSS rules they modify; unrelated styles are preserved.
2. **Graceful fallback** preserves original CSS if parsing fails (e.g., malformed LLM output).
3. **Consistent formatting** reconstructs CSS with uniform spacing after merge.

#### 6.3 Slide Validation
- Slides are identified by BeautifulSoup's `find_all("div", class_="slide")`, which correctly matches multi-class elements like `class="slide title-slide"`.
- Empty slide content is rejected with a descriptive error.
- Canvas/script alignment is validated before deck updates to prevent orphaned charts.

---

### 7. Key Files to Review
| Concern | File |
| --- | --- |
| Prompt / LLM Output Rules | `config/prompts.yaml` |
| Slide & script parsing | `src/domain/slide_deck.py`, `src/domain/slide.py` |
| Canvas heuristics | `src/utils/html_utils.py` |
| CSS parsing & merging | `src/utils/css_utils.py` |
| Agent response extraction | `src/services/agent.py` (`_parse_slide_replacements`, `_extract_css_from_response`) |
| Chat orchestration & replacements | `src/api/services/chat_service.py` |
| REST endpoints | `src/api/routes/slides.py`, `src/api/routes/chat.py` |
| React state & views | `frontend/src/components/Layout/AppLayout.tsx`, `frontend/src/components/ChatPanel`, `frontend/src/components/SlidePanel` |
| API client | `frontend/src/services/api.ts` |
| Tests | `tests/unit/test_html_utils.py`, `tests/unit/test_slide_deck.py`, `tests/unit/test_css_utils.py` |

---

### 8. Future Enhancements
- Consider storing per-canvas script hashes so we can detect no-op edits (would slot into the backend flow documented in `backend-overview.md`).
- Capture shared helper scripts separately if the LLM needs to reuse functions across canvases.
- Add automated validation that rejects multi-canvas blocks at the API boundary; coordinate any new validation responses with the frontend contract in `frontend-overview.md`.
- CSS diff visualization: show users which selectors were modified during edits.
- Scoped CSS: consider prefixing selectors per-slide to prevent style leakage between slides.

With these pieces, contributors can trace exactly how HTML is parsed, transformed, and rendered across the stack. For deeper dives, start with `SlideDeck` and `ChatService`, then follow the API responses into `ChatPanel` and `SlidePanel`. See the companion overview docs for broader context on how the UI and API are structured around this pipeline.

