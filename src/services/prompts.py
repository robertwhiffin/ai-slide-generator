"""
Prompts Module for Two-Stage Architecture.

This module centralizes prompt management for the slide generator,
separating planning prompts from generation prompts to optimize token usage.

Key Design:
- Planning Prompt (~800 tokens): Minimal, focused on query generation
- Generation Prompt (~3,500 tokens): Full instructions for slide creation
- Editing Instructions (~300 tokens): Only included when modifying existing slides
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# GENERATION PROMPT (Stage 2) - Full instructions for slide creation
# =============================================================================
# This is the complete prompt that includes all formatting, Chart.js examples,
# and styling guidelines. It's ONLY sent once in Stage 2.

GENERATION_PROMPT = """You are an expert data analyst and presentation creator.
You respond only with valid HTML. Never include markdown code fences or additional commentary - just the raw HTML.

Your goal is to create compelling, data-driven slide presentations by:
1. Analyzing the provided data to identify key insights and patterns
2. Constructing a clear, logical narrative for the presentation
3. Generating professional HTML slides with the narrative and data visualizations

Guidelines for data analysis:
- Identify trends, patterns, and outliers in the data
- Look for correlations and causal relationships
- Compare across time periods, categories, or segments
- Highlight both positive and negative findings objectively
- Quantify insights with specific numbers and percentages

Guidelines for presentation creation:
- Generate a maximum of {max_slides} slides
- Create a title slide with the presentation topic
- Include an agenda/overview slide if appropriate
- Use one key insight per slide for clarity
- Include data visualizations (tables, charts) where appropriate
- Add a conclusion/summary slide with key takeaways
- Ensure slides are professional, clear, and well-structured

Guidelines for each slide:
- Each slide should be a single key insight or finding
- The title should be a single sentence that captures the key insight (not just a description)
  Good example: "Increased usage over the last 12 months"
  Bad example: "Usage data for the last 12 months"
- Use a subtitle to provide more context or detail
- Avoid very text heavy slides
- Use at most two data visualizations per slide

HTML FORMATTING ESSENTIALS:

Layout & Structure:
- Fixed slide size: 1280x720px per slide, white background
- Body: width:1280px; margin:0 auto; padding:0
- Use flexbox for layout with appropriate gaps (≥12px)
- Cards/boxes: padding ≥16px, border-radius 8-12px, shadow: 0 4px 6px rgba(0,0,0,0.1)

Typography & Colors:
- Modern sans-serif font (Inter/SF Pro/Helvetica)
- H1: 40-52px bold, Navy #102025 | H2: 28-36px, Navy #2B3940 | Body: 16-18px, #5D6D71
- Primary accent: Lava #EB4A34 | Success: Green #4BA676 | Warning: Yellow #F2AE3D | Info: Blue #3C71AF
- Background: Oat Light #F9FAFB

Content Per Slide:
- ONE clear title (≤55 chars) that states the key insight
- Subtitle for context
- Body text ≤40 words
- Maximum 2 data visualizations per slide

Charts (when showing data):
- Use Chart.js with appropriate chart types: line (trends), bar (categories), area (cumulative)
- Brand colors: ['#EB4A34','#4BA676','#3C71AF','#F2AE3D']
- CRITICAL: Always check canvas exists before initializing charts:
  const canvas = document.getElementById('chartId');
  if (canvas) {{ const ctx = canvas.getContext('2d'); new Chart(ctx, ...); }}
- Set maintainAspectRatio:false, max-height:200px
- Every <canvas id="..."> MUST have a matching Chart.js script
- Append a <script data-slide-scripts>...</script> block after your slide divs
- One canvas per script: NEVER initialize more than one canvas in the same script block
- Unique scope per canvas: do not reuse variable names across canvases

Technical Requirements:
- Complete valid HTML5 with embedded CSS and JavaScript
- Semantic HTML tags, professional modern styling
- Single scrollable page with vertically stacked slides (no navigation buttons)
- Include Chart.js: <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

CRITICAL OUTPUT FORMAT:
- Respond ONLY with raw HTML - no markdown code fences, no explanatory text
- Start directly with: <!DOCTYPE html>
- End with: </html>
- Do NOT include ```html or ``` markers
- Do NOT add any commentary before or after the HTML
- Your entire response must be valid, parseable HTML
"""


# =============================================================================
# EDITING INSTRUCTIONS - Only included when modifying existing slides
# =============================================================================
# These are conditionally added to the generation prompt (~300 extra tokens)

EDITING_INSTRUCTIONS = """
SLIDE EDITING MODE:
You are editing existing slides. The current slides are provided in <slide-context> tags.

Guidelines for editing:
- Maintain consistency with the existing presentation style and structure
- Preserve the overall design theme and color scheme
- Keep the same chart types unless explicitly asked to change
- Maintain consistent formatting across all slides
- Ensure smooth integration with surrounding slides
- Only modify what the user specifically requests
- Return the complete modified slides wrapped in <div class="slide">...</div>

When editing:
1. Analyze the existing slide structure
2. Identify what needs to change based on the user's request
3. Make minimal changes while achieving the requested modification
4. Preserve all unaffected elements
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def build_generation_prompt(
    max_slides: int = 10,
    is_editing: bool = False,
    existing_slides: str | None = None,
) -> str:
    """
    Build the complete generation prompt for Stage 2.
    
    Args:
        max_slides: Maximum number of slides to generate
        is_editing: Whether this is an editing request
        existing_slides: HTML of existing slides (for editing mode)
    
    Returns:
        Complete system prompt string
    
    Token estimates:
        - Base prompt: ~3,200 tokens
        - With editing: ~3,500 tokens
    """
    # Start with base generation prompt
    prompt = GENERATION_PROMPT.format(max_slides=max_slides)
    
    # Add editing instructions if applicable
    if is_editing:
        prompt = prompt + "\n" + EDITING_INSTRUCTIONS
        logger.debug("Added editing instructions to prompt")
    
    return prompt


def build_user_message(
    user_request: str,
    summarized_data: dict[str, Any],
    existing_slides: str | None = None,
) -> str:
    """
    Build the user message for Stage 2 generation.
    
    Args:
        user_request: The original user request
        summarized_data: Summarized data from Genie queries
        existing_slides: HTML of existing slides (for editing mode)
    
    Returns:
        Complete user message string
    """
    parts = []
    
    # Add existing slides context if editing
    if existing_slides:
        parts.append("<slide-context>")
        parts.append(existing_slides)
        parts.append("</slide-context>")
        parts.append("")
    
    # Add user request
    parts.append(f"User Request: {user_request}")
    parts.append("")
    
    # Add summarized data
    parts.append("Data Available:")
    parts.append("=" * 40)
    
    for query, data in summarized_data.items():
        parts.append(f"\nQuery: {query}")
        
        # Add summary if present
        if isinstance(data, dict):
            if data.get("summary"):
                parts.append(f"Summary: {data['summary']}")
            
            # Add aggregates if present (compact format)
            aggregates = data.get("aggregates", {})
            if aggregates and "_overall" in aggregates:
                overall = aggregates["_overall"]
                agg_parts = []
                for col, stats in overall.items():
                    if isinstance(stats, dict) and "sum" in stats:
                        agg_parts.append(f"{col}: total={stats['sum']:.0f}")
                if agg_parts:
                    parts.append(f"Totals: {', '.join(agg_parts[:3])}")
            
            # Add data records
            records = data.get("data", [])
            if records:
                import json
                parts.append(f"Data ({len(records)} rows):")
                parts.append(json.dumps(records, indent=None))
        else:
            # Raw data (shouldn't happen with summarizer, but handle it)
            import json
            parts.append(json.dumps(data, indent=None))
    
    parts.append("")
    parts.append("=" * 40)
    parts.append("")
    parts.append("Generate the complete HTML slides now.")
    
    return "\n".join(parts)


def estimate_prompt_tokens(
    max_slides: int = 10,
    is_editing: bool = False,
) -> int:
    """
    Estimate token count for the generation prompt.
    
    This is useful for logging and monitoring.
    
    Args:
        max_slides: Maximum slides setting
        is_editing: Whether editing mode is active
    
    Returns:
        Estimated token count
    """
    # Base estimate: ~4 chars per token
    base_prompt = build_generation_prompt(max_slides, is_editing)
    estimated_tokens = len(base_prompt) // 4
    
    return estimated_tokens


# =============================================================================
# TOKEN COMPARISON (for documentation)
# =============================================================================
"""
Token Comparison:

CURRENT ARCHITECTURE (sent with EVERY LLM call):
- Full system prompt: ~4,000 tokens
- Editing instructions: ~300 tokens (always included!)
- Total per call: ~4,300 tokens
- 6 calls: ~25,800 tokens

TWO-STAGE ARCHITECTURE:
- Stage 1 (Planning): ~800 tokens (see query_planner.py)
- Stage 2 (Generation): ~3,500 tokens (once)
- With editing: ~3,800 tokens (once)
- Total: ~4,300-4,600 tokens

SAVINGS: ~21,000 tokens (82% reduction in prompt overhead)
"""

