# Export UX Test Cases

**Scope:** Manual test cases for changes introduced in the parallel export + prompt improvement work.

Covers: PPTX parallelization, Google Slides prompt enrichment, code sanitization, and 429 retry logic.

---

## 1. PPTX Export — Parallel Code Generation

### TC-1.1: Basic PPTX export still works

1. Open the Tellr app and generate a slide deck with **5+ slides**.
2. Click **Export to PPTX** (download).
3. Wait for the progress messages in the UI.
4. **Expected:** PPTX file downloads successfully. All slides are present and match the preview.

### TC-1.2: Progress messages show two phases

1. Generate a deck with **7+ slides**.
2. Click **Export to PPTX** (download).
3. Observe the progress messages in the UI.
4. **Expected:**
   - Phase 1 messages appear: "Generating code: 1/7 slides ready…", "Generating code: 2/7 slides ready…", etc.
   - Phase 2 messages appear: "Building slide 1/7…", "Building slide 2/7…", etc.
   - Export completes without timeout.

### TC-1.3: PPTX export is faster than before

1. Generate a deck with **10 slides**.
2. Click **Export to PPTX** and time the total export duration.
3. **Expected:** Total time should be noticeably faster than 10 × 15-45s sequential. Roughly 30-90s for codegen + a few seconds for execution.

### TC-1.4: Slide with apostrophe in content exports correctly

1. Generate a slide deck where at least one slide contains text with apostrophes (e.g. "Anthony's workflow", "don't", "it's").
2. Export to PPTX.
3. **Expected:** All slides render correctly — no fallback "Slide Content" placeholder slides. The apostrophe text appears in the PPTX as-is.

### TC-1.5: Slide with special characters (em-dash, curly quotes)

1. Generate a slide with content containing em-dashes (—), en-dashes (–), or curly quotes ("text").
2. Export to PPTX.
3. **Expected:** All slides render correctly. No SyntaxError in logs. Special characters appear as regular dashes/quotes in the PPTX.

### TC-1.6: Failed code generation produces fallback slide

1. This tests the fallback path. If an LLM call times out or returns garbage for one slide, the deck should still export.
2. Generate a large deck (10+ slides) and export to PPTX.
3. **Expected:** Even if one slide fails code generation, the PPTX still downloads with the correct total number of slides. The failed slide shows a "Slide N" placeholder instead of being omitted entirely.

---

## 2. Google Slides Export — Prompt Improvements

### TC-2.1: Basic Google Slides export

1. Generate a slide deck with **5+ slides** containing a mix of: title slide, metric cards, a table, and a chart.
2. Click **Export to Google Slides**.
3. Wait for the Google Slides URL to open automatically.
4. **Expected:** Presentation opens in Google Slides. All slides are present.

### TC-2.2: Table formatting matches preview

1. Generate a deck with a slide that has a **table with headers, data rows, and badges** (e.g. LOB badges).
2. Export to Google Slides.
3. **Expected:** Table headers have dark background with white text. Data cells have correct font size. Badge text and colors are preserved. No empty "The object has no text" errors in logs.

### TC-2.3: Bullet lists render correctly

1. Generate a deck with a slide that has an **unordered list** (`<ul><li>...`) or **ordered list** (`<ol><li>...`).
2. Export to Google Slides.
3. **Expected:** List items appear with bullet markers (disc/circle) or numbered markers. Indentation is correct.

### TC-2.4: Hyperlinks are clickable

1. Generate a deck where a slide contains a **hyperlink** (e.g. "See details at [this link](https://...)").
2. Export to Google Slides.
3. Click on the link text in the Google Slides presentation.
4. **Expected:** The link text is underlined and blue. Clicking it opens the correct URL.

### TC-2.5: Colors and gradients

1. Generate a deck with metric cards that have **colored borders** and a title slide with a **dark gradient background**.
2. Export to Google Slides.
3. **Expected:** Border colors match the preview. Gradient backgrounds use the first color stop as a solid fill. No white-on-white or missing colors.

### TC-2.6: Google Slides early URL still works

1. Generate a 7+ slide deck.
2. Click Export to Google Slides.
3. **Expected:** The Google Slides URL opens in a new tab almost immediately (within a few seconds), before all slides are populated. Slides appear incrementally as they are built.

---

## 3. Google Slides Export — 429 Rate Limit Retry

### TC-3.1: Large deck exports without missing slides

1. Generate a deck with **10+ slides** (complex slides with tables, charts, metric cards).
2. Export to Google Slides.
3. **Expected:** All slides are present in the Google Slides deck. Check logs for "hit rate limit" messages — if present, they should be followed by successful retries. No slides are skipped.

### TC-3.2: Progress messages continue through rate-limit pauses

1. Generate a deck with **10+ slides**.
2. Export to Google Slides. Observe progress messages.
3. **Expected:** If a rate limit is hit, the progress messages may pause for a few seconds but then resume. The export completes successfully without timeout.

---

## 4. Google Slides Export — Code Sanitizer Fixes

### TC-4.1: paragraphStyle nesting error is auto-fixed

1. Export any deck to Google Slides.
2. Check application logs for `"Prep: fixing 'paragraphStyle'"` messages.
3. **Expected:** If the message appears, the fix was applied automatically. No 400 errors with "Cannot find field" for `update_paragraph_style` in the logs.

### TC-4.2: Apostrophe content in Google Slides

1. Generate a slide with text containing apostrophes (e.g. "The client's portfolio", "We don't expect").
2. Export to Google Slides.
3. **Expected:** Text renders correctly in Google Slides. No SyntaxError in logs.

---

## 5. Chart Images

### TC-5.1: Google Slides export with chart images

1. Generate a deck with a slide containing a **Chart.js chart** (canvas element).
2. Export to Google Slides.
3. **Expected:** Chart appears as an image in Google Slides (uploaded via Drive). Positioned correctly (not overlapping metric cards).


### TC-5.2: PPTX export with chart images

1. Generate a deck with chart slides.
2. Export to PPTX.
3. **Expected:** Charts appear as images in the PPTX. Positioned correctly.



## Checklist result

- [x] **TC-1.1** — Basic PPTX export still works
- [x] **TC-1.2** — Progress messages show two phases
- [ ] **TC-1.3** — PPTX export is faster than before (skipped) - see TC-P3 test in [prompt-decoupling-tests.md](./prompt-decoupling-tests.md)
- [x] **TC-1.4** — Slide with apostrophe in content exports correctly
- [x] **TC-1.5** — Slide with special characters (em-dash, curly quotes)
- [x] **TC-1.6** — Failed code generation produces fallback slide
- [x] **TC-2.1** — Basic Google Slides export
- [x] **TC-2.2** — Table formatting matches preview
- [x] **TC-2.3** — Bullet lists render correctly
- [ ] **TC-2.4** — Hyperlinks are clickable (skipped)
- [x] **TC-2.5** — Colors and gradients and style
- [x] **TC-2.6** — Google Slides early URL still works
- [x] **TC-3.1** — Large deck exports without missing slides
- [x] **TC-3.2** — Progress messages continue through rate-limit pauses
- [x] **TC-4.1** — paragraphStyle nesting error is auto-fixed
- [x] **TC-4.2** — Apostrophe content in Google Slides
- [x] **TC-5.1** — Google Slides export with chart images
- [x] **TC-5.2** — PPTX export with chart images