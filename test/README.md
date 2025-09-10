# Integration Tests

This directory contains integration tests that mirror the functionality of the Gradio app.

## Test Overview

- **Test 1** (`test_1_llm_html_generation.py`): Sends prompt to LLM and generates HTML output
- **Test 2** (`test_2_visualize_html.py`): Opens generated HTML in browser for visual verification  
- **Test 3** (`test_3_html_to_pptx.py`): Placeholder for HTML to PPTX conversion (not yet implemented)
- **Test 4** (`test_4_run_all_tests.py`): Runs all tests sequentially

## Test Prompt

All tests use this prompt:
```
"Generate a succinct report EY Parthenon. Do not generate more than 5 slides. Use the information available in your tools. Use visualisations. Include an overview slide of EY Parthenon. Think about your response."
```

## Running Tests

### Run Individual Tests
```bash
# Test 1: Generate HTML from LLM
python test/test_1_llm_html_generation.py

# Test 2: Visualize HTML output
python test/test_2_visualize_html.py

# Test 3: PPTX conversion placeholder
python test/test_3_html_to_pptx.py
```

### Run All Tests
```bash
python test/test_4_run_all_tests.py
```

## Output Directory

All test outputs are saved to `test/output/`:
- `test_1_output.html` - Generated HTML slides
- `test_3_conversion_placeholder.txt` - PPTX conversion placeholder

## Prerequisites

- Databricks credentials configured
- Access to LLM endpoint: `databricks-claude-sonnet-4`
- Required dependencies installed:
  ```bash
  pip install -r requirements.txt
  pip install -e .
  ```

## Expected Behavior

1. **Test 1** should generate HTML with 5 slides about EY Parthenon
2. **Test 2** should open the HTML in your default browser for visual inspection
3. **Test 3** creates a placeholder file (actual PPTX conversion not implemented)
4. **Test 4** runs all tests and provides a summary

## Notes

- Tests replicate the exact initialization and conversation loop from the Gradio app
- Uses the same EY Parthenon theme and UC tools
- No fallback content - tests require real LLM and tool integration