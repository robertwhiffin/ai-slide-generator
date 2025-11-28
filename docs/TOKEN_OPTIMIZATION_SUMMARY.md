# 🚀 Token Optimization: Two-Stage Architecture

**Date:** November 27, 2025  
**Author:** Tariq  
**Status:** ✅ Implemented & Tested

---

## TL;DR

Rebuilt the slide generator with a **Two-Stage Architecture** that reduces token usage by **65%** and speeds up generation by **54%**.

---

## The Problem

The original LangChain agent was hitting token limits after just 3-4 slides:

```
Original Agent (3 slides):
├── 5-6 LLM calls (each with full 4K system prompt)
├── System prompt repeated 5× = 20,000 tokens wasted
├── Raw Genie data (180+ rows) accumulating in context
└── Total: ~40,000+ tokens for just 3 slides 😬
```

---

## The Solution

**Two-Stage Architecture + Data Summarization:**

```
Stage 1: PLANNING (1 LLM call, short prompt)
   └── "What data do I need?" → List of Genie queries

Stage 2: EXECUTION (No LLM)
   ├── Run all Genie queries in PARALLEL
   └── SUMMARIZE large responses (180 rows → 33 rows)

Stage 3: GENERATION (1 LLM call, full prompt)
   └── Generate all slides with summarized data
```

**Key insight:** System prompt only sent ONCE (in Stage 2), not 5-6 times.

---

## Results 📊

### Head-to-Head Comparison (Same Prompt)

| Metric | Original Agent | Two-Stage | Improvement |
|--------|----------------|-----------|-------------|
| **Total Time** | 101s | 46s | **54% faster** |
| **LLM Calls** | 5 | 2 | **60% fewer** |
| **Genie Execution** | Sequential | Parallel | **63% faster** |
| **System Prompt Overhead** | 20,000 tokens | 4,300 tokens | **78% reduction** |
| **Data Size** | 180+ rows raw | 33 rows summarized | **82% smaller** |

### Scaling Test (5 Slides)

| Metric | 3 Slides | 5 Slides | Notes |
|--------|----------|----------|-------|
| Total Time | 46s | 58s | +26% for 67% more content |
| LLM Calls | **2** | **2** | ✅ Stays constant! |

### Editing Mode

```
Edit request: ~13 seconds
Genie queries: 0 (planner knows no new data needed)
```

---

## What Changed

| Component | File | Purpose |
|-----------|------|---------|
| Query Planner | `src/services/query_planner.py` | Stage 1: Plans all queries upfront |
| Data Summarizer | `src/services/data_summarizer.py` | Reduces 180 rows → 33 samples |
| Two-Stage Generator | `src/services/two_stage_generator.py` | Orchestrates the flow |
| Prompts | `src/services/prompts.py` | Separated planning vs generation prompts |

**Feature flag:** `USE_TWO_STAGE_GENERATOR=true`

Original agent untouched – can switch back anytime.

---

## Key Wins

1. **65% token reduction** → Can generate 10-20+ slides now
2. **54% faster** → Better user experience
3. **Parallel Genie queries** → Huge speed boost
4. **Smart editing** → No unnecessary data fetches
5. **Same quality** → All the same instructions, just sent once

---

## Documentation

- `docs/TOKEN_OPTIMIZATION_ANALYSIS.md` - Full problem analysis & architecture
- `docs/TWO_STAGE_IMPLEMENTATION_PLAN.md` - Implementation details & test results

---

## Quick Slack Summary

```
🚀 Token Optimization Complete!

Built a Two-Stage slide generator that:
• 65% fewer tokens (can do 10-20+ slides now)
• 54% faster (46s vs 101s for 3 slides)
• LLM calls: 5 → 2 (constant regardless of slide count)
• Parallel Genie queries
• Smart editing (skips data fetch when not needed)

Feature flag: USE_TWO_STAGE_GENERATOR=true
Original agent untouched as fallback.

Full docs in docs/TOKEN_OPTIMIZATION_*.md
```

