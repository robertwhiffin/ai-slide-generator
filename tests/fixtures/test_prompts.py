"""
Standard test prompts for performance benchmarking.

These prompts are used consistently across tests to ensure
comparable results when measuring token usage.

Reference: docs/TWO_STAGE_CSV_IMPLEMENTATION_PLAN.md
"""

# Standard prompts for comparison testing
TEST_PROMPTS = {
    "3_slides_basic": {
        "prompt": "Create 3 slides about top 10 use cases in KPMG UK. Do not include use case ID.",
        "expected_slides": 3,
        "expected_queries_min": 2,
        "expected_queries_max": 5,
        "description": "Basic 3-slide presentation about use cases",
    },
    "5_slides_trends": {
        "prompt": "Create 5 slides showing monthly spend trends for top use cases in KPMG UK with comparisons.",
        "expected_slides": 5,
        "expected_queries_min": 3,
        "expected_queries_max": 6,
        "description": "5-slide presentation with trend data",
    },
    "3_slides_with_charts": {
        "prompt": "Create 3 slides with charts showing KPMG UK spend breakdown by line of business.",
        "expected_slides": 3,
        "expected_queries_min": 2,
        "expected_queries_max": 4,
        "description": "3-slide presentation with chart visualizations",
    },
    "single_metric": {
        "prompt": "Create 1 slide showing total KPMG UK Databricks spend.",
        "expected_slides": 1,
        "expected_queries_min": 1,
        "expected_queries_max": 4,  # Planner may add context queries
        "description": "Single slide with one metric",
    },
}

# Editing test prompts
EDITING_PROMPTS = {
    "modify_title": {
        "initial_prompt": "Create 2 slides about KPMG UK use cases.",
        "edit_prompt": "Change the title on slide 1 to be shorter.",
        "expected_changes": ["title"],
        "description": "Edit title text",
    },
    "add_chart": {
        "initial_prompt": "Create 2 slides about KPMG UK spend.",
        "edit_prompt": "Add a pie chart to slide 2.",
        "expected_changes": ["chart"],
        "description": "Add chart to existing slide",
    },
}

# Quick test prompt for development
QUICK_TEST_PROMPT = TEST_PROMPTS["single_metric"]

