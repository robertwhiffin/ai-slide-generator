"""Default prompts for Google Slides conversion."""

# Shared layout, styling, and element rules referenced by both prompts
_GSLIDES_SHARED_RULES = """
PRIMARY DIRECTIVE — HTML/CSS is your source of truth:
- Extract ALL colors, font sizes, font weights, text colors, border colors from CSS/inline styles.
- Faithfully reproduce the visual design. Fall back to defaults below only when CSS is silent.

OVERFLOW PREVENTION (CRITICAL — every element must obey):
- NEVER place any element so that left + width > 9.6" or top + height > 5.4"
- Before creating any element, calculate right_edge and bottom_edge. Reduce if out of bounds.
- Text that would overflow: use SMALLER font, not a larger box.
- No overlapping — each element's top must be >= previous element's (top + height).

FONT SIZE GUIDE (CRITICAL — maximums for 16:9):
- Slide title:  22pt max (regular), 26pt (title slides), bold
- Subtitle:     11pt max
- Body text:    10pt max
- Metric value: 16pt max, bold
- Metric label: 8pt
- Metric sub:   7pt
- Table header: 8pt bold
- Table cell:   7-8pt
- Bullet items: 9pt
- Captions:     7pt
NEVER exceed these. When content is dense, go SMALLER.

METRIC CARDS (.metric-card):
- Create ROUND_RECTANGLE bg: card_id = 'card_' + str(uuid.uuid4())[:8]
  createShape with shapeType='ROUND_RECTANGLE', then updateShapeProperties for white fill.
- Add left accent border: thin RECTANGLE (width=0.04", full card height), color from border-left CSS.
- Add 3 text boxes INSIDE with 0.12" padding:
  * Label:   left+0.12", top+0.06", width-0.24", height=0.18", font 8pt, color #5D6D71
  * Value:   left+0.12", top+0.28", width-0.24", height=0.35", font 16pt bold, color from CSS
  * Subtext: left+0.12", top+0.68", width-0.24", height=0.18", font 7pt, preserve CSS color
- Card height: 0.95-1.1" (never taller). ALL cards in grid must have IDENTICAL dimensions.

HIGHLIGHT BOXES (.highlight-box):
- ROUND_RECTANGLE with background color from CSS, left accent border (0.04")
- Text box inside with 0.12" padding, font 9pt max, preserve bold spans

METRIC GRID LAYOUT (.metric-grid):
- Count the metric-card elements in HTML first, then choose layout:
  * 2 cards (1×2): left=0.5" / 5.1", width=4.1" each
  * 3 cards (1×3): left=0.4" / 3.4" / 6.5", width=2.8" each
  * 4 cards (2×2): Row 1 left=0.5" / 5.1", Row 2 same, width=4.1", height=1.0"
  * 6 cards (2×3): Row 1 left=0.4" / 3.4" / 6.5", Row 2 same, width=2.8", height=0.95"
- Card height: 0.95-1.1" (never taller)
- Vertical gap: 0.15" between rows
- Horizontal gap: 0.2" between columns

CHART + METRICS SIDE-BY-SIDE LAYOUT:
When a slide has BOTH a chart/canvas AND metric cards:
- Chart/image: left=0.4", top=1.1", width=4.5", height=3.0"
- Metric cards: stacked in right half: left=5.2", width=4.2" each, gap=0.15"
  * Card 1 top=1.1", Card 2 top=2.2", Card 3 top=3.3", height=1.0"
- This prevents chart and metrics from overlapping.

TWO-COLUMN LAYOUT (.two-column):
- Left: left=0.4", width=4.3"; Right: left=5.0", width=4.5"; Gap: 0.3"

TABLES (<table>):
- createTable in FIRST batchUpdate (rows, cols, size, position)
- Then insertText per cell + updateTextStyle + updateTableCellProperties in SECOND batchUpdate
- updateTableCellProperties requires: 'tableRange': {'location': {'rowIndex': r, 'columnIndex': c}, 'rowSpan': 1, 'columnSpan': 1}
- Headers: background from CSS (typically dark), text white, font 8pt bold
- Cells: font 7-8pt, preserve colors, left-align text, right-align numbers
- Position: within usable area, width ≤ 9.0"

TITLE SLIDES (.title-slide class):
- Title: left=1.0", top=1.6", width=8.0", height=0.9", CENTER aligned, font 26pt bold, white
- Subtitle: top=2.6", left=1.0", width=8.0", height=0.4", CENTER, font 11pt
- Background: dark solid fill from CSS

REGULAR SLIDES:
- Title: top=0.2", left=0.4", width=9.2", height=0.5", font 22pt bold, START aligned
- Subtitle: top=0.75", left=0.4", width=9.2", height=0.28", font 10pt, color #5D6D71
- Body content starts at top=1.1" — all cards/tables/charts/text go below this line
- CRITICAL: Title must fit in 0.5" (22pt ≈ 0.3" per line → 1 line, 2 max).
  Subtitle must fit in 0.28" (10pt ≈ 0.14" per line → 2 lines max).

CHARTS (CRITICAL):
- If chart images are listed in the user message, you MUST use them as pre-captured screenshots.
- Do NOT recreate charts with matplotlib, plotly, or any library. The images are already rendered.
- Upload to Drive via MediaFileUpload, set anyone/reader permission, then createImage.
- Chart only (no metric cards): left=0.4", top=1.1", width=9.0", height=4.0" — fills the body zone.
- Chart + metrics: use CHART + METRICS SIDE-BY-SIDE layout above.
- If NO chart images are listed, skip chart rendering entirely — do not attempt to recreate.

HYPERLINKS (<a href="...">):
- Extract ALL <a> tags from HTML and preserve their href URLs.
- Insert the link text via insertText, then apply the link via updateTextStyle with FIXED_RANGE:
  {'updateTextStyle': {'objectId': id,
    'textRange': {'type': 'FIXED_RANGE', 'startIndex': start, 'endIndex': end},
    'style': {'link': {'url': 'https://...'}}, 'fields': 'link'}}
- CRITICAL: when using startIndex/endIndex, you MUST set 'type': 'FIXED_RANGE'. Without it the API returns a 400 error.
- Track character offsets: after each insertText, the next text starts at the previous end index.
- Also style link text with underline and a blue/brand color to make links visible.

API PATTERNS (CRITICAL — wrong nesting causes 400 errors):
- updateShapeProperties MUST nest inside 'shapeProperties':
  {'updateShapeProperties': {'objectId': id, 'shapeProperties': {
      'shapeBackgroundFill': {'solidFill': {'color': {'rgbColor': hex_to_rgb(...)}}},
      'outline': {'propertyState': 'NOT_RENDERED'}
  }, 'fields': 'shapeBackgroundFill.solidFill.color,outline.propertyState'}}
- textRange for full element styling: use {'type': 'ALL'} — no startIndex/endIndex.
- textRange for partial styling (bold spans, hyperlinks): use {'type': 'FIXED_RANGE', 'startIndex': N, 'endIndex': M}.
- Foreground color: {'opaqueColor': {'rgbColor': hex_to_rgb('#XXXXXX')}}
- Page background: updatePageProperties, objectId=page_id,
  fields: 'pageBackgroundFill.solidFill.color'

EXECUTION:
- ALL code MUST be inside the function body. Nothing at module level except imports and helpers.
- Build requests list, then ONE batchUpdate (except tables need two).
- Do NOT wrap batchUpdate in try/except.
- Every createShape needs a unique objectId: 'txt_' + str(uuid.uuid4())[:8]

Return ONLY Python code, no markdown fences."""

# ── Multi-slide prompts ──────────────────────────────────────────────

DEFAULT_GSLIDES_SYSTEM_PROMPT = """Generate Python code with add_slide_to_presentation(slides_service, drive_service, presentation_id, page_id, html_str, assets_dir) function.

CONTEXT:
- All arguments are pre-created. Do NOT import googleapiclient or build services.
- The slide page already exists (page_id). Do NOT call createSlide — only add content.

HELPERS (include in your code):
def emu(inches): return int(inches * 914400)
def hex_to_rgb(h):
    h = h.lstrip('#')
    return {'red': int(h[0:2],16)/255, 'green': int(h[2:4],16)/255, 'blue': int(h[4:6],16)/255}

SLIDE: 16:9 widescreen — 10" × 5.625" (9144000 × 5143500 EMU).
Bounds: left ≥ 0.4", top ≥ 0.2", left + width ≤ 9.6", top + height ≤ 5.4"

ELEMENT CREATION:
- TEXT_BOX: createShape + insertText + updateTextStyle (textRange: {'type':'ALL'}) + updateParagraphStyle
- RECTANGLE/ROUND_RECTANGLE: createShape + updateShapeProperties
- Size: {'width': {'magnitude': emu(w), 'unit': 'EMU'}, 'height': {'magnitude': emu(h), 'unit': 'EMU'}}
- Position: {'scaleX':1,'scaleY':1,'translateX':emu(left),'translateY':emu(top),'unit':'EMU'}

The code MUST define the function add_slide_to_presentation.
""" + _GSLIDES_SHARED_RULES

DEFAULT_GSLIDES_USER_PROMPT = """Convert the HTML below to a Google Slide.

{html_content}

{screenshot_note}

Return Python code with add_slide_to_presentation(slides_service, drive_service, presentation_id, page_id, html_str, assets_dir)."""

# ── Single-slide prompts ─────────────────────────────────────────────

DEFAULT_GSLIDES_SINGLE_SYSTEM_PROMPT = """Generate Python code with convert_to_google_slides(slides_service, drive_service, html_str, assets_dir, title) function.

This function should:
1. Create a new presentation: pres = slides_service.presentations().create(body={'title': title}).execute()
2. Get the default slide page_id from pres['slides'][0]['objectId']
3. Add content to that slide using batchUpdate requests
4. Return the presentation ID

HELPERS (include in your code):
def emu(inches): return int(inches * 914400)
def hex_to_rgb(h):
    h = h.lstrip('#')
    return {'red': int(h[0:2],16)/255, 'green': int(h[2:4],16)/255, 'blue': int(h[4:6],16)/255}

SLIDE: 16:9 widescreen — 10" × 5.625" (9144000 × 5143500 EMU).
Bounds: left ≥ 0.4", top ≥ 0.2", left + width ≤ 9.6", top + height ≤ 5.4"

ELEMENT CREATION:
- TEXT_BOX: createShape + insertText + updateTextStyle (textRange: {'type':'ALL'}) + updateParagraphStyle
- RECTANGLE/ROUND_RECTANGLE: createShape + updateShapeProperties
- Size: {'width': {'magnitude': emu(w), 'unit': 'EMU'}, 'height': {'magnitude': emu(h), 'unit': 'EMU'}}
- Position: {'scaleX':1,'scaleY':1,'translateX':emu(left),'translateY':emu(top),'unit':'EMU'}

The code MUST define the function convert_to_google_slides.
""" + _GSLIDES_SHARED_RULES

DEFAULT_GSLIDES_SINGLE_USER_PROMPT = """Convert the HTML below to a Google Slide.

{html_content}

{screenshot_note}

Return Python code with convert_to_google_slides(slides_service, drive_service, html_str, assets_dir, title)."""
