# GSlides Prompts + PPTX Parallelization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Google Slides export quality by enriching the LLM prompts with missing patterns from the PPTX prompts, and apply the same two-phase parallelization strategy (already working for Google Slides) to the PPTX export path for a 3–5x speedup.

**Architecture:** Part 1 is prompt-only changes to `google_slides_prompts_defaults.py`. Part 2 refactors `html_to_pptx.py` from sequential per-slide processing into a two-phase pipeline (parallel LLM codegen + sequential execution), mirroring the pattern already proven in `html_to_google_slides.py`.

**Tech Stack:** Python/FastAPI backend, asyncio, Anthropic Claude via Databricks model serving, python-pptx, Google Slides API

**Spec:** `docs/superpowers/specs/2026-03-31-gslides-pptx-export-design.md`

---

## Task ordering rationale

Part 1 (prompts) and Part 2 (parallelization) are independent and can be developed in any order. Within Part 2, the refactor tasks must be sequential: extract helpers → add parallel infrastructure → rewrite the main loop → update the queue. Tests run after each part.

---

## Part 1: Google Slides Prompt Enrichment

### Task 1: Enrich `_GSLIDES_SHARED_RULES`

**Files:**
- Modify: `src/services/google_slides_prompts_defaults.py`
- Modify: `tests/unit/test_google_slides_converter.py`

- [ ] **Step 1: Add COLOR EXTRACTION section**

Add an explicit color extraction block to `_GSLIDES_SHARED_RULES`:
- Gradient handling: "use first color"
- "Preserve all badge/border/highlight colors"
- Canonical `hex_to_rgb('#XXXXXX')` conversion pattern

- [ ] **Step 2: Improve TABLE guidance**

Enhance the existing table section (lines 62–68) with:
- Badge/span handling (`lob-badge` class)
- Row height minimum / column width distribution
- Border and row-striping guidance (`updateTableCellProperties` for alternating row fills)
- "NEVER insertText with empty string into table cells — skip the cell"

- [ ] **Step 3: Add TEXT AUTOFIT guidance**

Add text-in-shapes section:
- "Use autofit: NONE for shapes with precise layout (metric cards, badges)"
- "Ensure text does not overflow by reducing font size rather than growing the box"

- [ ] **Step 4: Add ALLOWED IMPORTS block**

Replace the current "Do NOT import" negative guidance with a positive allowlist:

```
ALLOWED imports:
import os, json, uuid, re
from googleapiclient.http import MediaFileUpload  # ONLY for image uploads
```

- [ ] **Step 5: Add API ERROR PREVENTION patterns**

Add to `_GSLIDES_SHARED_RULES`:
- "Never reference an objectId before the request that creates it"
- "Batch request order must match dependency order"
- "Never insertText with empty string"
- "When computing EMU values, always use `emu()` helper"

- [ ] **Step 6: Add BULLET / LIST paragraph guidance**

Add 3–4 lines on converting HTML `<ul>/<ol>` to Slides `updateParagraphStyle` with bullet presets and indent.

- [ ] **Step 7: Add mini worked examples (optional)**

Add compact inline examples for:
- Table cell fill: 2-line pseudocode for `insertText` + `updateTextStyle` with `tableRange`
- Hyperlink with two text segments: show `startIndex`/`endIndex` tracking

- [ ] **Step 8: Run existing Google Slides tests**

Run: `python -m pytest tests/unit/test_google_slides_converter.py -v --tb=short`

Expected: ALL PASS — prompt changes don't break converter logic.

- [ ] **Step 9: Commit**

```bash
git add src/services/google_slides_prompts_defaults.py
git commit -m "feat: enrich Google Slides LLM prompts with color/table/import/API patterns

Add COLOR EXTRACTION, improved TABLE guidance, TEXT AUTOFIT, explicit
ALLOWED IMPORTS, API ERROR PREVENTION, BULLET/LIST paragraph handling,
and mini worked examples to _GSLIDES_SHARED_RULES."
```

---

## Part 2: PPTX Export Parallelization

### Task 2: Refactor `_call_llm` into sync + async

**Files:**
- Modify: `src/services/html_to_pptx.py`

- [ ] **Step 1: Add imports**

Add `asyncio`, `time`, `Tuple` imports and `MAX_CONCURRENT_LLM = 5` constant at the top of `html_to_pptx.py`.

- [ ] **Step 2: Split `_call_llm` into `_call_llm_sync` + async wrapper**

Current `_call_llm` is declared `async` but performs a blocking HTTP call. Split:

```python
def _call_llm_sync(self, system_prompt, user_prompt):
    """Synchronous LLM call with timeout=300."""
    # Existing logic from _call_llm, add timeout=300
    ...

async def _call_llm(self, system_prompt, user_prompt):
    """Async wrapper for backward compat."""
    return await asyncio.to_thread(self._call_llm_sync, system_prompt, user_prompt)
```

- [ ] **Step 3: Verify existing single-slide path still works**

Run: `python -m pytest tests/unit/ -k "pptx" -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add src/services/html_to_pptx.py
git commit -m "refactor: split _call_llm into sync + async for parallel dispatch

_call_llm_sync does the blocking HTTP call with timeout=300.
_call_llm is a thin async wrapper via asyncio.to_thread."
```

---

### Task 3: Extract helper methods

**Files:**
- Modify: `src/services/html_to_pptx.py`

- [ ] **Step 1: Extract `_prepare_slide` helper**

Extract asset-preparation logic from `_add_slide_to_presentation` (lines 265–316) into:

```python
def _prepare_slide(self, html_str, client_chart_images, slide_num):
    """Prepare slide assets. Returns (html, chart_files, content_files, assets_dir)."""
    ...
```

- [ ] **Step 2: Extract `_generate_code_sync` helper**

Create synchronous code generation method for `asyncio.to_thread`:

```python
def _generate_code_sync(self, html_str, chart_images, content_images=None):
    """Build prompt, call _call_llm_sync, return generated code string."""
    ...
```

- [ ] **Step 3: Extract `_execute_slide` helper**

Extract execution + fallback logic from `_add_slide_to_presentation` (lines 332–341 + 916–991):

```python
def _execute_slide(self, code, prs, html_str, assets_dir, slide_number):
    """Execute generated code against Presentation. Falls back to blank slide on error."""
    if not code:
        # add fallback slide
        return
    self._execute_slide_adder(code, prs, html_str, assets_dir)
```

- [ ] **Step 4: Verify refactored helpers produce same output**

Run: `python -m pytest tests/unit/ -k "pptx" -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/html_to_pptx.py
git commit -m "refactor: extract _prepare_slide, _generate_code_sync, _execute_slide

Break _add_slide_to_presentation into composable helpers for the
upcoming two-phase parallel pipeline."
```

---

### Task 4: Add parallel codegen infrastructure

**Files:**
- Modify: `src/services/html_to_pptx.py`

- [ ] **Step 1: Add `_generate_all_codes` method**

Mirror the Google Slides pattern (lines 619–653):

```python
async def _generate_all_codes(self, slide_inputs, on_codegen_progress=None):
    """Generate code for all slides in parallel with semaphore."""
    sem = asyncio.Semaphore(MAX_CONCURRENT_LLM)

    async def gen_one(idx, inp):
        async with sem:
            code = await asyncio.to_thread(
                self._generate_code_sync, inp["html"], inp["chart_images"], inp.get("content_images")
            )
            if on_codegen_progress:
                on_codegen_progress(idx)
            return code

    tasks = [gen_one(i, inp) for i, inp in enumerate(slide_inputs)]
    return await asyncio.gather(*tasks)
```

- [ ] **Step 2: Commit**

```bash
git add src/services/html_to_pptx.py
git commit -m "feat: add _generate_all_codes for parallel PPTX codegen

Semaphore-bounded (MAX_CONCURRENT_LLM=5) parallel dispatch of
_generate_code_sync via asyncio.to_thread."
```

---

### Task 5: Rewrite `convert_slide_deck` as two-phase

**Files:**
- Modify: `src/services/html_to_pptx.py`

- [ ] **Step 1: Rewrite the main loop**

Replace the sequential `for` loop in `convert_slide_deck` (lines 197–236) with:

**Phase 1:** Prepare all slides, then `await _generate_all_codes(...)` with progress callback.

**Phase 2:** Sequential `_execute_slide` for each slide, then `prs.save()`.

- [ ] **Step 2: Verify PPTX output is correct**

Run: `python -m pytest tests/unit/ -k "pptx" -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 3: Commit**

```bash
git add src/services/html_to_pptx.py
git commit -m "feat: rewrite convert_slide_deck as two-phase parallel pipeline

Phase 1: prepare all slides + parallel LLM codegen (semaphore=5).
Phase 2: sequential execution against Presentation object + save.
3-5x speedup for multi-slide decks."
```

---

### Task 6: Update export job queue for two-phase progress

**Files:**
- Modify: `src/api/services/export_job_queue.py`

- [ ] **Step 1: Rewrite `convert_slides_with_progress` as two-phase**

Apply the same two-phase pattern to the live export path:

- Phase 1: Prepare all slides, parallel codegen with `status_message` updates ("Generating code: X/Y slides ready...")
- Phase 2: Sequential execution with `status_message` updates ("Building slide X/Y...")

This mirrors the Google Slides path's progress reporting.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/unit/ -v --tb=short -x 2>&1 | tail -30`

Expected: ALL PASS.

- [ ] **Step 3: Commit**

```bash
git add src/api/services/export_job_queue.py
git commit -m "feat: two-phase progress reporting for PPTX export queue

Phase 1 reports 'Generating code: X/Y slides ready...'
Phase 2 reports 'Building slide X/Y...'
Matches Google Slides export progress pattern."
```

---

## Part 3: Verification

### Task 7: Final verification and lint check

- [ ] **Step 1: Run full backend test suite**

Run: `python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -40`

Expected: ALL PASS.

- [ ] **Step 2: Run linter**

Run: `ruff check src/services/html_to_pptx.py src/services/google_slides_prompts_defaults.py src/api/services/export_job_queue.py`

Expected: No errors.

- [ ] **Step 3: Verify no regressions in Google Slides export**

Run: `python -m pytest tests/unit/test_google_slides_converter.py -v --tb=short`

Expected: ALL PASS — prompt enrichment is additive, converter logic unchanged.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: lint fixes and test verification for export improvements"
```
