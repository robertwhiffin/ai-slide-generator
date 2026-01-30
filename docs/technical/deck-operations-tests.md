# Deck Operations Test Suite

**One-Line Summary:** Test coverage for deck integrity, persistence, and state management including CRUD operations, reorder, add position validation, and database survival.

---

## 1. Overview

The deck operations test suite validates that slide deck manipulations maintain data integrity and correctly persist to the database. These tests ensure that operations like reorder, delete, duplicate, and add work correctly and survive backend restarts.

### Test Files

| File | Test Count | Purpose |
|------|------------|---------|
| `tests/unit/test_deck_integrity.py` | 22 | Deck parsing, CRUD operations, CSS, knit output |
| `tests/unit/test_deck_persistence.py` | 18 | CRUD persistence to database |
| `tests/unit/test_chat_persistence.py` | 12 | Chat-based operation persistence |
| `tests/unit/test_add_position_bug.py` | 12 | Add position validation, state mismatch detection |

---

## 2. Test Categories

### 2.1 Deck Parsing and Structure

**Goal:** Validate that decks are correctly parsed from HTML and maintain structure.

```
tests/unit/test_deck_integrity.py::TestDeckParsing
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_parse_deck_various_sizes[3]` | 3-slide deck | Correct slide count |
| `test_parse_deck_various_sizes[6]` | 6-slide deck | Correct slide count |
| `test_parse_deck_various_sizes[9]` | 9-slide deck | Correct slide count |
| `test_parse_deck_various_sizes[12]` | 12-slide deck | Correct slide count |
| `test_parse_deck_various_themes` | Different CSS themes | CSS preserved |
| `test_parse_deck_with_charts_extracts_canvas_ids` | Deck with charts | Canvas IDs extracted |

**Parsing Method:** `SlideDeck.from_html_string(html)`

---

### 2.2 Delete Operations

**Goal:** Verify delete operations preserve deck integrity.

```
tests/unit/test_deck_integrity.py::TestDeleteOperation
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_delete_preserves_integrity[6]` | Delete from 6-slide deck | Remaining slides valid |
| `test_delete_preserves_integrity[9]` | Delete from 9-slide deck | Remaining slides valid |
| `test_delete_preserves_integrity[12]` | Delete from 12-slide deck | Remaining slides valid |
| `test_delete_chart_slide_removes_script` | Delete slide with chart | Associated script removed |
| `test_delete_all_slides_except_one` | Delete to single slide | Deck still valid |

**Key Invariant:** Deleting a slide must also remove its associated scripts.

---

### 2.3 Add Operations

**Goal:** Verify add operations correctly insert slides at specified positions.

```
tests/unit/test_deck_integrity.py::TestAddOperation
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_add_content_slide_preserves_integrity` | Add text slide | Deck structure valid |
| `test_add_chart_slide_preserves_integrity` | Add slide with chart | Scripts attached |
| `test_insert_slide_at_position_preserves_integrity` | Insert at specific index | Correct position |

---

### 2.4 Edit Operations

**Goal:** Verify in-place edits preserve deck integrity.

```
tests/unit/test_deck_integrity.py::TestEditOperation
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_edit_slide_html_preserves_integrity` | Modify slide HTML | Other slides unchanged |
| `test_edit_slide_scripts_preserves_integrity` | Modify slide scripts | Script-canvas binding intact |

---

### 2.5 Reorder Operations

**Goal:** Verify reorder operations maintain deck integrity.

```
tests/unit/test_deck_integrity.py::TestReorderOperation
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_move_slide_preserves_integrity` | Move single slide | All slides present |
| `test_swap_slides_preserves_integrity` | Swap two slides | Both slides intact |
| `test_multiple_reorders_preserve_integrity` | Multiple moves | Final state correct |

---

### 2.6 CSS and Knit Operations

**Goal:** Verify CSS handling and HTML knitting work correctly.

```
tests/unit/test_deck_integrity.py::TestCSSMerging
tests/unit/test_deck_integrity.py::TestKnitOutput
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_update_css_preserves_validity` | Update deck CSS | Valid CSS syntax |
| `test_css_merge_preserves_existing_rules` | Merge new CSS | Original rules kept |
| `test_knit_produces_valid_html` | Knit deck to HTML | Valid HTML document |
| `test_knit_aggregates_scripts_correctly` | Knit with scripts | Scripts properly wrapped |
| `test_render_single_slide_valid` | Render one slide | Valid standalone HTML |

---

## 3. Persistence Tests

### 3.1 Basic CRUD Persistence

**Goal:** Verify all CRUD operations save to database.

```
tests/unit/test_deck_persistence.py::TestPersistenceBasics
```

| Test | Operation | Validation |
|------|-----------|------------|
| `test_reorder_persists_to_database` | Reorder slides | New order saved |
| `test_update_slide_persists_to_database` | Update slide HTML | Changes saved |
| `test_delete_slide_persists_to_database` | Delete slide | Deletion saved |
| `test_duplicate_slide_persists_to_database` | Duplicate slide | New slide saved |

---

### 3.2 Persistence After Restart

**Goal:** Verify changes survive backend restart (cache clear).

```
tests/unit/test_deck_persistence.py::TestPersistenceAfterRestart
```

| Test | Operation | Validation |
|------|-----------|------------|
| `test_reorder_survives_restart` | Reorder + restart | Order restored from DB |
| `test_update_survives_restart` | Update + restart | Changes restored |
| `test_delete_survives_restart` | Delete + restart | Deletion persisted |
| `test_duplicate_survives_restart` | Duplicate + restart | New slide persisted |

**Simulates:** Cache clear via `service._deck_cache.clear()`

---

### 3.3 Multiple Operations Persistence

**Goal:** Verify sequences of operations all persist correctly.

```
tests/unit/test_deck_persistence.py::TestMultipleOperationsPersistence
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_multiple_edits_all_persist` | Edit slides 1, 2, 3 | All edits saved |
| `test_mixed_operations_persist` | Edit + delete + reorder | Final state correct |

---

### 3.4 Script and CSS Persistence

**Goal:** Verify scripts and CSS persist with operations.

```
tests/unit/test_deck_persistence.py::TestScriptPersistence
tests/unit/test_deck_persistence.py::TestCSSPersistence
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_scripts_preserved_on_reorder` | Reorder chart slide | Scripts stay attached |
| `test_scripts_preserved_on_duplicate` | Duplicate chart slide | Both have scripts |
| `test_css_preserved_on_operations` | Operations with custom CSS | CSS unchanged |

---

### 3.5 Edge Cases

**Goal:** Verify edge cases are handled correctly.

```
tests/unit/test_deck_persistence.py::TestEdgeCases
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_empty_html_content_still_saves` | Empty slide content | Saves without error |
| `test_special_characters_in_content_save` | HTML entities, quotes | Correctly escaped |
| `test_unicode_content_saves` | Unicode characters | Preserved correctly |
| `test_large_deck_saves` | 50+ slides | No size issues |

---

## 4. Chat-Based Persistence

### 4.1 Sync and Streaming Paths

**Goal:** Verify both sync and streaming chat paths persist correctly.

```
tests/unit/test_chat_persistence.py
```

| Test | Path | Validation |
|------|------|------------|
| `test_sync_generation_saves_deck` | `send_message()` | Deck saved to DB |
| `test_sync_edit_with_context_saves_deck` | Sync edit | Edit persisted |
| `test_streaming_generation_saves_deck` | `send_message_streaming()` | Deck saved to DB |

---

### 4.2 Persistence Conditions

**Goal:** Verify save only happens when conditions are met.

```
tests/unit/test_chat_persistence.py::TestPersistenceConditions
```

| Test | Condition | Validation |
|------|-----------|------------|
| `test_save_requires_current_deck` | `current_deck=None` | Save skipped |
| `test_save_requires_slide_deck_dict` | `slide_deck_dict=None` | Save skipped |
| `test_save_called_when_both_present` | Both present | Save called |

**Save Condition:**
```python
if current_deck and slide_deck_dict:
    session_manager.save_slide_deck(...)
```

---

### 4.3 Deck Dict Completeness

**Goal:** Verify deck dict contains all required data.

```
tests/unit/test_chat_persistence.py::TestDeckDictCompleteness
```

| Test | Field | Validation |
|------|-------|------------|
| `test_deck_dict_contains_all_slides` | `slides` array | All slides present |
| `test_deck_dict_contains_scripts` | `slide.scripts` | Scripts preserved |
| `test_deck_dict_contains_css` | `css` | CSS included |
| `test_deck_dict_contains_title` | `title` | Title included |

---

## 5. Add Position Validation (RC14)

### 5.1 Position Calculation

**Goal:** Verify add operations calculate correct insert position.

```
tests/unit/test_add_position_bug.py::TestAddPositionBug
```

| Test | Scenario | Expected Position |
|------|----------|-------------------|
| `test_detect_add_position_before_this` | "add before this" | `("before", None)` |
| `test_detect_add_intent_add_slide` | "add a slide..." | Intent detected |
| `test_add_operation_position_calculation` | Before selected slide | Insert at selection index |
| `test_add_beginning_position` | "beginning" position | Insert at 0 |
| `test_add_after_position` | "after" position | Insert after selection |

---

### 5.2 Edge Cases: State Mismatch

**Goal:** Detect and handle frontend/backend deck state mismatches.

```
tests/unit/test_add_position_bug.py::TestAddPositionEdgeCases
```

| Test | Scenario | Behavior |
|------|----------|----------|
| `test_add_before_with_empty_deck_fallback` | Backend has 0 slides | Falls back to position 0 |
| `test_add_before_with_mismatched_deck_size` | Backend has 1 slide, frontend selected index 1 | Falls back to position 0 |

**Root Cause:** When `start_idx >= len(current_deck.slides)`, position falls back to 0.

---

### 5.3 RC14 State Validation

**Goal:** Early detection of frontend/backend state mismatch.

```
tests/unit/test_add_position_bug.py::TestRC14StateValidation
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_state_mismatch_detection_logic` | Index 2, deck has 1 slide | Mismatch detected |
| `test_state_mismatch_with_valid_selection` | Index 1, deck has 3 slides | No mismatch |
| `test_state_mismatch_with_multiple_selections` | Indices [0,1,2], deck has 2 | Mismatch detected |

**Validation Code:**
```python
if slide_context:
    max_index = max(selected_indices)
    if max_index >= len(existing_deck.slides):
        # State mismatch - return error asking user to refresh
```

---

## 6. Running the Tests

```bash
# Run all deck operations tests
pytest tests/unit/test_deck_integrity.py tests/unit/test_deck_persistence.py tests/unit/test_chat_persistence.py tests/unit/test_add_position_bug.py -v

# Run specific category
pytest tests/unit/test_deck_persistence.py::TestPersistenceAfterRestart -v

# Run with coverage
pytest tests/unit/test_deck_persistence.py --cov=src/api/services --cov-report=html

# Run just the position bug tests
pytest tests/unit/test_add_position_bug.py -v
```

---

## 7. CI/CD Integration

These tests run in the GitHub Actions workflow:

```yaml
# .github/workflows/test.yml
persistence-tests:
  name: Deck Persistence Validation
  steps:
    - run: pytest tests/unit/test_deck_persistence.py tests/unit/test_chat_persistence.py -v

validation-tests:
  name: Deck Integrity Validation
  steps:
    - run: pytest tests/unit/test_deck_integrity.py tests/unit/test_llm_edit_responses.py -v
```

---

## 8. Key Invariants

These invariants must NEVER be violated:

1. **Persistence completeness:** Every deck modification must save to database before returning success
2. **Restart survival:** All deck state must be recoverable from database after backend restart
3. **Script preservation:** Reorder and duplicate operations must preserve script-canvas bindings
4. **Position validity:** Add operations must validate that selected indices exist in the backend deck
5. **State consistency:** Frontend and backend deck state must match; mismatches must be detected and reported

---

## 9. Debugging State Mismatches

When users report "changes not saving" or "slides at wrong position":

1. Check logs for `RC14: Frontend/backend deck state mismatch detected`
2. Check logs for `DECK STATE MISMATCH: Frontend selected index exceeds backend deck size`
3. Check logs for `Add 'before' fallback to position 0 due to invalid start_index`

These indicate a previous save failed and the user should refresh their browser.

---

## 10. Cross-References

- [Edit Operations Tests](./edit-operations-tests.md) - LLM response validation and intent detection
- [Slide Editing Robustness Fixes](./slide-editing-robustness-fixes.md) - Implementation details
- [Backend Overview](./backend-overview.md) - Chat service architecture
- [Database Configuration](./database-configuration.md) - Persistence layer details
