# Prompt Decoupling UX Test Cases

**One-Line Summary:** Manual UX test cases verifying that the decoupled generation/editing prompt modes produce correct behaviour end-to-end.

---

## 1. Overview

The prompt decoupling change splits the monolithic system prompt into composable modules so that generation and editing each receive only mode-relevant instructions. These UX test cases verify that the change is invisible to users (no regressions) while the underlying prompt is now smaller and more focused per mode.

### What Changed

| Component | Change |
|-----------|--------|
| `src/core/prompt_modules.py` | New — modular prompt blocks and assembly functions |
| `src/services/agent_factory.py` | Accepts `mode`, delegates to prompt_modules |
| `src/services/agent.py` | `_create_prompt` fast path for pre-assembled prompts |
| `src/api/services/chat_service.py` | Determines mode before agent build; RC13 moved earlier |

### Unit Test Coverage

| File | Tests | Status |
|------|-------|--------|
| `tests/unit/test_prompt_modules.py` | 9 | Covers block inclusion/exclusion per mode |
| `tests/unit/test_agent_factory.py` | 18 | Covers mode routing, custom overrides, DB lookups |
| `tests/unit/test_agent.py` | 9 | Backward compatibility of legacy path |

---

## 2. UX Test Cases — Generation Mode

### TC-G1: Fresh deck generation (happy path)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open the app, start a new session | Empty canvas, no slides |
| 2 | Type: "Create a 5-slide presentation about Q1 sales performance" | Loading indicator appears |
| 3 | Wait for LLM response | 5 slides render in the slide panel |
| 4 | Verify slides | Title slide, content slides with charts/data, conclusion slide |
| 5 | Verify HTML structure | Each slide is a `<div class="slide">` at 1280x720 |

**What this validates:** Generation mode prompt includes GENERATION_GOALS, PRESENTATION_GUIDELINES, and HTML_OUTPUT_FORMAT. LLM returns a full `<!DOCTYPE html>` document.

---

### TC-G2: Generation with Genie data tool

| Step | Action | Expected |
|------|--------|----------|
| 1 | Configure session with a Genie space (via agent config) | Session has Genie tool |
| 2 | Type: "Show me revenue trends for the last 12 months" | Agent calls Genie, then generates slides |
| 3 | Verify intermediate steps | Chat panel shows Genie tool call and data response |
| 4 | Verify slides | Charts use data returned by Genie |

**What this validates:** Generation prompt includes DATA_ANALYSIS_GUIDELINES. Tools work correctly with the new prompt assembly.

---

### TC-G3: Generation with existing deck (RC12 clarification)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck (TC-G1) | Deck with slides exists |
| 2 | Without selecting any slide, type: "Create slides about marketing" | Clarification message appears |
| 3 | Verify clarification | Message asks "add new slides" or "replace the entire deck" |
| 4 | Reply: "Replace with new slides about marketing" | New deck replaces old one |

**What this validates:** RC12 clarification still runs before agent build. Mode correctly resolves to `"generate"`.

---

## 3. UX Test Cases — Editing Mode

### TC-E1: Edit a single slide (happy path)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck (TC-G1) | Deck with 5 slides |
| 2 | Select slide 3 in the slide panel | Slide 3 highlighted |
| 3 | Type: "Change the background to dark blue and make the text white" | Loading indicator |
| 4 | Wait for LLM response | Slide 3 updates with dark blue background, white text |
| 5 | Verify other slides | Slides 1, 2, 4, 5 unchanged |

**What this validates:** Editing mode prompt includes EDITING_RULES. LLM returns `<div class="slide">` fragments (not a full HTML document). Slide replacement applies correctly.

---

### TC-E2: Edit via text reference without selection (RC13)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck (TC-G1) | Deck with 5 slides |
| 2 | Without selecting any slide, type: "Change slide 2 title to 'Revenue Growth'" | No clarification prompt |
| 3 | Wait for LLM response | Slide 2 title changes to "Revenue Growth" |
| 4 | Verify other slides | All other slides unchanged |

**What this validates:** RC13 auto-creates `slide_context` from the text reference **before** the agent is built, so mode correctly resolves to `"edit"`. The editing prompt (not generation) is used.

---

### TC-E3: Add a new slide

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck (TC-G1) | Deck with 5 slides |
| 2 | Select any slide | Slide highlighted |
| 3 | Type: "Add a new slide about customer retention" | Loading indicator |
| 4 | Wait for LLM response | New slide appears in the deck (now 6 slides) |
| 5 | Verify new slide | Contains customer retention content |
| 6 | Verify existing slides | Original 5 slides unchanged |

**What this validates:** Editing mode with add-intent. EDITING_RULES include the ADD operation type instructions.

---

### TC-E4: Expand slides (edit returns more slides than input)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck | Deck with slides |
| 2 | Select 1 slide with dense content | Slide highlighted |
| 3 | Type: "Expand this into 3 more detailed slides" | Loading indicator |
| 4 | Wait for LLM response | Selected slide replaced by 3 new slides |
| 5 | Verify deck | Total slide count increased by 2 |

**What this validates:** EDITING_RULES EXPAND operation type works. Mode is `"edit"`.

---

### TC-E5: Unsupported operation (delete)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck | Deck with slides |
| 2 | Select a slide | Slide highlighted |
| 3 | Type: "Delete this slide" | Conversational response (no HTML) |
| 4 | Verify response | Message guides user to use the trash icon in the UI |
| 5 | Verify deck | All slides unchanged |

**What this validates:** EDITING_RULES unsupported operations section is present in the editing prompt.

---

## 4. UX Test Cases — Backward Compatibility

### TC-B2: Edit intent without clear target (RC10 clarification)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck | Deck with slides |
| 2 | Without selecting any slide, type: "Change the colors" | Clarification message |
| 3 | Verify clarification | Asks which slide to edit |
| 4 | Reply: "Change slide 1 colors to green" | Slide 1 updates |

**What this validates:** RC10 clarification runs before agent build. After clarification, RC13 resolves the text reference and mode correctly becomes `"edit"`.

---

### TC-B3: Multi-turn conversation continuity

| Step | Action | Expected |
|------|--------|----------|
| 1 | Generate a deck about sales | Deck created |
| 2 | Select slide 2, type: "Add a chart showing monthly trends" | Slide 2 updated with chart |
| 3 | Without selecting, type: "Now create 2 slides about customer growth" | RC12 clarification or new slides added |
| 4 | Verify conversation history | Chat panel shows all 3 messages and responses |

**What this validates:** Mode switches correctly between `"edit"` (step 2) and `"generate"` (step 3) across turns in the same session. Chat history is preserved.

---

## 5. Performance Tests

### Test File

```
tests/unit/test_prompt_performance.py
```

Run with `-s` to see printed metrics:

```bash
.venv/bin/python -m pytest tests/unit/test_prompt_performance.py -v -s
```

---

### 5.1 Token Efficiency (TC-P1)

**Method:** Tokenize the old monolithic prompt and each new mode-specific prompt using `tiktoken` (`cl100k_base`). Compare counts.

**Baseline results (measured):**

| Prompt variant | Tokens | vs Legacy |
|----------------|--------|-----------|
| Legacy (monolithic: style + system_prompt + editing_instructions + image_support) | 2,585 | -- |
| New generation-only | 1,623 | **-962 tokens (37.2%)** |
| New editing-only | 2,152 | **-433 tokens (16.8%)** |

**Token breakdown by block:**

| Block | Tokens | Category |
|-------|--------|----------|
| BASE_PROMPT | 146 | Shared |
| DATA_ANALYSIS_GUIDELINES | 55 | Shared |
| SLIDE_GUIDELINES | 158 | Shared |
| CHART_JS_RULES | 339 | Shared |
| IMAGE_SUPPORT | 199 | Shared |
| GENERATION_GOALS | 123 | Generation-only |
| PRESENTATION_GUIDELINES | 73 | Generation-only |
| HTML_OUTPUT_FORMAT | 233 | Generation-only |
| EDITING_RULES | 881 | Editing-only |
| EDITING_OUTPUT_FORMAT | 79 | Editing-only |
| **Shared total** | **897** | |
| **Generation-only total** | **429** | |
| **Editing-only total** | **960** | |

**Key takeaway:** Every generation request now avoids sending 960 editing-only tokens. Every editing request avoids 429 generation-only tokens. The editing savings are smaller because the EDITING_RULES block (881 tokens) is large -- this is the block that was always sent on generation requests before.

**Automated assertions:**
- Generation prompt is strictly smaller than legacy
- Editing prompt is strictly smaller than legacy
- Generation saves at least 400 tokens
- Editing saves at least 300 tokens

---

### 5.2 Assembly Latency (TC-P2)

**Method:** Call `build_generation_system_prompt` and `build_editing_system_prompt` 1,000 times each and measure wall-clock time.

**Baseline results (measured):**

| Assembly function | Avg latency |
|-------------------|-------------|
| `build_generation_system_prompt` | 1.7 us |
| `build_editing_system_prompt` | 2.1 us |

**Key takeaway:** Prompt assembly overhead is negligible (&lt;3 us). The overall LLM request takes 5-30 seconds, so the assembly cost is ~0.00001% of total latency.

**Automated assertion:** Average assembly latency < 1,000 us (1ms).

---

### 5.3 LLM Latency Benefit (TC-P3) -- Manual

Token savings translate to reduced LLM processing time because the model reads fewer input tokens before generating output. This must be measured against the live endpoint.

**Test procedure:**

| Step | Action | Measurement |
|------|--------|-------------|
| 1 | Use current tellr app in production | Baseline |
| 2 | Send 5 identical generation requests: "Create a 3-slide presentation about Q1 revenue" | Record `latency_seconds` from response metadata for each |
| 3 | Send 5 identical editing requests: select slide 1, "Change the title to 'Growth Summary'" | Record `latency_seconds` for each |
| 4 | Deploy the **new** code (modular prompts) | -- |
| 5 | Repeat step 2 with the same prompt | Record `latency_seconds` |
| 6 | Repeat step 3 with the same slide and prompt | Record `latency_seconds` |
| 7 | Compare medians | Calculate delta |

**Expected outcome:**
- 962 fewer input tokens on generation should reduce time-to-first-token by ~0.5-1.5s (model-dependent; Claude processes ~1,000 tokens/second on input)
- 433 fewer input tokens on editing should reduce time-to-first-token by ~0.3-0.7s
- Total end-to-end improvement is smaller because output generation dominates, but input processing is the one part we can reduce without changing behaviour

**Where to find latency data:**
- Response metadata: `result["metadata"]["latency_seconds"]`
- MLflow spans: `generate_slides` span has `latency_seconds` attribute
- Application logs: `"Slide generation completed"` log entry includes `latency_seconds`

---

## 6. Checklist result

Run after deployment to confirm no regressions:

- [x] TC-G1: Fresh generation produces valid multi-slide deck
- [ ] TC-G2: Generation with Genie data tool (skipped)
- [x] TC-G3: Generation with existing deck (RC12 clarification)
- [x] TC-E1: Single-slide edit applies correctly
- [x] TC-E2: Text reference editing (RC13) works without selection
- [x] TC-E3: Add slide works
- [x] TC-E4: Expand slides (edit returns more slides than input)
- [x] TC-E5: Delete request returns conversational guidance
- [x] TC-B2: RC10 clarification still fires
- [x] TC-B3: Multi-turn generation then editing works (RC12)
- [x] TC-P1: `pytest tests/unit/test_prompt_performance.py -v -s` -- all 6 pass. See result in [### Test prompt performance](#test-prompt-performance)
- [ ] TC-P3: Manual Test: Generation latency against prod (within noise margin). See result in [### Manual latency test](#manual-latency-test)

### Test prompt performance

```
tests/unit/test_prompt_performance.py::TestTokenEfficiency::test_generation_prompt_is_smaller_than_legacy 
--- Token Efficiency: Generation Mode ---
  Legacy (monolithic):   2,585 tokens
  New (generation-only): 1,623 tokens
  Savings:               962 tokens (37.2%)
PASSED
tests/unit/test_prompt_performance.py::TestTokenEfficiency::test_editing_prompt_is_smaller_than_legacy 
--- Token Efficiency: Editing Mode ---
  Legacy (monolithic):  2,585 tokens
  New (editing-only):   2,152 tokens
  Savings:              433 tokens (16.8%)
PASSED
tests/unit/test_prompt_performance.py::TestTokenEfficiency::test_combined_coverage_vs_legacy 
--- Combined Coverage ---
  Legacy:          2,585 tokens
  Generation:      1,623 tokens
  Editing:         2,152 tokens
  Max per-request: 2,152 tokens
  Worst-case savings: 433 tokens
PASSED
tests/unit/test_prompt_performance.py::TestTokenEfficiency::test_token_breakdown_by_block 
--- Token Breakdown by Block ---
  BASE_PROMPT                       146 tokens  [shared]
  DATA_ANALYSIS_GUIDELINES           55 tokens  [shared]
  SLIDE_GUIDELINES                  158 tokens  [shared]
  CHART_JS_RULES                    339 tokens  [shared]
  IMAGE_SUPPORT                     199 tokens  [shared]
  GENERATION_GOALS                  123 tokens  [gen-only]
  PRESENTATION_GUIDELINES            73 tokens  [gen-only]
  HTML_OUTPUT_FORMAT                233 tokens  [gen-only]
  EDITING_RULES                     881 tokens  [edit-only]
  EDITING_OUTPUT_FORMAT              79 tokens  [edit-only]
                                  -----
  Shared                            897 tokens
  Generation-only                   429 tokens
  Editing-only                      960 tokens
PASSED
tests/unit/test_prompt_performance.py::TestAssemblyLatency::test_generation_assembly_latency 
--- Assembly Latency: Generation ---
  1000 iterations in 0.001s
  Average: 1.1 µs per call
PASSED
tests/unit/test_prompt_performance.py::TestAssemblyLatency::test_editing_assembly_latency 
--- Assembly Latency: Editing ---
  1000 iterations in 0.001s
  Average: 1.3 µs per call
PASSED
```

### Manual latency test

Both test ran on Claude Opus 4.6 model

Current prod: 
- generating 10 slides from 1 prompt: ~ 2min 44sec
- editing text on 1 slide: 15 sec 
- editing color on 1 slide: 15 sec
- expanding 1 slide into 3 slides: 55 sec
- exporting pptx based on generated slides: ~6min+ then crashes due to error in Python execution of one slide 
- exporting google slides based on generated slides: 
  + Total time: ~14min+ then stopped silently 
  + Only 4 of 10 slides exported


New dev: 
- generating 10 slides from 1 prompt: ~ 2min 56sec
- editing 1 slide: 15 sec
- editing color on 1 slide: 12 sec
- expanding 1 slide into 3 slides: 56 sec 
- exporting pptx based on generated slides: 3min 41sec. Export success with all slides.
- exporting google slides based on generated slides: 
  + Within 33sec first Google Slide file created with a placeholder page. 
  + Total export time: ~12min. All slides exported successfully
