# LLM as Judge - Implementation Plan

## Slide Verification Using MLflow 3.x GenAI Evaluate

**Status:** ✅ Implemented (Phase 1 MVP)  
**Author:** Implementation Team  
**Created:** December 2024  
**Last Updated:** December 15, 2024  
**Approach:** On-Demand LLM-as-Judge (MLflow Only)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Implementation Status](#implementation-status)
3. [Current Data Flow](#current-data-flow)
4. [Evaluation Criteria](#evaluation-criteria)
5. [Phase 1: Numerical Accuracy](#phase-1-numerical-accuracy)
6. [Phase 2: Narrative Quality](#phase-2-narrative-quality)
7. [User Feedback Mechanism](#user-feedback-mechanism)
8. [Source Data Visibility](#source-data-visibility)
9. [API Design](#api-design)
10. [Frontend Components](#frontend-components)
11. [Files Created/Modified](#files-createdmodified)

---

## Executive Summary

### Problem Statement

Users need confidence that AI-generated slides accurately reflect data from Genie. They want to:
- Verify numbers in slides match Genie source data
- See which queries produced which data
- Understand if the LLM hallucinated anything

### Solution

**Single-tier, on-demand LLM-as-Judge verification:**

1. User clicks 🔨 (gavel) button on a slide
2. Backend retrieves Genie source data + slide HTML
3. LLM evaluates accuracy using MLflow 3.x `make_judge`
4. Results show: score, rating, assessment explanation
5. User can provide feedback (👍/👎 with comment if negative)
6. User can view source data in Genie

### Key Principles

1. **On-demand only** - User triggers verification (cost ~$0.01-0.03/slide)
2. **MLflow native** - Uses MLflow 3.x make_judge (no fallback)
3. **Semantic comparison** - Formatting differences (7M = 7,000,000) are OK
4. **Derived numbers pass** - If Q1=100, Q2=150, "50% growth" is CORRECT
5. **Clear feedback** - Show assessment explanation, not just trace ID
6. **Source visibility** - Link to Genie conversation with all queries

---

## Implementation Status

### ✅ Completed (Phase 1 MVP)

| Component | File | Status |
|-----------|------|--------|
| LLM Judge Core | `src/services/evaluation/llm_judge.py` | ✅ Done |
| Verification API | `src/api/routes/verification.py` | ✅ Done |
| API Registration | `src/api/main.py` | ✅ Done |
| Frontend API | `frontend/src/services/api.ts` | ✅ Done |
| Verification Types | `frontend/src/types/verification.ts` | ✅ Done |
| Gavel Button | `frontend/src/components/SlidePanel/SlideTile.tsx` | ✅ Done |
| Verification Badge | `frontend/src/components/SlidePanel/VerificationBadge.tsx` | ✅ Done |
| Feedback Modal | Integrated in VerificationBadge | ✅ Done |
| Help Tab | `frontend/src/components/Help/HelpPage.tsx` | ✅ Done |
| Dependencies | `requirements.txt`, `pyproject.toml` | ✅ Done (litellm added) |
| Spike Test | `tests/test_llm_judge_spike.py` | ✅ Done |

### 🔲 Pending (Next Steps)

**High Priority:**
- [x] **Persist verification with session** - ✅ Done: Stored in `slide.verification` within `deck_json`
- [x] **Clear verification on slide edit** - ✅ Done: Cleared when slide HTML is modified
- [x] **User feedback storage** - ✅ Done: Logged as structured Assessments in MLflow using `log_feedback()`

**Phase 2:**
- [ ] Narrative Quality Judge
- [ ] "Verify All Slides" button
- [ ] Query-to-slide mapping (pass only relevant Genie data per slide)
- [ ] Verification dashboard/monitoring

---

## MLflow Integration Details

### How It Works

The LLM Judge uses MLflow 3.x `genai.evaluate()` with `make_judge` to create proper Evaluation Runs:

```python
# 1. Create a judge with custom instructions
accuracy_judge = mlflow.genai.make_judge(
    name="numerical_accuracy",
    instructions=JUDGE_INSTRUCTIONS,
    model="databricks:/databricks-claude-sonnet-4-5",
    feedback_value_type=Literal["excellent", "good", "moderate", "poor", "failing"],
)

# 2. Prepare evaluation data with MLflow structure
eval_data = pd.DataFrame([{
    "inputs": {"task": "Verify slide numerical accuracy"},
    "outputs": slide_html_content,           # What to evaluate
    "expectations": {"source_data": genie_data},  # Ground truth
}])

# 3. Run evaluation - creates Evaluation Run in MLflow
eval_result = mlflow.genai.evaluate(data=eval_data, scorers=[accuracy_judge])
```

### MLflow Data Structure

| Field | Content | Purpose |
|-------|---------|---------|
| `inputs` | `{"task": "Verify slide numerical accuracy"}` | Context/metadata |
| `outputs` | Slide HTML content | What's being evaluated |
| `expectations` | `{"source_data": "Genie query results..."}` | Ground truth to compare |

### Result Extraction

The evaluation result contains:
- `numerical_accuracy/value`: Rating (excellent/good/moderate/poor/failing)
- `assessments`: List of Assessment objects with `rationale` field
- `trace_id`: Link to MLflow trace

The rationale is extracted from the `numerical_accuracy` assessment in the `assessments` column.

---

## Current Data Flow

### What's Stored Today

| Data | Stored | Location | Status |
|------|--------|----------|--------|
| `genie_conversation_id` | ✅ | `UserSession` | Good - can link to Genie |
| Tool call queries | ✅ | `SessionMessage.metadata_json` | Good |
| Genie responses | ⚠️ | `SessionMessage.content` | Truncated to 500 chars |
| Slide deck | ✅ | `SessionSlideDeck.deck_json` | Good - full deck preserved |
| Verification results | ✅ | `slide.verification` in deck_json | Persists with session, survives refresh/restore |
| User feedback | ✅ | MLflow Assessments (Databricks) | Structured assessments linked to traces |
| Genie link | ⚠️ | Opens room only | Deep-link to conversation not supported by Databricks |

### ⚠️ Known Limitation: No Query-to-Slide Mapping

**Current behavior:** When verifying a slide, ALL Genie query results from the session are 
passed to the judge as `expectations.source_data`. The judge must determine which data is 
relevant to the specific slide being verified.

**Impact:**
- More tokens consumed (higher cost per verification)
- Judge must infer relevance from context
- Works well in practice, but less precise

**Future improvement:** Map specific queries to specific slides at generation time, so 
verification only passes relevant source data. This would:
- Reduce token usage
- Improve precision
- Enable per-slide data lineage tracking

This is tracked as a Phase 2 item: "Query-to-slide mapping"

---

## Evaluation Criteria

### What PASSES (Same meaning = No penalty)

| Source Data | Slide Shows | Why It Passes |
|-------------|-------------|---------------|
| 7,234,567 | 7.2M | Same value, different format |
| 7,234,567 | $7.2M | Added currency symbol |
| 7,234,567 | ~7 million | Words instead of digits |
| 0.15 | 15% | Percentage conversion |
| Q1=100, Q2=150 | "50% growth" | Correct calculation from source |
| chart: [7.2, 8.5, 9.1] | Chart shows same values | Chart.js data matches |

### What FAILS (Actually wrong)

| Source Data | Slide Shows | Why It Fails |
|-------------|-------------|--------------|
| 7,234,567 | 9.2M | Wrong number |
| Q1: 7M, Q2: 8M | Q1: 8M, Q2: 7M | Values swapped |
| (nothing about X) | X grew 50% | Hallucinated data |
| A=100, B=50 | "A is 3x B" | Wrong calculation |
| 7M (critical) | (missing) | Missing key data |

### Special Cases

**Slides Without Numbers:**
- Title slides: "No numerical data to verify"
- Skip verification, show info message

**Edited Slides:**
- Clear verification status on any edit
- Show "Re-verify recommended" indicator

---

## Phase 1: Numerical Accuracy

### User Flow

```
1. User generates slides via chat
2. Slides appear in SlidePanel
3. User hovers over slide tile
4. Clicks 🔨 (gavel) icon
5. Loading spinner: "Verifying..."
6. Results appear:
   - Badge: ✓ 95% (excellent) or ⚠ 60% (moderate)
   - Click badge for details:
     - Score + rating
     - Explanation
     - Issues (if any)
     - Genie link
     - 👍/👎 feedback
7. Badge persists with session (survives refresh)
8. If slide edited → badge clears, shows "Re-verify"
```

### Rating Scale

| Rating | Score | Meaning |
|--------|-------|---------|
| excellent | 95 | All numbers correctly represent source |
| good | 80 | Numbers correct, minor non-critical omissions |
| moderate | 60 | Most correct, some important data missing |
| poor | 40 | Some numbers wrong or key data missing |
| failing | 15 | Major errors, hallucinations, swapped values |

---

## Phase 2: Narrative Quality (Future)

Evaluate storytelling coherence:
- Does the deck flow logically?
- Are insights meaningful?
- Is there a clear narrative arc?
- Are conclusions supported by data?

Separate judge prompt focused on qualitative aspects.

---

## User Feedback Mechanism

### Flow (Option C - Asymmetric)

```
👍 Click → Log positive feedback → Done (instant, no modal)
👎 Click → Modal: "What was wrong?" → Submit → Log with comment
```

### Why This Approach

- 👍 = Quick, no friction (most common case)
- 👎 = Ask for detail (most valuable feedback)
- Negative feedback with context is gold for improvement

### MLflow Integration

**✅ Implemented:** Feedback is logged as structured **Assessments** using `mlflow.log_feedback()`.

```python
mlflow.set_tracking_uri("databricks")
mlflow.log_feedback(
    trace_id=trace_id,
    name="human_verification_feedback",
    value=is_positive,  # True/False
    rationale=user_comment,
    source=AssessmentSource(
        source_type=AssessmentSourceType.HUMAN,
        source_id=f"session_{session_id[:8]}"
    ),
    metadata={
        "session_id": session_id,
        "slide_index": slide_index,
        "feedback_type": "positive" | "negative",
    }
)
```

**Benefits:**
- ✅ Feedback appears in MLflow UI under trace's "Assessments" section
- ✅ Structured data (not just tags) for easy querying
- ✅ Linked directly to verification trace for full context
- ✅ Enables labeling workflows and quality monitoring
- ✅ Can be queried via MLflow API for analysis

---

## Source Data Visibility

### Genie Conversation Link

We store `genie_conversation_id` in the session. Link format:

```
https://{workspace}.azuredatabricks.net/genie/rooms/{space_id}
```

Display as: **"View Source Data in Genie"**

**⚠️ Limitation:** Databricks Genie UI does not support deep-linking to specific 
conversations. The link opens the Genie room, and users must find their conversation
in the room's history. The `conversation_id` is stored for potential API access.

When opened, users can find:
- Recent conversations in the room
- SQL generated by Genie
- Query results and data

---

## API Design

### Endpoint: `POST /api/verification/{slide_index}`

**Request:**
```json
{
  "session_id": "uuid-string"
}
```

**Response:**
```json
{
  "score": 80,
  "rating": "good",
  "explanation": "All revenue numbers accurately represent source data...",
  "issues": [],
  "duration_ms": 7959,
  "trace_id": "tr-abc123",
  "genie_conversation_id": "conv-xyz",
  "error": false
}
```

### Endpoint: `POST /api/verification/{slide_index}/feedback`

**Request:**
```json
{
  "session_id": "uuid-string",
  "slide_index": 0,
  "is_positive": false,
  "rationale": "Slide shows $9.2M but source says $9.1M",
  "trace_id": "tr-abc123..."
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Feedback submitted successfully",
  "linked_to_trace": true,
  "feedback_logged": true
}
```

**Note:** The `trace_id` is obtained from the verification response and passed to link feedback to the original verification trace.

### Endpoint: `GET /api/verification/genie-link?session_id={id}`

Returns the Genie conversation URL for the session.

---

## Frontend Components

### 1. VerificationBadge

Location: `frontend/src/components/SlidePanel/VerificationBadge.tsx`

Features:
- Gavel icon (🔨) to trigger verification
- Loading state with spinner
- Color-coded badge showing score and rating
- Click to expand details panel with:
  - Score bar visualization
  - **Assessment explanation/rationale** (from MLflow judge)
  - **MLflow Trace ID** (displayed with copy button for easy access)
  - Issues list (if any)
  - Genie link to view source data
- Thumbs up/down feedback (👎 requires comment, Enter to submit)
- Feedback automatically linked to verification trace
- Stale indicator when slide is edited post-verification
- Console logging of trace_id for debugging

### 2. Help Tab

Location: `frontend/src/components/Help/HelpPage.tsx`

Added "Verification" tab with:
- How it works explanation
- Rating scale reference
- What passes/fails examples
- Cost information
- Feedback guidance

---

## Files Created/Modified

### Backend (Python)

| File | Action | Description |
|------|--------|-------------|
| `src/services/evaluation/llm_judge.py` | MODIFIED | Updated to use MLflow 3.x `make_judge` |
| `src/services/evaluation/__init__.py` | MODIFIED | Updated exports |
| `src/api/routes/verification.py` | CREATED | API endpoints for verification |
| `src/api/main.py` | MODIFIED | Register verification routes |
| `requirements.txt` | MODIFIED | Added `litellm>=1.80.0` |
| `pyproject.toml` | MODIFIED | Added `litellm>=1.80.0` |
| `tests/test_llm_judge_spike.py` | CREATED | Spike test for MLflow judge |

### Frontend (TypeScript/React)

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/services/api.ts` | MODIFIED | Added verification API functions |
| `frontend/src/types/verification.ts` | CREATED | TypeScript types for verification |
| `frontend/src/components/SlidePanel/SlideTile.tsx` | MODIFIED | Added gavel button integration |
| `frontend/src/components/SlidePanel/VerificationBadge.tsx` | CREATED | Badge + details panel |
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | MODIFIED | Pass sessionId to SlideTile |
| `frontend/src/components/Help/HelpPage.tsx` | MODIFIED | Added Verification tab |

---

## Testing

### Spike Test Results

The spike test (`tests/test_llm_judge_spike.py`) validates:

| Test | Expected | Result |
|------|----------|--------|
| Correct slide (7M matches source) | Score >= 70 | ✅ Score: 80, Rating: good |
| Wrong slide (fabricated numbers) | Score < 70 | ✅ Score: 15, Rating: failing |
| Title slide (no numbers) | Handle gracefully | ✅ Score: 40, Rating: poor |

Run with:
```bash
cd "/path/to/project"
.venv/bin/python tests/test_llm_judge_spike.py
```

### Manual Testing Verified

| Feature | Status |
|---------|--------|
| Gavel button triggers verification | ✅ Works |
| Loading spinner during evaluation | ✅ Works |
| Score badge appears after verification | ✅ Works |
| Assessment explanation shown in details | ✅ Works |
| Genie link opens correct URL | ✅ Works |
| Evaluation runs visible in MLflow UI | ✅ Works |
| Feedback buttons (thumbs up/down) | ✅ Works |
| Verification persists on page refresh | ✅ Works |
| Verification restored from session history | ✅ Works |
| Verification cleared on slide edit | ✅ Works |

---

## Cost Estimation

| Action | Cost | Frequency |
|--------|------|-----------|
| Verify 1 slide | ~$0.01-0.03 | On-demand |
| Verify 10-slide deck | ~$0.10-0.30 | On-demand |
| Auto-verification | $0 | Never (disabled) |

---

## Known Limitations & Future Work

### 1. Narrative Quality Verification (Phase 2 - Not Implemented)

**Status:** ⏳ Planned for future release

**Description:**
Current verification focuses on **numerical accuracy only** (Phase 1). Phase 2 will add narrative/storytelling quality assessment:
- Logical flow across the full deck
- Meaningful insights and conclusions
- Clear narrative arc
- Data-supported claims

**Why Not Implemented Yet:**
- Phase 1 (numerical accuracy) must be validated and refined first
- Narrative quality requires different judge prompts and evaluation criteria
- Need to gather user feedback on Phase 1 effectiveness before expanding scope

**Workaround:**
Users must manually review narrative quality and storytelling coherence.

---

### 2. Genie Conversation Deep-Linking Limitation

**Status:** 🔒 External Platform Constraint

**Description:**
The "View Source Data" link currently opens the **Genie space/room** rather than the specific conversation used for slide generation.

**Technical Details:**
```python
# Current behavior (src/api/routes/verification.py:335)
genie_url = f"{workspace_url}/genie/rooms/{space_id}"
# Returns: https://<workspace>/genie/rooms/<space_id>
```

**Why:**
- Genie UI does not support deep-linking to specific conversations by conversation_id
- The conversation_id is stored in our session metadata and returned by the API
- However, no Databricks Genie URL format allows direct navigation to a conversation

**Impact:**
- Users must manually find the recent conversation in the Genie room
- Inefficient for reviewers needing quick access to source data

**Potential Solutions:**
1. **Wait for Databricks feature:** Monitor Genie API/UI for conversation deep-linking support
2. **Custom query viewer:** Build our own UI to display Genie query results (bypasses Genie UI entirely)
3. **API-based data fetch:** Use Genie SDK to fetch and display conversation data in-app (requires additional API calls)

**Current Workaround:**
- Link message: "Opens Genie room. Look for recent conversations to find queries used."
- conversation_id is returned in API response for potential future use

---

### 3. Genie Data Capture and Mapping

**Status:** ✅ Working as Designed (with clarifications)

**What We Capture:**
All Genie query results are captured **as raw CSV/data** without explicit mapping to specific slides:

```python
# Session structure
session = {
    "genie_conversation_id": "01j...",
    "genie_queries": [
        {
            "query_id": "01j...",
            "sql": "SELECT ...",
            "result_csv": "col1,col2\nval1,val2\n...",
            "row_count": 150,
            "timestamp": "2024-12-15T..."
        },
        # ... more queries
    ]
}
```

**What Verification Can Assess:**
✅ Numbers on slides match numbers in **any** Genie query result  
✅ Derived calculations (e.g., "50% growth") are correct given source data  
✅ Semantic equivalence (7M = 7,000,000 = $7.2M)  
✅ Chart data accuracy  

**What Verification Cannot Assess:**
❌ Which specific Genie query corresponds to which slide  
❌ Whether the LLM used the "right" query for a slide's topic  
❌ Data freshness (verification uses cached query results)  

**Design Rationale:**
- The LLM slide generator has full context of all Genie queries
- It chooses which data to use for each slide based on the user's conversation
- Verification checks if the slide **accurately represents** the data it chose to use
- We don't enforce a 1:1 slide→query mapping because:
  - One slide might combine data from multiple queries
  - One query might feed data to multiple slides
  - The LLM's query selection is part of the creative process

**Example:**
```
User: "Show me Q1 revenue by region, then create a trend slide"

Genie Queries:
1. Q1 revenue by region → 4 regions, $7M total
2. Revenue trend Q1-Q4 → 4 quarters

Slide 1: Regional breakdown (uses Query 1)
Slide 2: Quarterly trend (uses Query 2)
Slide 3: "Q1 represented 25% of annual revenue" (derives from both queries)

Verification:
- Slide 1: Checks regional numbers against Query 1 ✓
- Slide 2: Checks trend data against Query 2 ✓
- Slide 3: Validates "25%" calculation from Query 1 + Query 2 ✓
```

**Improvement Opportunities:**
1. **Query attribution:** Log which query(ies) the LLM used for each slide (requires LangGraph instrumentation)
2. **Explicit mapping UI:** Show users which query fed which slide
3. **Query rerun:** Allow re-running specific queries if data is stale

---
