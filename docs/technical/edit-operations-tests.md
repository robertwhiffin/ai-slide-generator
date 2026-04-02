# Edit Operations Test Suite

**One-Line Summary:** Comprehensive test coverage for slide editing flows including LLM response validation, intent detection, canvas ID handling, and JavaScript validation.

---

## 1. Overview

The edit operations test suite validates the robustness of slide editing workflows. These tests ensure that user editing requests are correctly interpreted, LLM responses are validated before applying, and deck integrity is preserved even when errors occur.

### Test Files

| File | Test Count | Purpose |
|------|------------|---------|
| `tests/unit/test_slide_editing_robustness.py` | 48 | Core robustness fixes (RC1-RC15), integration, and edge cases |
| `tests/unit/test_llm_edit_responses.py` | 17 | LLM response handling for various edit types |
| `tests/unit/test_slide_replacements.py` | 11 | Slide replacement parsing, context validation, and sample HTML fixtures |

---

## 2. Test Categories

### 2.1 Deck Preservation (RC3)

**Goal:** Never destroy the deck when editing fails.

```
tests/unit/test_slide_editing_robustness.py::TestDeckPreservation
```

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_rc3_deck_structure_preserved` | Invalid LLM response | Original deck preserved |
| `test_rc3_valid_replacement_updates_deck` | Valid HTML edit | Deck updated correctly |
| `test_rc3_new_generation_creates_deck` | New generation (no selection) | New deck created |

**Key Invariant:** If `slide_context` is provided but parsing fails, the existing deck MUST be preserved.

---

### 2.2 LLM Response Validation (RC1)

**Goal:** Detect invalid LLM responses and retry before failing.

```
tests/unit/test_slide_editing_robustness.py::TestLLMResponseValidation
```

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_rc1_t1_detects_delete_text` | LLM returns "I understand you want to delete..." | Invalid, retry triggered |
| `test_rc1_t2_detects_cannot_modify` | LLM returns "I cannot modify" | Invalid, retry triggered |
| `test_rc1_t3_accepts_valid_html` | Valid HTML with slide divs | Passes validation |
| `test_rc1_t6_html_without_slide_divs` | HTML without `<div class="slide">` | Invalid, retry triggered |
| `test_rc1_empty_response_invalid` | Empty string response | Invalid |
| `test_rc1_whitespace_response_invalid` | Whitespace-only response | Invalid |
| `test_rc1_valid_with_multiple_slides` | Multiple valid slides | Passes validation |
| `test_rc1_conversational_with_slides_is_valid` | Text + valid slides | Passes (slides present) |

**Validation Method:** `agent._validate_editing_response(response)`

```python
# Confusion patterns that indicate invalid response
confusion_patterns = [
    "I understand",
    "I cannot",
    "I'm sorry",
    "There are no slides",
]
```

---

### 2.3 Add vs Edit Intent Detection (RC2)

**Goal:** Correctly distinguish between adding new slides and editing existing ones.

```
tests/unit/test_slide_editing_robustness.py::TestAddIntentDetection
```

| Test | Message | Expected Intent |
|------|---------|-----------------|
| `test_rc2_t1_add_at_bottom_detected` | "add a slide at the bottom for summary" | Add |
| `test_rc2_t2_insert_new_slide_detected` | "insert a new slide after this one" | Add |
| `test_rc2_t3_change_color_is_edit` | "change the color to red" | Edit (not add) |
| `test_rc2_t4_make_blue_is_edit` | "make this slide blue" | Edit (not add) |
| `test_rc2_t5_create_new_summary` | "create a new summary slide" | Add |
| `test_rc2_t6_append_slide` | "append a conclusions slide" | Add |
| `test_rc2_t7_add_at_end` | "add a chart at the end" | Add |
| `test_rc2_add_summary` | "add a summary slide" | Add |
| `test_rc2_add_key_takeaway` | "add a key takeaway slide at the end" | Add |
| `test_rc2_update_existing_is_not_add` | "update the chart colors" | Edit (not add) |

**Detection Method:** `agent._detect_add_intent(message)`

```python
add_patterns = [
    r'\badd\b.*\bslide\b',
    r'\binsert\b.*\bslide\b',
    r'\bappend\b.*\bslide\b',
    r'\bnew\s+slide\b',
    r'\bcreate\b.*\bslide\b',
]
```

---

### 2.4 Canvas ID Deduplication (RC4)

**Goal:** Prevent canvas ID collisions when editing slides with charts.

```
tests/unit/test_slide_editing_robustness.py::TestCanvasIdDeduplication
```

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_rc4_t1_single_canvas_deduplicated` | Single canvas `id="chart1"` | Becomes `chart1_abc123` |
| `test_rc4_t2_multiple_canvases_same_suffix` | Multiple canvases in one slide | All get same suffix |
| `test_rc4_t3_scripts_references_updated` | Scripts reference canvas IDs | Scripts updated to new IDs |
| `test_rc4_t4_no_canvas_unchanged` | Slide without canvas | No changes made |
| `test_rc4_t5_consecutive_edits_unique_suffixes` | Two edits in a row | Different suffixes |
| `test_rc4_querySelector_updated` | Scripts use `querySelector` | References updated |

**Deduplication Method:** `agent._deduplicate_canvas_ids(html, scripts)`

---

### 2.5 JavaScript Syntax Validation (RC5)

**Goal:** Validate JavaScript syntax before applying to prevent browser errors.

```
tests/unit/test_slide_editing_robustness.py::TestJavaScriptValidation
```

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_rc5_t1_valid_js_passes` | Valid JavaScript | Passes validation |
| `test_rc5_t2_missing_brace_fixed` | Missing closing `}` | Auto-fixed |
| `test_rc5_t3_missing_paren_fixed` | Missing closing `)` | Auto-fixed |
| `test_rc5_t5_empty_script_valid` | Empty script | Passes |
| `test_rc5_whitespace_only_valid` | Whitespace-only | Passes |
| `test_rc5_validate_and_fix_returns_fixed` | Fixable syntax error | Returns fixed script |
| `test_rc5_validate_and_fix_empty_script` | Empty script via `validate_and_fix_javascript` | Returns empty, no error |
| `test_rc5_missing_bracket_fixed` | Missing closing `]` | Auto-fixed |

**Validation Utilities:** `src/utils/js_validator.py`

```python
from src.utils.js_validator import validate_javascript, try_fix_common_js_errors
```

---

### 2.6 Slide Editing Integration

**Goal:** Verify the complete slide editing flow end-to-end in unit tests.

```
tests/unit/test_slide_editing_robustness.py::TestSlideEditingIntegration
```

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_deck_from_html_string` | Create deck from HTML string | Deck with 2 slides, title parsed |
| `test_deck_slide_manipulation` | Add, remove, reorder slides | Correct slide count and content |
| `test_slide_with_scripts` | Slide with associated JavaScript | Scripts stored on slide object |
| `test_deck_knit_includes_scripts` | `knit()` output includes scripts | `<script>` tags present in output |
| `test_format_slide_context_add_operation` | `_format_slide_context` with add flag | Add instructions included in context |

---

### 2.7 Edge Cases

**Goal:** Ensure robustness with unusual or boundary inputs.

```
tests/unit/test_slide_editing_robustness.py::TestEdgeCases
```

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_slide_with_special_characters` | HTML entities (`>`, `&`, `<`) | Content preserved correctly |
| `test_slide_with_unicode` | Unicode and emoji characters | Characters preserved |
| `test_empty_slide_deck` | Deck with zero slides | `knit()` still produces valid HTML |
| `test_slide_clone` | Clone a slide with scripts | Clone preserves HTML, scripts, and ID |
| `test_deeply_nested_html` | Deeply nested div structure | Content accessible in slide |

---

### 2.8 Cache Restoration (RC6)

**Goal:** Restore deck from database when in-memory cache is empty.

```
tests/unit/test_slide_editing_robustness.py::TestCacheRestoration
```

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_rc6_get_or_load_deck_from_cache` | Deck in cache | Returns from cache |
| `test_rc6_get_or_load_deck_from_database` | Cache empty, deck in DB | Restores from DB |
| `test_rc6_get_or_load_deck_empty_database` | Cache empty, no deck in DB | Returns None |

**Critical for:** Surviving backend restarts with `--reload` flag.

---

### 2.9 LLM Edit Response Types

**Goal:** Validate that various edit operations produce correct output.

```
tests/unit/test_llm_edit_responses.py
```

| Test Class | Tests | Operation | Key Validations |
|------------|-------|-----------|-----------------|
| `TestRecolorChartResponse` | 2 | Change chart colors | Canvas ID preserved, valid JS |
| `TestRewordContentResponse` | 2 | Modify text content | Valid HTML, no spurious scripts |
| `TestAddSlideResponse` | 2 | Add new slide | Deck integrity, chart scripts |
| `TestConsolidateResponse` | 2 | Merge slides | Slide count reduced, valid HTML |
| `TestExpandResponse` | 2 | Split into multiple | Slide count increased, unique canvas IDs |
| `TestMalformedResponses` | 2 | Invalid LLM output | Duplicate IDs detected, JS errors caught |
| `TestCSSInEditResponses` | 2 | CSS modifications | CSS extracted, valid syntax |
| `TestEdgeCase` | 3 | Empty/no slides/orphan scripts | Handled gracefully, `AgentError` raised |

---

### 2.10 Slide Replacement Operations

**Goal:** Validate the core slide replacement mechanism.

```
tests/unit/test_slide_replacements.py
```

#### TestSlideReplacementParsing (5 tests)

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_parse_replacements_varied_counts` | Parametrized: 1:1, expansion, condensation (3 cases) | Correct counts, valid `Slide` objects |
| `test_parse_replacements_no_slides_error` | No slide divs in response | `AgentError` raised |
| `test_parse_extracts_scripts_and_canvas_ids` | Response with canvas and scripts | Canvas IDs extracted, scripts attached |
| `test_validate_canvas_scripts_full_html_success` | Full HTML with matching script | Passes validation |
| `test_validate_canvas_scripts_full_html_failure` | Canvas without matching script | `AgentError` raised |

#### TestSlideContextValidation (2 tests)

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_contiguous_validation_passes` | Contiguous indices with matching HTMLs | `SlideContext` created |
| `test_non_contiguous_or_mismatched_lengths_fail` | Non-contiguous indices or length mismatch | `ValueError` raised |

#### TestSampleHTMLReplacements (4 tests)

| Test | Scenario | Expected Outcome |
|------|----------|------------------|
| `test_parse_single_slide_replacement_scenarios` | `update1.html` and `update2.html` fixtures | Single-slide replacements with correct scripts |
| `test_parse_consolidation_replacement` | `update3.html` (3-to-1 consolidation) | `net_change` of -2, no scripts |
| `test_replacement_css_extraction` | CSS in replacement HTML | CSS extracted with expected selectors |
| `test_original_indices_preserved` | Original indices passed through | Indices and `start_index` preserved |

---

## 3. Running the Tests

```bash
# Run all edit operations tests
pytest tests/unit/test_slide_editing_robustness.py tests/unit/test_llm_edit_responses.py tests/unit/test_slide_replacements.py -v

# Run specific test class
pytest tests/unit/test_slide_editing_robustness.py::TestLLMResponseValidation -v

# Run with coverage
pytest tests/unit/test_slide_editing_robustness.py --cov=src/services/agent --cov-report=html
```

---

## 4. Key Invariants

These invariants must NEVER be violated:

1. **Deck preservation:** If editing fails for any reason, the original deck must remain intact
2. **Canvas ID uniqueness:** No two canvases in the same presentation may share an ID
3. **Script-canvas binding:** Scripts must always reference their correct canvas IDs
4. **Add vs Edit:** Add operations must never replace existing slides; edit operations must never add new slides unintentionally

---

## 5. CI/CD Integration

Edit operation tests run as part of the `unit-tests` job in the GitHub Actions workflow:

```yaml
# .github/workflows/test.yml
unit-tests:
  name: Unit Tests
  runs-on: ubuntu-latest
  needs: changes
  if: needs.changes.outputs.backend == 'true'
  steps:
    - run: |
        pytest tests/unit -v --tb=short -n auto \
          --junitxml=test-results/unit-results.xml \
          --cov=src --cov-report=xml --cov-report=term-missing
```

All three edit operations test files live under `tests/unit/` and are collected automatically by this job whenever backend files change.

---

## 6. Cross-References

- [Slide Editing Robustness Fixes](./slide-editing-robustness-fixes.md) - Implementation details for RC1-RC15
- [Slide Parser and Script Management](./slide-parser-and-script-management.md) - HTML parsing details
- [Backend Overview](./backend-overview.md) - Agent architecture
