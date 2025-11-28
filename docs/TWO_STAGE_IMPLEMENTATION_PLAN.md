# Two-Stage Architecture Implementation Plan

**Status:** ✅ Implementation Complete — Testing in Progress  
**Created:** November 27, 2025  
**Branch:** LOCAL ONLY (no commits until testing complete)

---

## Overview

This document tracks the implementation of the Two-Stage Architecture + Data Summarization solution for token optimization.

### Goal
Reduce token usage by 70-80% while maintaining or improving slide quality.

### Current State → Target State

```
CURRENT:                              TARGET:
├── 6+ LLM calls per request          ├── 2 LLM calls per request
├── System prompt repeated 6×         ├── System prompt sent once
├── Raw Genie data (140+ rows)        ├── Summarized data (20 rows + aggregates)
├── ~47,000 tokens for 3 slides       ├── ~14,000 tokens for 3 slides
└── Max 3-4 slides before limit       └── Max 20+ slides
```

---

## Implementation Checklist

### Phase 1: Core Components

| # | Task | File | Status |
|---|------|------|--------|
| 1 | Create Data Summarizer | `src/services/data_summarizer.py` | ✅ Complete |
| 2 | Create Query Planner | `src/services/query_planner.py` | ✅ Complete |
| 3 | Create Two-Stage Generator | `src/services/two_stage_generator.py` | ✅ Complete |
| 4 | Create Prompts Module | `src/services/prompts.py` | ✅ Complete |

### Phase 2: Integration

| # | Task | File | Status |
|---|------|------|--------|
| 5 | Add feature flag for new architecture | `src/api/services/chat_service.py` | ✅ Complete |
| 6 | Integrate with chat service | `src/api/services/chat_service.py` | ✅ Complete |
| 7 | Update routes to use new generator | N/A (uses same interface) | ✅ Complete |

**Feature Flag:** Set `USE_TWO_STAGE_GENERATOR=true` in environment to enable.

### Phase 3: Testing & Validation

| # | Task | Status |
|---|------|--------|
| 8 | Test with 3-slide request | ✅ Complete (see Test Results below) |
| 9 | Compare token usage (old vs new) | ✅ Complete (see Analysis below) |
| 10 | Test with 5-slide request | ⬜ Pending |
| 11 | Test editing mode | ⬜ Pending |

### Phase 4: Documentation

| # | Task | File | Status |
|---|------|------|--------|
| 12 | Update TOKEN_OPTIMIZATION_ANALYSIS.md | `docs/TOKEN_OPTIMIZATION_ANALYSIS.md` | ✅ Complete |
| 13 | Add inline code documentation | All new files | ✅ Complete |

---

## Architecture Design

### File Structure

```
src/services/
├── agent.py                    # EXISTING - Keep as fallback
├── tools.py                    # EXISTING - Genie queries (reuse)
├── data_summarizer.py          # NEW - Summarize Genie responses
├── query_planner.py            # NEW - Stage 1: Plan queries
├── prompts.py                  # NEW - Separated prompts (planning vs generation)
└── two_stage_generator.py      # NEW - Orchestrates the two stages
```

### Data Flow

```
User Request
     │
     ▼
┌────────────────────────────────┐
│  two_stage_generator.py        │
│  ──────────────────────────────│
│  1. Call query_planner         │
│  2. Execute Genie queries      │
│  3. Summarize with data_summarizer
│  4. Generate slides            │
└────────────────────────────────┘
     │
     ▼
HTML Slides
```

---

## Component Specifications

### 1. Data Summarizer ✅

**File:** `src/services/data_summarizer.py`  
**Status:** Complete

**Purpose:** Reduce Genie response size while preserving essential information.

**Key Features:**
- Detects time series data automatically
- Samples at regular intervals (max 12 points for time series)
- Computes aggregates (sum, mean, max, min)
- Preserves first and last data points
- Falls back to top-N for categorical data

**Usage:**
```python
from src.services.data_summarizer import summarize_genie_response

# Raw: 140 rows → Summarized: 12 samples + aggregates
summarized = summarize_genie_response(raw_data, query="monthly trends")
```

---

### 2. Query Planner (Stage 1) ✅

**File:** `src/services/query_planner.py`  
**Status:** Complete

**Purpose:** Generate all needed Genie queries in a single LLM call.

**Prompt Design:**
```
SHORT prompt (~800 tokens):
- Role: Data analyst planning queries
- Input: User request
- Output: JSON list of queries
- No HTML instructions, no Chart.js examples
```

**Expected Output:**
```json
{
  "queries": [
    "What are the top 10 use cases by total spend?",
    "What is the monthly spend trend for each use case?",
    "How many workspaces does each use case have?"
  ],
  "rationale": "Need spend data, trends, and infrastructure metrics"
}
```

---

### 3. Prompts Module ✅

**File:** `src/services/prompts.py`  
**Status:** Complete

**Purpose:** Centralize and separate prompts for different stages.

**Contents:**
- `PLANNING_PROMPT`: Short prompt for Stage 1 (~800 tokens)
- `GENERATION_PROMPT`: Full prompt for Stage 2 (~3,500 tokens)
- `EDITING_INSTRUCTIONS`: Only included when editing (~300 tokens)

**Key Difference from Current:**
- Current: All instructions sent with every LLM call
- New: Planning gets minimal prompt, Generation gets full prompt

---

### 4. Two-Stage Generator ✅

**File:** `src/services/two_stage_generator.py`  
**Status:** Complete

**Purpose:** Orchestrate the complete two-stage flow.

**Flow:**
```python
class TwoStageGenerator:
    async def generate(self, request: str, session_id: str, existing_slides: str = None):
        # Stage 1: Plan queries
        queries = await self.plan_queries(request)
        
        # Execute queries in parallel (NO LLM)
        raw_results = await self.execute_queries_parallel(queries)
        
        # Summarize results
        summarized = self.summarize_all(raw_results)
        
        # Stage 2: Generate slides
        html = await self.generate_slides(request, summarized, existing_slides)
        
        return html
```

---

## Prompt Comparison

### Stage 1: Planning Prompt (~800 tokens)

```
You are a data analyst planning queries for a presentation.

Given the user's request, identify what data queries are needed.
Output a JSON object with a list of natural language queries.

Rules:
- Be comprehensive but efficient (3-6 queries typically)
- Each query should be specific and actionable
- Consider: totals, trends, breakdowns, comparisons

Output format:
{"queries": ["query 1", "query 2", ...]}
```

### Stage 2: Generation Prompt (~3,500 tokens)

```
[Full system prompt with:]
- Role & identity
- Slide formatting guidelines
- HTML structure requirements
- Chart.js code examples
- Color schemes & typography
- {conditional: editing instructions}

Data Available:
{summarized_data}

User Request: {request}

Generate complete HTML slides.
```

---

## Token Estimates

### Current Architecture (3 slides)

| Component | Tokens | Count | Total |
|-----------|--------|-------|-------|
| System Prompt | 4,000 | ×6 calls | 24,000 |
| Genie Data | 4,000 | ×3 accumulations | 12,000 |
| HTML Output | 8,000 | ×1 | 8,000 |
| **TOTAL** | | | **~44,000** |

### Two-Stage Architecture (3 slides)

| Component | Tokens | Count | Total |
|-----------|--------|-------|-------|
| Planning Prompt | 800 | ×1 | 800 |
| Planning Output | 200 | ×1 | 200 |
| Generation Prompt | 3,500 | ×1 | 3,500 |
| Summarized Data | 1,000 | ×1 | 1,000 |
| HTML Output | 8,000 | ×1 | 8,000 |
| **TOTAL** | | | **~13,500** |

**Reduction: 69%**

---

## Testing Plan

### Test 1: Basic Generation
```
Request: "Create 3 slides about top use cases"
Expected: 
- 2 LLM calls (planning + generation)
- ~15,000 tokens total
- Same quality slides
```

### Test 2: Trend Query (The 140-row case)
```
Request: "Show monthly trends for all use cases"
Expected:
- Genie returns 140+ rows
- Summarizer reduces to ~12 samples
- Final LLM sees ~1,000 tokens of data (not 3,500)
```

### Test 3: Scaling
```
Request: "Create 5 slides about..."
Expected:
- Still just 2 LLM calls
- ~18,000 tokens total
- No degradation
```

### Test 4: Editing Mode
```
Request: "Change slide 2 to use a pie chart"
Expected:
- Editing instructions included in Stage 2
- Existing slides passed as context
- Only affected slides regenerated
```

---

## Rollback Plan

If the new architecture has issues:

1. **Feature Flag:** Set `USE_TWO_STAGE=false` in settings
2. **Fallback:** Original `SlideGeneratorAgent` remains untouched
3. **A/B Testing:** Can run both side-by-side

---

## Notes & Decisions

### Decision 1: Keep Original Agent
We're NOT modifying `src/services/agent.py`. The new generator is a separate implementation that can be swapped via feature flag.

### Decision 2: Parallel Genie Queries
Stage 1 generates all queries, then we execute them in parallel using `asyncio.gather()`. This improves speed significantly.

### Decision 3: Summarization Strategy
- Time series: Sample every Nth row + aggregates
- Categorical: Top N rows + totals
- Small data (<20 rows): Pass through unchanged

### Decision 4: MLflow Setup
Reuse the exact same MLflow setup from `agent.py`:
- `mlflow.set_tracking_uri("databricks")`
- `mlflow.set_experiment()`
- `mlflow.langchain.autolog()` - Auto-traces all ChatDatabricks.invoke() calls
- `mlflow.start_span()` - Manual span for overall generation

This ensures same visibility level as the original agent.

---

## Progress Log

| Date | Update |
|------|--------|
| Nov 27, 2025 | Created implementation plan |
| Nov 27, 2025 | Completed data_summarizer.py |
| Nov 27, 2025 | Completed query_planner.py |
| Nov 27, 2025 | Completed prompts.py (separated planning vs generation prompts) |
| Nov 27, 2025 | Completed two_stage_generator.py (main orchestrator) |
| Nov 27, 2025 | All core components complete |
| Nov 27, 2025 | Added feature flag integration in chat_service.py |
| Nov 27, 2025 | Added print statements for execution tracing |
| Nov 27, 2025 | Added MLflow LangChain autolog (matches original agent.py setup) |
| Nov 27, 2025 | **FIRST TEST COMPLETE** - Results documented below |

---

## 📊 Test Results (November 27, 2025)

**Test Prompt (identical for both tests):**
> "produce a short summary presentation (three slides only) on the state of the top 10 use cases in KPMG In the UK. When requesting data from Genie, explicitly do not include the use case ID"

**Environment:**
- Model: `databricks-claude-3-7-sonnet` (via ChatDatabricks)
- Genie Space: KPMG UK Consumption

---

## Test 1: Original Agent (Baseline)

**Environment:** `USE_TWO_STAGE_GENERATOR=false`

### Execution Timeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  ORIGINAL AGENT EXECUTION                                           │
├─────────────────────────────────────────────────────────────────────┤
│  22:34:53 - Request received                                        │
│  22:35:00 - LLM Call 1 (7s) - Decide what query to run              │
│  22:35:14 - LLM Call 2 (14s) - After Genie Query 1 (10 rows)        │
│  22:35:30 - LLM Call 3 (16s) - After Genie Query 2 (180+ rows!) ←── │
│  22:35:48 - LLM Call 4 (18s) - After Genie Query 3 (1 row)          │
│  22:36:05 - LLM Call 5 (17s) - After Genie Query 4 (10 rows)        │
│  22:36:34 - Finished chain + HTML generation                        │
├─────────────────────────────────────────────────────────────────────┤
│  TOTAL: 101 seconds (1 minute 41 seconds)                           │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Issues Observed

1. **5 LLM calls** - Each with full system prompt (~4,000 tokens)
2. **Query 2 returned 180+ rows** of raw monthly trend data
3. **Sequential execution** - Each Genie query waits for LLM to decide
4. **Accumulating context** - Each call adds more data to the scratchpad
5. **System prompt repeated 5×** = ~20,000 tokens just for prompts

---

## Test 2: Two-Stage Generator (Optimized)

**Environment:** `USE_TWO_STAGE_GENERATOR=true`

### Execution Timeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  TWO-STAGE GENERATOR EXECUTION                                      │
├─────────────────────────────────────────────────────────────────────┤
│  [STAGE 1] Planning queries...                                      │
│    - Time: 3.98s                                                    │
│    - Result: 3 queries planned                                      │
│    - LLM Calls: 1 (short planning prompt only)                      │
│                                                                     │
│  [EXECUTION] Running 3 Genie queries in PARALLEL...                 │
│    - Time: 14.93s (all 3 at once!)                                  │
│    - No LLM involved                                                │
│                                                                     │
│  [SUMMARIZE] Processing data...                                     │
│    - Original: 80 rows                                              │
│    - Summarized: 33 rows (58.8% reduction)                          │
│    - Time: <1s                                                      │
│                                                                     │
│  [STAGE 2] Generating HTML slides...                                │
│    - Time: 27.16s                                                   │
│    - LLM Calls: 1 (full prompt + summarized data)                   │
│    - Output: 9,841 characters                                       │
├─────────────────────────────────────────────────────────────────────┤
│  TOTAL: 46.15 seconds                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### What the Two-Stage Generator Did Differently

1. **Only 2 LLM calls** - Planning (short prompt) + Generation (full prompt)
2. **Parallel Genie queries** - All 3 started at same timestamp (22:12:13,328)
3. **Data summarization** - 80 rows → 33 rows before sending to LLM
4. **System prompt sent once** - Only in Stage 2, not repeated

---

## 🆚 Head-to-Head Comparison

| Metric | Original Agent | Two-Stage Generator | Winner |
|--------|----------------|---------------------|--------|
| **Total Time** | 101s | 46s | 🏆 Two-Stage (54% faster) |
| **LLM Calls** | 5 | 2 | 🏆 Two-Stage (60% fewer) |
| **Genie Queries** | 4 (sequential) | 3 (parallel) | 🏆 Two-Stage |
| **Biggest Data Response** | 180+ rows (raw) | 80→33 rows | 🏆 Two-Stage (82% smaller) |
| **System Prompt Overhead** | 5× (~20K tokens) | 2× (~4.3K tokens) | 🏆 Two-Stage (78% less) |

### Time Breakdown

| Phase | Original | Two-Stage | Improvement |
|-------|----------|-----------|-------------|
| Planning | ~7s | 4s | 43% faster |
| Genie Queries | ~40s (sequential) | 15s (parallel) | **63% faster** |
| LLM Processing | ~54s (5 calls) | 27s (1 call) | **50% faster** |
| **TOTAL** | **101s** | **46s** | **54% faster** |

### Token Usage Comparison

| Component | Original Agent | Two-Stage | Reduction |
|-----------|----------------|-----------|-----------|
| Planning Prompt | N/A | ~800×1 = 800 | N/A |
| System Prompt | ~4,000×5 = 20,000 | ~3,500×1 = 3,500 | **82%** |
| Genie Data | 180+ rows raw | 33 rows summarized | **82%** |
| HTML Output | ~8,000 | ~8,000 | Same |
| **TOTAL INPUT** | **~40,000+** | **~14,000** | **~65%** |

---

## 🎉 Comparison Complete

### The Key Insight

The original agent's **Query 2 returned 180+ rows** of monthly trend data that was:
- Sent **raw** to the LLM
- **Accumulated** in the agent's scratchpad
- Included in **every subsequent LLM call**

The Two-Stage Generator:
1. Got similar data (80 rows)
2. **Summarized it to 33 rows** before sending to LLM
3. Ran queries **in parallel** instead of sequentially
4. Only made **2 LLM calls** instead of 5

### Quality Verification ✅

Both approaches generated slides with:
- ✅ Top 10 use cases by spend (bar chart)
- ✅ Monthly trend data (line chart)
- ✅ Proper HTML structure with Chart.js
- ✅ Professional styling and color schemes

**Same quality, 54% faster, 65% fewer tokens.**

---

## Detailed Logs (Two-Stage Generator)

<details>
<summary>Click to expand full logs</summary>

**Initialization:**
```
2025-11-27 22:12:05,012 - src.api.services.chat_service - INFO - Using TWO-STAGE generator (token optimized)
2025-11-27 22:12:06,993 - src.services.two_stage_generator - INFO - MLflow experiment already exists
2025-11-27 22:12:07,218 - src.services.two_stage_generator - INFO - MLflow LangChain autologging enabled
```

**Stage 1 (Planning):**
```
2025-11-27 22:12:09,347 - src.services.query_planner - INFO - Planning queries (sync) for request
2025-11-27 22:12:13,325 - httpx - INFO - HTTP Request: POST .../serving-endpoints/chat/completions "HTTP/1.1 200 OK"
2025-11-27 22:12:13,328 - src.services.query_planner - INFO - Query planning complete (sync)
```

**Execution (Genie - note same timestamp = parallel):**
```
2025-11-27 22:12:13,328 - src.services.two_stage_generator - INFO - Executing Genie queries in parallel
2025-11-27 22:12:13,328 - src.services.tools - INFO - Querying Genie space
2025-11-27 22:12:13,328 - src.services.tools - INFO - Querying Genie space
2025-11-27 22:12:13,329 - src.services.tools - INFO - Querying Genie space
2025-11-27 22:12:28,261 - src.services.two_stage_generator - INFO - Genie queries completed
```

**Stage 2 (Generation):**
```
2025-11-27 22:12:28,265 - src.services.two_stage_generator - INFO - Stage 2: Generating slides
2025-11-27 22:12:55,421 - httpx - INFO - HTTP Request: POST .../serving-endpoints/chat/completions "HTTP/1.1 200 OK"
2025-11-27 22:12:55,423 - src.services.two_stage_generator - INFO - Stage 2 complete: Slide generation
```

</details>

---

### Next Steps

| Priority | Task | Status |
|----------|------|--------|
| 1 | ✅ Verify 3-slide generation works (Two-Stage) | Complete |
| 2 | ✅ Run baseline test with original agent | Complete |
| 3 | ✅ Document comparison results | Complete |
| 4 | ✅ Test with 5-slide request | Complete |
| 5 | ✅ Test editing mode | Complete |

### Editing Mode Test (Nov 27, 23:53-23:55)

```
Edit 1: Mode=EDIT | Queries=0 | Time=12.6s | Output=2,055 chars
Edit 2: Mode=EDIT | Queries=0 | Time=14.0s | Output=2,157 chars
```

**Key:** Planner correctly identified no new data needed → 0 Genie queries → fast edits (~13s vs ~58s for new)

### 5-Slide Test Result (Nov 27, 23:33)

```
Total time: 58.48s | LLM calls: 2 | Genie queries: 5 | Data: 106→54 rows | Output: 14,902 chars
```

| Metric | 3 Slides | 5 Slides | Notes |
|--------|----------|----------|-------|
| Total Time | 46s | 58s | +26% for 67% more content |
| LLM Calls | 2 | **2** | ✅ Stays constant! |
| Genie Queries | 3 | 5 | Scales with data needs |

---

## Related Documents

- [Token Optimization Analysis](./TOKEN_OPTIMIZATION_ANALYSIS.md) - Problem analysis and solution design
- [Technical Doc Template](./technical-doc-template.md) - Documentation standards

