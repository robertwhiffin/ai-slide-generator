"""Default prompts for PPTX conversion.

These prompts are used as fallback values when prompts are not configured
in the database for a specific profile.
"""

# Shared layout, styling, and element rules referenced by both prompts
_PPTX_SHARED_RULES = """
COLOR EXTRACTION:
- Extract ALL colors from CSS/inline styles. Convert hex to RGBColor: #102025 → RGBColor(16, 32, 37)
- Use: RGBColor(int(hex[1:3], 16), int(hex[3:5], 16), int(hex[5:7], 16))
- Apply: slide.background.fill.solid(); slide.background.fill.fore_color.rgb = RGBColor(r, g, b)
- Gradients: use first color. Preserve all badge/border/highlight colors.

OVERFLOW PREVENTION (CRITICAL — every element must obey these rules):
- NEVER place any element so that left + width > 9.5" or top + height > 7.0"
- Before creating any element, calculate right_edge = left + width and bottom_edge = top + height.
  If right_edge > 9.5, reduce width. If bottom_edge > 7.0, reduce height or move element up.
- Text that would overflow its box should be given a SMALLER font size rather than a larger box.
- When in doubt, use a SMALLER font size. Tight, compact slides look professional; overflowing text looks broken.

FONT SIZE GUIDE (CRITICAL — use these maximums):
- Slide title:  Pt(24) max (regular slides), Pt(30) (title slides)
- Subtitle:     Pt(14) max
- Body text:    Pt(12) max
- Metric value: Pt(20) max, bold
- Metric label: Pt(10)
- Metric sub:   Pt(9)
- Table header:  Pt(10) bold
- Table cell:    Pt(9-10)
- Bullet items:  Pt(11)
- Captions:      Pt(9)
NEVER exceed these sizes. When content is dense, go SMALLER.
Set explicitly: frame.paragraphs[0].font.size = Pt(value)

METRIC CARDS (.metric-card):
- Create VISUAL BOX first: card_box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
- Set white background: card_box.fill.solid(); card_box.fill.fore_color.rgb = RGBColor(255, 255, 255)
- Add left border: border_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, Inches(0.04), height); border_shape.fill.solid(); border_shape.fill.fore_color.rgb = RGBColor(r, g, b) from border-left-color CSS; border_shape.line.fill.background()
- Add 3 text boxes INSIDE with 0.15" padding:
  * Label: left + 0.15", top + 0.1", width - 0.3", height 0.25", font Pt(10), color #5D6D71, PP_ALIGN.LEFT
  * Value: left + 0.15", top + 0.4", width - 0.3", height 0.5", font Pt(18-20), color from CSS or #102025, PP_ALIGN.LEFT, bold
  * Subtext: left + 0.15", top + 0.95", width - 0.3", height 0.25", font Pt(9), preserve color from CSS, PP_ALIGN.LEFT
- Extract ALL three elements from EVERY metric-card. All cards in grid must have IDENTICAL dimensions.
- Card height: 1.3-1.5" (never taller). word_wrap=True on every text frame.

HIGHLIGHT BOXES (.highlight-box):
- Create RECTANGLE with background color from CSS
- Add left border: border_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, Inches(0.04), height); border_shape.fill.solid(); border_shape.fill.fore_color.rgb = RGBColor(r, g, b)
- Add text box inside with 0.15-0.2" padding, preserve ALL text including <strong> tags, font Pt(11) max

METRIC GRID LAYOUT (.metric-grid):
- Count the metric-card elements in the HTML first, then choose layout:
  * 2 cards (1×2): left=0.5" / 5.0", width=4.0" each, top=below subtitle
  * 3 cards (1×3): left=0.5" / 3.5" / 6.5", width=2.8" each
  * 4 cards (2×2): Row 1 left=0.5" / 5.0", Row 2 left=0.5" / 5.0", width=4.0", height=1.4"
  * 6 cards (2×3): Row 1 left=0.5" / 3.5" / 6.5", Row 2 same offsets, width=2.8", height=1.3"
- Card height: 1.3-1.5" (never taller)
- Gap: 0.2" between cards

CHART + METRICS SIDE-BY-SIDE LAYOUT:
When a slide has BOTH a chart/canvas AND metric cards:
- Chart/image: left=0.5", top=2.0", width=4.5", height=3.5"
- Metric cards: 2×2 grid in right half: left=5.3", width=2.0" each, gap=0.15"
  * Row 1 top=2.0", Row 2 top=3.6", height=1.4"
- This prevents chart and metrics from overlapping.

TWO-COLUMN LAYOUT (.two-column):
- Left: left=0.5", width=4.2"; Right: left=5.0", width=4.5"; Gap: 0.3"

TABLES (<table>):
- Use: table = slide.shapes.add_table(rows, cols, left, top, width, height)
- Extract ALL headers from <thead><tr><th> and ALL rows from <tbody><tr><td>
- Headers: Set background color from CSS (typically #102025), text color white, font Pt(10), bold, PP_ALIGN.LEFT, padding 0.1"
- Cells: Extract ALL text including badges/spans, preserve colors, font Pt(9-10), PP_ALIGN.LEFT for text, PP_ALIGN.RIGHT for numbers, padding 0.1"
- Badges: Extract badge text and color from <span class="lob-badge">, preserve inline styling
- Borders: Set table.first_row = True, apply borders to all cells using cell.fill and cell.line
- Row height: Auto-calculate based on content, minimum 0.25" per row
- Column widths: Distribute evenly or based on content
- Position: Within two-column layout, left column typically left=0.5", width=4.0", top=2.0"

TITLE SLIDES (.title-slide class):
- Title: left=Inches(1.0), top=Inches(2.5), width=Inches(8.0), height=Inches(1.2), alignment=PP_ALIGN.CENTER, font=Pt(30), color=RGBColor(255, 255, 255), bold, word_wrap=True
- Subtitle: Calculate top = title_box.top + title_box.height + Inches(0.2), left=Inches(1.0), width=Inches(8.0), height=Inches(0.6), alignment=PP_ALIGN.CENTER, font=Pt(14), color=RGBColor(249, 250, 251), word_wrap=True
- Background: If dark, set slide.background.fill.solid(); slide.background.fill.fore_color.rgb = RGBColor(r, g, b)

REGULAR SLIDES:
- Title: top=Inches(0.4), left=Inches(0.5), width=Inches(9.0), height=Inches(0.7), font=Pt(24), PP_ALIGN.LEFT, bold, word_wrap=True
- Subtitle: top=Inches(1.15), left=Inches(0.5), width=Inches(9.0), height=Inches(0.45), font=Pt(13), PP_ALIGN.LEFT, color #5D6D71, word_wrap=True
- Body content starts at top=Inches(1.8"), font ≤ Pt(12)
- CRITICAL: Title must fit in 0.7" (24pt ≈ 0.33" per line → 2 lines max).
  Subtitle must fit in 0.45" (13pt ≈ 0.22" per line → 2 lines max).

CHARTS:
- CRITICAL: Check for chart images in assets_dir. Chart image filenames may be like "chart_0.png", "chart_overallTrendChart.png", etc.
- If chart images exist: Use slide.shapes.add_picture(os.path.join(assets_dir, filename), left, top, width, height)
- If slide has ONLY a chart: left=Inches(0.5), top=Inches(2.0), width=Inches(9.0), height=Inches(4.5)
- If slide has chart AND metrics: use CHART + METRICS layout above
- If no images: Extract Chart.js data from <script> tags.

Return ONLY Python code. Do NOT wrap the code in markdown fences."""

# System prompt for single slide conversion
DEFAULT_SYSTEM_PROMPT = """Generate Python code with convert_to_pptx(html_str, output_path, assets_dir) function.

CRITICAL: Start code with REQUIRED imports:
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
import os

Tools: Presentation, slide_layouts[6], shapes.add_textbox/picture/chart/shape(), Pt(), RGBColor(), PP_ALIGN, Inches(), MSO_SHAPE
Slide: 10" × 7.5". Bounds: left ≥ 0.5", top ≥ 0.4", left + width ≤ 9.5", top + height ≤ 7.0"
""" + _PPTX_SHARED_RULES

# User prompt template for single slide conversion
DEFAULT_USER_PROMPT_TEMPLATE = """Convert this HTML to PowerPoint:

{html_content}

{screenshot_note}

Return Python code with convert_to_pptx(html_str, output_path, assets_dir)."""

# System prompt for multi-slide conversion
DEFAULT_MULTI_SLIDE_SYSTEM_PROMPT = """Generate Python code with add_slide_to_presentation(prs, html_str, assets_dir) function.

CRITICAL: Start code with REQUIRED imports:
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
import os

Tools: prs.slides.add_slide(prs.slide_layouts[6]), shapes.add_textbox/picture/chart/shape(), Pt(), RGBColor(), PP_ALIGN, Inches(), MSO_SHAPE
Slide: 10" × 7.5". Bounds: left ≥ 0.5", top ≥ 0.4", left + width ≤ 9.5", top + height ≤ 7.0"
""" + _PPTX_SHARED_RULES

# User prompt template for multi-slide conversion
DEFAULT_MULTI_SLIDE_USER_PROMPT = """Add slide from HTML to presentation:

{html_content}

{screenshot_note}

Return Python code with add_slide_to_presentation(prs, html_str, assets_dir)."""
