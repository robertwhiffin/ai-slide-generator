"""
Prompts for Two-Stage Slide Generator.

This module provides separated prompts for planning and generation stages,
optimizing token usage by using minimal prompts for planning and full
prompts only for final slide generation.

Reference: docs/TWO_STAGE_CSV_IMPLEMENTATION_PLAN.md
"""

from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage


# =============================================================================
# STAGE 1: PLANNING PROMPT (~800 tokens)
# =============================================================================

PLANNING_PROMPT = """You are a data analyst planning queries for a business presentation.

Given the user's request, identify what data queries are needed from the Genie space to create comprehensive slides.

## Available Data in Genie Space

{genie_description}

## Guidelines

- Generate 3-6 comprehensive queries (be thorough but efficient)
- Each query should be specific and answerable by Genie
- Consider different data dimensions:
  - Totals and aggregates
  - Trends over time
  - Breakdowns by category
  - Comparisons between groups
- Use natural language that Genie can understand
- Do NOT include technical SQL - use plain English questions

## Output Format

Respond with ONLY a valid JSON object (no markdown, no explanation):
{{
  "queries": ["query 1", "query 2", "query 3"],
  "rationale": "Brief explanation of your data strategy"
}}"""


# =============================================================================
# STAGE 2: GENERATION - Helper to build full prompt
# =============================================================================

def build_generation_prompt(
    user_request: str,
    data_context: str,
    system_prompt: str,
    existing_slides: Optional[str] = None,
) -> list:
    """
    Build the full generation prompt for Stage 2.
    
    Args:
        user_request: Original user request
        data_context: All CSV data from Genie queries (formatted)
        system_prompt: Full system prompt from settings (slide formatting, Chart.js, etc.)
        existing_slides: Optional existing slides HTML if editing
    
    Returns:
        List of messages for LLM invocation
    """
    # Build the combined system message
    prompt_parts = [system_prompt]
    
    # Add data section
    prompt_parts.append("""
---

## Data Available

The following data has been retrieved from Genie. Use this data to create accurate, data-driven slides.
All numbers and statistics in your slides MUST come from this data.

""")
    prompt_parts.append(data_context)
    
    # Add editing context if modifying existing slides
    if existing_slides:
        prompt_parts.append("""
---

## Editing Mode

You are modifying existing slides. Rules:
- Preserve structure of unmodified slides
- Only change what the user explicitly requests
- Maintain consistent styling across all slides
- Keep existing data unless user asks to update it

### Existing Slides:

""")
        prompt_parts.append(existing_slides)
    
    full_system_prompt = "\n".join(prompt_parts)
    
    return [
        SystemMessage(content=full_system_prompt),
        HumanMessage(content=f"User request: {user_request}\n\nGenerate the HTML slides based on the data above."),
    ]


def format_csv_data_for_llm(csv_results: dict[str, dict]) -> str:
    """
    Format all CSV query results for LLM consumption.
    
    No summarization - passes all data through unchanged.
    
    Args:
        csv_results: Dict mapping query strings to results
            Each result has: {"csv": str, "row_count": int, "message": str}
    
    Returns:
        Formatted string with all query results
    """
    parts = []
    
    for i, (query, result) in enumerate(csv_results.items(), 1):
        parts.append(f"### Query {i}: {query}")
        parts.append(f"**Rows returned:** {result.get('row_count', 0)}")
        
        # Include any message from Genie
        if result.get("message"):
            parts.append(f"**Genie note:** {result['message']}")
        
        # Include CSV data (NO truncation, NO summarization)
        if result.get("csv"):
            parts.append("**Data:**")
            parts.append(f"```csv\n{result['csv']}\n```")
        elif result.get("error"):
            parts.append(f"**Error:** {result['error']}")
        else:
            parts.append("*No data returned*")
        
        parts.append("")  # Blank line between queries
    
    return "\n".join(parts)

