# Token Usage Optimization Analysis

**Date:** November 27, 2025  
**Purpose:** Problem analysis and solution design for token optimization  
**Related:** [TWO_STAGE_IMPLEMENTATION_PLAN.md](./TWO_STAGE_IMPLEMENTATION_PLAN.md) — Implementation details & test results

---

## Executive Summary

This document explains **why** the original slide generator agent consumed excessive tokens and **how** the Two-Stage Architecture + Data Summarization solution addresses this.

### The Problem We Observed

```
User Request: "Create 3 slides about top 10 use cases in KPMG UK"

WHAT HAPPENED:
├── 5 Genie Queries executed
├── Query 3 returned 140 ROWS of monthly trend data
├── ~6 LLM Calls (each with full system prompt)
└── Estimated Total: 45,000+ input tokens for just 3 slides
```

### Original Agent Architecture (The Problem)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ORIGINAL LANGCHAIN AGENT: Iterative Tool-Calling Loop                      │
└─────────────────────────────────────────────────────────────────────────────┘

User Request: "Create 3 slides about top 10 use cases"
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM CALL 1                                                                  │
│  ─────────────────────────────────────────────────────────────────────────── │
│  INPUT:                                                                      │
│  ├── System Prompt (4,000 tokens) ◄─── FULL PROMPT EVERY TIME               │
│  ├── User Request (200 tokens)                                               │
│  └── Tools Available: [query_genie_space]                                    │
│                                                                              │
│  OUTPUT: "I need to query for top use cases by spend"                        │
│  ACTION: Call query_genie_space("top 10 use cases by spend")                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ Genie returns 10 rows
┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM CALL 2                                                                  │
│  ─────────────────────────────────────────────────────────────────────────── │
│  INPUT:                                                                      │
│  ├── System Prompt (4,000 tokens) ◄─── REPEATED                             │
│  ├── User Request (200 tokens)                                               │
│  ├── Previous: Query 1 result (150 tokens) ◄─── ACCUMULATING                │
│  └── Tools Available: [query_genie_space]                                    │
│                                                                              │
│  OUTPUT: "Now I need monthly trend data"                                     │
│  ACTION: Call query_genie_space("monthly spend trend for top 10")            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ Genie returns 140 rows! 
┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM CALL 3                                                                  │
│  ─────────────────────────────────────────────────────────────────────────── │
│  INPUT:                                                                      │
│  ├── System Prompt (4,000 tokens) ◄─── REPEATED AGAIN                       │
│  ├── User Request (200 tokens)                                               │
│  ├── Previous: Query 1 (150) + Query 2 (3,500!) ◄─── HUGE ACCUMULATION      │
│  └── Tools Available: [query_genie_space]                                    │
│                                                                              │
│  OUTPUT: "I need workspace counts..."                                        │
│  ACTION: Call query_genie_space("workspaces per use case")                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ ... this continues ...
┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM CALL 6 (Final)                                                          │
│  ─────────────────────────────────────────────────────────────────────────── │
│  INPUT:                                                                      │
│  ├── System Prompt (4,000 tokens) ◄─── REPEATED 6TH TIME                    │
│  ├── User Request (200 tokens)                                               │
│  ├── ALL previous queries + results (4,000+ tokens)                          │
│  └── Agent scratchpad (accumulated reasoning)                                │
│                                                                              │
│  OUTPUT: Generate complete HTML slides                                       │
└─────────────────────────────────────────────────────────────────────────────┘

PROBLEM SUMMARY:
├── System Prompt (4,000 tokens) × 6 calls = 24,000 tokens WASTED
├── Genie data accumulates through every call (sent multiple times)
├── Query 2's 140 rows (3,500 tokens) sent in calls 3, 4, 5, and 6
└── TOTAL: ~47,000 input tokens for just 3 slides
```

### The Two Core Problems

| Root Cause | What's Happening | Token Impact |
|------------|------------------|--------------|
| **System Prompt Repetition** | 4,000 tokens sent with EVERY LLM call (×6 calls = 24K) | 53% |
| **Raw Data Accumulation** | 140 rows = 3,500 tokens stuffed into context | 27% |
| **HTML Output** | 8,000 tokens of generated slides | 18% |

### Three Solutions (Ranked)

| Solution | Token Reduction | Scales to 10+ slides? | Complexity | Recommendation |
|----------|----------------|----------------------|------------|----------------|
| 🥇 **Both Combined** | **75-80%** | ✅ Yes (20+ slides) | Medium | **DO THIS** |
| 🥈 Two-Stage Only | 50-55% | ⚠️ Fragile | Medium | Partial fix |
| 🥉 Data Summary Only | 30-40% | ❌ No | Low | Insufficient |

---

## Fresh Test Data: 3-Slide Generation

### Genie Queries Made

| # | Query | Rows Returned | Estimated Tokens |
|---|-------|---------------|------------------|
| 1 | Top 10 use cases by spend | 6 | ~150 |
| 2 | Workspaces per use case | 6 | ~150 |
| 3 | **Monthly trend for top 10** | **140** | **~3,500** ← THE KILLER |
| 4 | Total UK spend | 1 | ~50 |
| 5 | Latest month spend per case | 6 | ~150 |
| **TOTAL** | | **159 rows** | **~4,000 tokens** |

### Why Query 3 Is The Problem

```
Query: "Monthly spend trend for top 10 use cases over time"

WHAT GENIE RETURNED:
├── 6 use cases
├── × 35 months of data (Jan 2023 - Nov 2025)  
├── = 140 rows of JSON like this:

[{"month_date":"2023-01-01","use_case_name":"UK Global Audit Workbench","spend_amount":"11.64"},
 {"month_date":"2023-01-01","use_case_name":"Unknown UK","spend_amount":"244.15"},
 {"month_date":"2023-02-01","use_case_name":"UK Global Audit Workbench","spend_amount":"2.04"},
 ... (137 more rows like this) ...]

TOKEN COUNT: ~3,500 tokens of raw data
```

### What The LLM Actually Needed

The LLM extracted these insights from those 140 rows:
- "EDP grew from £0 to £14K/month"
- "UK Global Audit Workbench spiked to £49K in Oct 2025"
- "Forensics emerged in Jan 2025, now at £18K/month"

**Those 3 sentences = ~50 tokens. The raw data = 3,500 tokens.**

That's a **70:1 compression ratio** we're missing.

### Token Accumulation Through 6 LLM Calls

```
Call 1: System Prompt (4,000) + User Question
        = 4,500 tokens

Call 2: System Prompt (4,000) + Previous + Query 1 Result
        = 4,650 tokens

Call 3: System Prompt (4,000) + Previous + Query 2 Result
        = 4,800 tokens

Call 4: System Prompt (4,000) + Previous + Query 3 Result (140 rows!)
        = 8,300 tokens  ← JUMPS due to 140-row result

Call 5: System Prompt (4,000) + Previous + Query 4 Result
        = 8,350 tokens

Call 6: System Prompt (4,000) + ALL previous + Generate HTML
        = 16,000+ tokens

──────────────────────────────────────────────────────
TOTAL INPUT TOKENS: ~47,000 for just 3 slides
```

---

## Solutions Explored

We analyzed three approaches before deciding on the combined solution. This section documents each option and why we chose the combined approach.

---

### 🥉 Option 1: Data Summarization Only

### What It Does

Intercepts Genie results and summarizes them before passing to LLM:
- 140 rows → 20 representative rows + aggregates
- Raw JSON → Structured summary with key insights

### Implementation

```python
def summarize_genie_response(data: list[dict]) -> dict:
    """Summarize large Genie responses before passing to LLM."""
    df = pd.DataFrame(data)
    
    # Detect time series data (like that 140-row query)
    date_cols = [c for c in df.columns if 'date' in c.lower() or 'month' in c.lower()]
    
    if date_cols and len(df) > 20:
        # Sample every Nth row + add aggregates
        step = len(df) // 20
        sampled = df.iloc[::step]
        return {
            "type": "time_series",
            "summary": f"{len(df)} data points from {df[date_cols[0]].min()} to {df[date_cols[0]].max()}",
            "sampled_data": sampled.to_dict(orient='records'),
            "aggregates": df.groupby('use_case_name').agg({
                'spend_amount': ['sum', 'mean', 'max']
            }).to_dict()
        }
    
    return {"data": data[:20], "total_rows": len(data)}
```

### Token Impact

```
BEFORE SUMMARIZATION:
├── Query 3 Result: 3,500 tokens
├── All Genie Data: ~4,000 tokens
└── Sent 6 times through LLM calls

AFTER SUMMARIZATION:
├── Query 3 Result: 500 tokens (sampled + aggregates)
├── All Genie Data: ~1,000 tokens
└── Still sent 6 times through LLM calls

SAVINGS:
├── Per query: 3,000 tokens saved
├── Accumulated: ~10,000 tokens saved
└── Total reduction: ~30-40%

RESULT:
├── 47,000 tokens → ~32,000 tokens
├── Still 6 LLM calls
├── System prompt still repeated 6 times (24K tokens!)
└── ⚠️ NOT ENOUGH for 10+ slides
```

### Verdict

| Pros | Cons |
|------|------|
| ✅ Simple to implement | ❌ Doesn't fix system prompt repetition |
| ✅ Low risk | ❌ Still 6 LLM calls = slow |
| ✅ Helps the 140-row problem | ❌ Won't scale to 10+ slides |

**Rating: Helpful but insufficient for production.**

---

### 🥈 Option 2: Two-Stage Architecture Only

### What It Does

Separates planning from execution:
1. **Stage 1 (Planning):** One LLM call generates ALL Genie queries upfront
2. **Execution:** Code runs all queries (no LLM)
3. **Stage 2 (Generation):** One LLM call generates all slides

### Implementation

```python
# Stage 1: Planning
PLANNING_PROMPT = """Analyze this request and output a JSON list of Genie queries needed.
Be comprehensive but efficient (3-6 queries max).
{"queries": ["query 1", "query 2", ...]}"""

async def stage_1_plan(user_request: str) -> list[str]:
    response = await llm.invoke(PLANNING_PROMPT + user_request)
    return json.loads(response)["queries"]

# Execution: No LLM, just run queries
async def execute_queries(queries: list[str]) -> dict:
    results = {}
    for q in queries:
        results[q] = await query_genie_space(q)
    return results

# Stage 2: Generation
async def stage_2_generate(user_request: str, data: dict) -> str:
    return await llm.invoke(FULL_SYSTEM_PROMPT + f"""
    User Request: {user_request}
    Data Available: {json.dumps(data)}
    Generate complete HTML slides.
    """)
```

### Token Impact

```
BEFORE TWO-STAGE:
├── 6 LLM Calls
├── System Prompt × 6 = 24,000 tokens
├── Genie Data accumulates through all calls
└── Total: 47,000 tokens

AFTER TWO-STAGE:
├── 2 LLM Calls only
├── Stage 1: Short prompt (800 tokens) + User request
├── Stage 2: Full prompt (4,000) + ALL raw data (4,000) + HTML output
└── Total: ~25,000 tokens

SAVINGS:
├── System prompt: 24,000 → 4,800 tokens (80% reduction)
├── Total reduction: ~50%

BUT PROBLEM:
├── Raw Genie data (4,000 tokens) still goes to Stage 2
├── That 140-row query is still 3,500 tokens
└── ⚠️ 10+ slides could still hit limits
```

### Verdict

| Pros | Cons |
|------|------|
| ✅ Dramatically fewer LLM calls | ❌ Raw data still large |
| ✅ 80% reduction in prompt tokens | ❌ Fragile for very data-heavy requests |
| ✅ Much faster (2 calls vs 6) | ❌ Medium complexity to implement |

**Rating: Good improvement but fragile at scale.**

---

### 🥇 Option 3: Both Combined ← CHOSEN SOLUTION

### What It Does

Combines Two-Stage Architecture with Data Summarization:
1. **Stage 1:** Planning LLM (short prompt)
2. **Execution:** Genie queries + **SUMMARIZATION**
3. **Stage 2:** Generation LLM (full prompt + **compact data**)

### The Key Insight

**Neither solution alone is enough:**
- Data Summarization alone: Still 6 LLM calls, 24K tokens of repeated prompts
- Two-Stage alone: Still 4K tokens of raw data per big query

**Together they fix both problems:**
- 2 LLM calls = minimal prompt repetition
- Summarized data = minimal data bloat

### Token Impact

```
COMBINED SOLUTION:
├── Stage 1: 800 (short prompt) + 200 (user request) = 1,000 tokens
├── Execution: 0 LLM tokens (just code)
├── Stage 2: 4,000 (full prompt) + 1,000 (summarized data) + 8,000 (HTML) = 13,000 tokens
└── TOTAL: ~14,000 tokens

COMPARISON:
├── Current: 47,000 tokens for 3 slides
├── With Solution: 14,000 tokens for 3 slides
└── REDUCTION: 70% for 3 slides

SCALING:
├── 5 slides: 16,000 tokens (vs 60,000+ current → likely fails)
├── 10 slides: 22,000 tokens (vs 100,000+ current → definitely fails)
├── 15 slides: 28,000 tokens (vs 150,000+ current → impossible)
└── 20+ slides: Still possible!
```

### Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│  USER: "Create 10 slides about top use cases with trends"             │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: PLANNING (1 LLM Call)                                        │
│  ──────────────────────────────                                        │
│  Input: SHORT prompt (800 tokens) + User request                       │
│  Output: ["Query 1", "Query 2", "Query 3", "Query 4", "Query 5"]       │
│                                                                        │
│  Tokens Used: ~1,000                                                   │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  EXECUTION: (NO LLM - Code Only)                                       │
│  ──────────────────────────────                                        │
│  1. Run all 5 Genie queries in parallel                                │
│  2. SUMMARIZE each response:                                           │
│     • 140-row trend data → 20 samples + aggregates                     │
│     • Small results → keep as-is                                       │
│  3. Package into single data object                                    │
│                                                                        │
│  Tokens Used: 0 (no LLM)                                               │
│  Data Output: ~1,000 tokens (vs 4,000 raw)                             │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: GENERATION (1 LLM Call)                                      │
│  ────────────────────────────────                                      │
│  Input: FULL prompt (4,000) + Summarized data (1,000)                  │
│  Output: Complete HTML slides (8,000+ tokens)                          │
│                                                                        │
│  Tokens Used: ~5,000 input + ~8,000 output = ~13,000                   │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  RESULT: 10 beautiful slides generated                                 │
│  Total Tokens: ~14,000 (vs 100,000+ current = 85% reduction)           │
└────────────────────────────────────────────────────────────────────────┘
```

### Verdict

| Pros | Cons |
|------|------|
| ✅ 70-80% token reduction | ⚠️ Medium implementation effort |
| ✅ Scales to 20+ slides | ⚠️ Requires refactoring agent |
| ✅ Much faster (2 calls vs 6+) | |
| ✅ Future-proof | |
| ✅ Handles any data size | |

**Rating: The right solution for production.**

---

## Decision Matrix

| Factor | Data Summary Only | Two-Stage Only | **Both Combined** |
|--------|------------------|----------------|-------------------|
| Token Reduction | 30-40% | 50-55% | **70-80%** |
| Handles 140-row queries | ✅ Yes | ❌ No | **✅ Yes** |
| Reduces LLM calls | ❌ No (6 calls) | ✅ Yes (2 calls) | **✅ Yes (2 calls)** |
| Scales to 10+ slides | ❌ No | ⚠️ Fragile | **✅ Yes** |
| Implementation | Low | Medium | **Medium** |
| Speed improvement | 20% | 60% | **70%** |

---

## Where Do Instructions Go? (Detailed Flow) ---------------------------------------------------------------------------------------------------

A critical question: In the Two-Stage Architecture, where do the important instructions go?

### Current Architecture: Instructions Sent 6 Times

```
CURRENT (WASTEFUL):

Every single LLM call includes:
├── Core Role & Identity (~500 tokens)
├── Slide Formatting Guidelines (~800 tokens)
├── Chart.js Code Examples (~700 tokens)
├── Color Schemes & Typography (~400 tokens)
├── Slide Editing Instructions (~300 tokens)  ← Even when NOT editing!
└── Tool Usage Instructions (~300 tokens)

Total: ~3,000 tokens × 6 calls = 18,000 tokens of repeated instructions
```

### Two-Stage Architecture: Instructions Sent Once

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: PLANNING                                                          │
│  ─────────────────                                                          │
│                                                                              │
│  PROMPT: Short & Focused (~800 tokens)                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  "You are a data analyst. Given the user's presentation request,       │ │
│  │   identify what data queries are needed from the Genie space.          │ │
│  │                                                                         │ │
│  │   Output a JSON list of 3-6 natural language queries that would        │ │
│  │   provide comprehensive data for the requested slides.                 │ │
│  │                                                                         │ │
│  │   Format: {"queries": ["query 1", "query 2", ...]}"                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ❌ NO slide formatting instructions                                         │
│  ❌ NO Chart.js examples                                                     │
│  ❌ NO editing instructions                                                  │
│  ❌ NO HTML templates                                                        │
│                                                                              │
│  WHY: This stage only decides WHAT data to get, not HOW to present it       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXECUTION (No LLM)                                                         │
│  ──────────────────                                                         │
│  • Run all Genie queries                                                    │
│  • Summarize responses                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: GENERATION                                                        │
│  ───────────────────                                                        │
│                                                                              │
│  PROMPT: Full System Prompt (~4,000 tokens) - ALL instructions here         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  ✅ CORE ROLE & IDENTITY                                                │ │
│  │     "You are an expert presentation designer creating HTML slides..."   │ │
│  │                                                                         │ │
│  │  ✅ SLIDE FORMATTING GUIDELINES                                         │ │
│  │     - 1280x720 dimensions                                                │ │
│  │     - Typography rules, color schemes                                    │ │
│  │     - Layout patterns                                                    │ │
│  │                                                                         │ │
│  │  ✅ CHART.JS CODE EXAMPLES                                              │ │
│  │     - Bar chart template                                                 │ │
│  │     - Line chart template                                                │ │
│  │     - Initialization patterns                                            │ │
│  │                                                                         │ │
│  │  ✅ SLIDE EDITING INSTRUCTIONS (only if editing!)                       │ │
│  │     - How to modify existing slides                                      │ │
│  │     - Preserve structure rules                                           │ │
│  │                                                                         │ │
│  │  + Summarized Data (~1,000 tokens)                                       │ │
│  │  + User Request                                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  THIS is where all the important instructions live - sent ONCE only         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Instruction Placement Summary

| Component | Current (6 calls) | Two-Stage (2 calls) |
|-----------|------------------|---------------------|
| Core slide instructions | Sent 6× | Sent **1×** (Stage 2) |
| Chart.js examples | Sent 6× | Sent **1×** (Stage 2) |
| Formatting guidelines | Sent 6× | Sent **1×** (Stage 2) |
| Editing instructions | Sent 6× (always!) | Sent **1×** (only when editing) |

**The full system prompt with ALL your carefully crafted instructions goes to Stage 2 - the LLM that actually generates the HTML.**

Stage 1 only needs to be smart enough to figure out "what data should I ask for?" - it doesn't need CSS, Chart.js, or slide layouts.

---

## What Is "Editing" vs "Creating"?

### The Two User Modes

| Mode | What User Is Doing | Example |
|------|-------------------|---------|
| **Creating** (New) | Generating slides from scratch | "Create 3 slides about use cases" |
| **Editing** (Modify) | Changing existing slides | "Make slide 2 use a pie chart" |

### Example User Flow

```
Step 1 (CREATING):
User: "Create 3 slides about top use cases in KPMG UK"
→ LLM generates 3 new slides
→ NO editing instructions needed

Step 2 (EDITING):
User: "Change the title on slide 1 to be shorter"
→ LLM modifies existing slides
→ EDITING INSTRUCTIONS needed (how to preserve content, etc.)

Step 3 (EDITING):
User: "Add a comparison chart to slide 2"
→ LLM modifies existing slides
→ EDITING INSTRUCTIONS needed
```

### Current Problem

```
CURRENT (WASTEFUL):
├── Editing instructions (~300 tokens) sent with EVERY call
├── Even for brand new presentations
├── Even for the planning calls
└── 300 tokens × 6 calls = 1,800 tokens wasted
```

### Proposed Fix

```python
def build_generation_prompt(user_request: str, data: dict, existing_slides: str = None) -> str:
    prompt = CORE_SLIDE_INSTRUCTIONS     # Always included (~3,000 tokens)
    prompt += CHART_JS_EXAMPLES          # Always included (~700 tokens)
    
    # Only add editing instructions when actually editing
    if existing_slides:
        prompt += SLIDE_EDITING_INSTRUCTIONS  # (~300 tokens)
        prompt += f"\n\nExisting slides to modify:\n{existing_slides}"
    
    prompt += f"\n\nData available:\n{json.dumps(data)}"
    prompt += f"\n\nUser request: {user_request}"
    
    return prompt
```

**Result:**
- **New presentation:** 3,700 tokens of instructions (no editing section)
- **Editing existing:** 4,000 tokens of instructions (includes editing section)

---

## Speed Comparison

### Current Architecture Speed

```
CURRENT FLOW (3 slides):
├── LLM Call 1: Plan first query        → 8-12 seconds
├── Genie Query 1                       → 3-5 seconds
├── LLM Call 2: Plan second query       → 8-12 seconds
├── Genie Query 2                       → 3-5 seconds
├── LLM Call 3: Plan third query        → 8-12 seconds
├── Genie Query 3 (140 rows!)           → 5-8 seconds
├── LLM Call 4: Plan fourth query       → 10-15 seconds (bigger context now)
├── Genie Query 4                       → 3-5 seconds
├── LLM Call 5: Plan fifth query        → 10-15 seconds
├── Genie Query 5                       → 3-5 seconds
├── LLM Call 6: Generate HTML           → 15-25 seconds
└── TOTAL                               → 80-120 seconds (1.5-2 minutes)
```

### Two-Stage Architecture Speed

```
TWO-STAGE FLOW (3 slides):
├── LLM Call 1: Plan ALL queries        → 5-8 seconds (short prompt)
├── Genie Queries 1-5 (PARALLEL!)       → 8-12 seconds (run simultaneously)
├── Data Summarization (code)           → <1 second
├── LLM Call 2: Generate HTML           → 15-25 seconds
└── TOTAL                               → 30-45 seconds

SPEED IMPROVEMENT: 50-60% faster!
```

### Speed Comparison Table

| Scenario | Current | Two-Stage | Improvement |
|----------|---------|-----------|-------------|
| 3 slides | 80-120s | 30-45s | **50-60% faster** |
| 5 slides | 120-180s | 35-50s | **65-70% faster** |
| 10 slides | 200+ s (if possible) | 45-60s | **70%+ faster** |

### Why So Much Faster?

1. **Fewer LLM calls:** 2 instead of 6+ (LLM calls are slow, ~10-15s each)
2. **Parallel Genie queries:** Run all 5 queries at once instead of sequentially
3. **Smaller contexts:** Less data to process per call = faster responses

---

## Quality Comparison

### Will Quality Decrease?

**No - quality should be the SAME or BETTER.** Here's why:

### Same Quality Factors

| Factor | Current | Two-Stage | Notes |
|--------|---------|-----------|-------|
| System prompt | Full instructions | Full instructions | Same prompt in Stage 2 |
| Chart.js examples | Included | Included | Same examples |
| Formatting rules | Included | Included | Same rules |
| Data available | Raw data | Summarized + raw | Same or more info |

### Potentially BETTER Quality

1. **Holistic View:** The LLM sees ALL data at once in Stage 2, not incrementally. This means:
   - Better narrative flow across slides
   - More coherent story arc
   - Smarter data selection

2. **No "Surprise" Data:** Currently, the LLM sometimes makes suboptimal choices because it doesn't know what data is coming later. With Two-Stage:
   - LLM plans queries knowing the full request
   - LLM generates slides knowing all available data

3. **Cleaner Context:** Summarized data is easier for the LLM to reason about:
   - Raw: 140 rows of `{"month_date":"2023-01-01","spend_amount":"11.64"}`
   - Summarized: "EDP grew from £0 to £14K/month, peaked Jan 2025"

### Quality Summary

| Aspect | Impact |
|--------|--------|
| Instruction quality | ✅ Same (all instructions in Stage 2) |
| Data comprehension | ✅ Same or better (summarized = clearer) |
| Slide narrative | ✅ Better (holistic view of all data) |
| Chart accuracy | ✅ Same (sampled data still accurate for trends) |

---

## Quick Wins (Incorporated into Solution)

The following optimizations were incorporated into the Two-Stage implementation:

### 1. Conditional Slide Editing Instructions ✅
Editing instructions (~300 tokens) are only included when modifying existing slides, not for new presentations.

### 2. Data Summarization ✅
Large Genie responses are automatically summarized before being sent to the LLM, reducing 140+ rows to ~20 representative samples.

### 3. Parallel Query Execution ✅
All Genie queries run in parallel instead of sequentially, significantly reducing total execution time.

---

## Decision

Based on the analysis above, we implemented **Option 3: Both Combined** (Two-Stage Architecture + Data Summarization).

**Why this was the right choice:**
- Neither solution alone was sufficient
- Data Summarization alone: Still 6 LLM calls with repeated system prompts
- Two-Stage alone: Still sending raw data (3,500+ tokens per big query)
- Combined: 2 LLM calls + summarized data = optimal token usage

**Expected Impact:**
- 65-70% token reduction
- 50-60% faster execution
- Scales to 20+ slides (previously limited to 3-4)

**Implementation:** See [TWO_STAGE_IMPLEMENTATION_PLAN.md](./TWO_STAGE_IMPLEMENTATION_PLAN.md)

---

## Appendix: Raw Test Data

### 3-Slide Test - Query 3 Full Response (140 rows)

```json
[
  {"month_date":"2023-01-01","use_case_name":"UK Global Audit Workbench","spend_amount":"11.65"},
  {"month_date":"2023-01-01","use_case_name":"Unknown UK","spend_amount":"244.15"},
  {"month_date":"2023-02-01","use_case_name":"UK Global Audit Workbench","spend_amount":"2.04"},
  {"month_date":"2023-02-01","use_case_name":"Unknown UK","spend_amount":"438.82"},
  ... (136 more rows) ...
  {"month_date":"2025-11-01","use_case_name":"Forensics","spend_amount":"18001.47"},
  {"month_date":"2025-11-01","use_case_name":"MDP","spend_amount":"190.96"},
  {"month_date":"2025-11-01","use_case_name":"UK Global Audit Workbench","spend_amount":"19473.05"},
  {"month_date":"2025-11-01","use_case_name":"Unknown UK","spend_amount":"2975.54"}
]
```

### What Summarized Version Would Look Like

```json
{
  "type": "time_series",
  "summary": "Monthly spend for 6 use cases from 2023-01 to 2025-11",
  "key_insights": [
    "EDP: £206K total, peaked £14.3K/month in Jan 2025, now £5K/month",
    "UK Global Audit: £204K total, massive spike to £49K in Oct 2025",
    "Audit: £152K total, growing steadily, now £13K/month",
    "Forensics: £87K total, started Jan 2025, now £18K/month"
  ],
  "sampled_data": [
    {"month":"2023-01","EDP":0,"Audit":0,"Workbench":12,"Forensics":0},
    {"month":"2024-01","EDP":1291,"Audit":0,"Workbench":4099,"Forensics":0},
    {"month":"2025-01","EDP":14349,"Audit":10694,"Workbench":4901,"Forensics":30},
    {"month":"2025-11","EDP":4988,"Audit":12782,"Workbench":19473,"Forensics":18001}
  ]
}
```

**Token comparison: 3,500 tokens → 400 tokens (89% reduction)**

---

## Summary

This document analyzed the token usage problem and designed the Two-Stage + Data Summarization solution.

**Key Takeaways:**
1. The original agent used 6+ LLM calls, repeating the 4,000-token system prompt each time
2. Large Genie responses (140+ rows) accumulated in the context, bloating token usage
3. The Two-Stage Architecture reduces LLM calls to 2, with data summarization keeping responses compact
4. Expected improvement: **65-70% token reduction, 50-60% faster execution**

---

## Implementation & Test Results

For implementation details, test results, and comparison data, see:

📄 **[TWO_STAGE_IMPLEMENTATION_PLAN.md](./TWO_STAGE_IMPLEMENTATION_PLAN.md)**

Contains:
- Implementation checklist and file list
- Head-to-head comparison (Original Agent vs Two-Stage)
- Actual test results with timing data
- Full execution logs
