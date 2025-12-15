# LLM as Judge Verification System

On-demand numerical accuracy verification for generated slides using MLflow's custom prompt judge, with human feedback collection for continuous improvement.

---

## Stack / Entry Points

- **Backend:** MLflow 3.6+ (`make_judge` API), litellm 1.80+ (Databricks model routing), FastAPI verification routes
- **Frontend:** React verification badge component, feedback UI with thumbs up/down
- **MLflow:** Traces logged to Databricks workspace for verification runs and human feedback
- **Boot files:** `src/services/evaluation/llm_judge.py` (core evaluator), `src/api/routes/verification.py` (API endpoints)
- **Environment:** Requires `DATABRICKS_HOST` and `DATABRICKS_TOKEN` for MLflow tracking

---

## Architecture Snapshot

```
User clicks gavel → Frontend (VerificationBadge.tsx)
                           ↓
                    POST /api/verification/{slide_index}
                           ↓
              Backend (verification.py) assembles:
                - Slide HTML + scripts (what LLM generated)
                - Genie query results (source truth)
                           ↓
              evaluate_with_judge(genie_data, slide_content)
                           ↓
              MLflow make_judge creates custom prompt judge:
                - Semantic comparison (7M = 7,000,000)
                - Derived calc validation (growth % from Q1/Q2)
                - Chart data accuracy (Chart.js arrays)
                           ↓
              Judge returns: score (0-100), rating, explanation, issues
                           ↓
              Frontend displays badge with rating + details popup
                           ↓
          User provides feedback (👍/👎 + optional rationale)
                           ↓
              POST /api/verification/{slide_index}/feedback
                           ↓
              mlflow.log_feedback(trace_id, ...) 
                → Logged as Assessment in Databricks MLflow UI
```

---

## Key Concepts / Data Contracts

### 1. Verification Result (Frontend ↔ Backend)

```typescript
// frontend/src/types/verification.ts
interface VerificationResult {
  score: number;                    // 0-100
  rating: VerificationRating;       // 'excellent' | 'good' | 'moderate' | 'poor' | 'failing' | 'error' | 'unknown'
  explanation: string;              // Human-readable assessment
  issues: Array<{                   // Specific problems found
    type: string;
    detail: string;
  }>;
  duration_ms: number;              // Verification latency
  trace_id?: string;                // MLflow trace ID for linking feedback
  genie_conversation_id?: string;   // For "View Source Data" link
  error: boolean;
  error_message?: string;
  timestamp?: string;               // ISO string
}
```

### 2. Rating Scale & Thresholds

```python
# src/services/evaluation/llm_judge.py
RATING_SCORES = {
    "excellent": 95,  # All data accurate
    "good": 80,       # Minor omissions only
    "moderate": 60,   # Some data missing
    "poor": 40,       # Errors or missing data
    "failing": 15,    # Major inaccuracies
}

# Score to rating mapping
if score >= 85: rating = "excellent"
elif score >= 70: rating = "good"
elif score >= 50: rating = "moderate"
elif score >= 30: rating = "poor"
else: rating = "failing"
```

### 3. Judge Prompt Structure

The custom prompt judge evaluates:
- **Numerical exactness:** Source `7234567` ↔ Slide `7.2M` (✓ pass)
- **Semantic equivalence:** `$7.2M`, `7,200,000`, `~7 million` all match
- **Derived calculations:** "50% growth" validated against Q1/Q2 source numbers
- **Chart data:** Chart.js `data: [7.2, 8.5, 9.1]` compared to source CSV
- **Format tolerance:** Rounding, currency symbols, percentage conversion allowed

See `src/services/evaluation/llm_judge.py::_build_judge_prompt()` for full prompt text.

---

## Component Responsibilities

### Backend

| Path | Responsibility | APIs Touched |
|------|----------------|--------------|
| `src/services/evaluation/llm_judge.py` | Core judge evaluation logic using MLflow 3.x make_judge | MLflow (`mlflow.genai.make_judge`, `mlflow.set_tracking_uri`) |
| `src/services/evaluation/__init__.py` | Exports `evaluate_with_judge`, `LLMJudgeResult`, `RATING_SCORES` | None (module exports) |
| `src/api/routes/verification.py` | FastAPI endpoints for verification and feedback | MLflow (`log_feedback`), `SessionManager`, `evaluate_with_judge` |

### Frontend

| Path | Responsibility | Backend Touchpoints |
|------|----------------|---------------------|
| `frontend/src/components/SlidePanel/VerificationBadge.tsx` | Renders gavel button, rating badge, details popup, feedback UI | `api.verifySlide`, `api.submitVerificationFeedback` |
| `frontend/src/components/SlidePanel/SlideTile.tsx` | Hosts `VerificationBadge`, manages verification state, clears on edit | Calls `onVerificationUpdate` prop to persist |
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | Persists verification to backend via `api.updateSlideVerification` | `api.updateSlideVerification` |
| `frontend/src/services/api.ts` | API client methods for verification flow | `/api/verification/{index}`, `/api/verification/{index}/feedback`, `/api/verification/genie-link` |
| `frontend/src/types/verification.ts` | TypeScript types and utility functions (badge colors, icons) | None (types only) |
| `frontend/src/components/Help/HelpPage.tsx` | Verification tab with user documentation | None (UI only) |

---

## State/Data Flow

### Verification Flow (numbered steps)

1. **User triggers verification**
   - User hovers over `SlideTile`, clicks gavel icon
   - `VerificationBadge` calls `onVerify()` → `SlideTile::handleVerify()`

2. **Frontend requests verification**
   - `api.verifySlide(sessionId, slideIndex)` → `POST /api/verification/{slide_index}`
   - Request body: `{ session_id: "abc123" }`

3. **Backend assembles inputs**
   - Fetch slide HTML + scripts from session's slide deck
   - Fetch all Genie query results from session metadata
   - If no Genie data found → return `rating="unknown"` (skip verification)

4. **Judge evaluation**
   - Call `evaluate_with_judge(genie_data, slide_content)`
   - MLflow `make_judge` creates custom prompt judge with Databricks Claude endpoint
   - Judge analyzes slide against source data, returns score + explanation
   - MLflow logs trace to Databricks workspace

5. **Backend returns result**
   - Response includes: `score`, `rating`, `explanation`, `issues`, `trace_id`, `genie_conversation_id`
   - Trace ID links verification run to MLflow for feedback association

6. **Frontend displays result**
   - Badge shows rating with color-coded indicator
   - Click badge → popup with score, explanation, issues, MLflow trace ID
   - Verification persisted via `api.updateSlideVerification` (survives refresh)

7. **User provides feedback (optional)**
   - 👍 Thumbs up → instant submission with positive feedback
   - 👎 Thumbs down → modal asks "What's wrong?" → user provides rationale
   - Feedback submitted via `api.submitVerificationFeedback(... , traceId)`

8. **Feedback logged to MLflow**
   - Backend calls `mlflow.log_feedback(trace_id, name="human_verification_feedback", ...)`
   - Logged as structured Assessment in MLflow UI under original trace
   - Includes: `value` (true/false), `rationale`, `source` (HUMAN), `metadata` (session, slide index)

9. **Slide edit triggers re-verification**
   - User edits slide HTML → `SlideTile` clears verification result
   - Badge switches back to gavel (no rating) to prompt re-verification

### Human Feedback Session (MLflow Labeling Workflow)

1. **Reviewer accesses MLflow UI**
   - Navigate to Databricks workspace → MLflow → Experiments → Traces
   - Filter traces by `name="slide_verification"` or date range

2. **Review traces with feedback**
   - Each trace shows: verification inputs, judge output, human feedback (if provided)
   - Feedback appears under "Assessments" tab in trace details

3. **Analyze feedback patterns**
   - Query traces via MLflow API: `mlflow.search_traces(filter_string="tags.user_feedback = 'negative'")`
   - Export feedback for analysis: CSV with trace_id, rating, human_feedback, rationale

4. **Improve judge prompt**
   - Identify common false positives/negatives from feedback
   - Refine judge prompt in `llm_judge.py::_build_judge_prompt()`
   - Re-run historical verifications to validate improvements

---

## Interfaces / API Table

### Backend REST API

| Method | Path | Request Body | Response | Purpose |
|--------|------|--------------|----------|---------|
| `POST` | `/api/verification/{slide_index}` | `{ session_id }` | `VerifySlideResponse` | Verify slide accuracy |
| `POST` | `/api/verification/{slide_index}/feedback` | `{ session_id, is_positive, rationale?, trace_id? }` | `{ status, message, linked_to_trace }` | Submit human feedback |
| `GET` | `/api/verification/genie-link?session_id=...` | – | `{ has_genie_conversation, conversation_id?, url?, message }` | Get Genie conversation URL |

### Frontend API Client (`api.ts`)

```typescript
// Verify slide
api.verifySlide(sessionId: string, slideIndex: number): Promise<VerificationResult>

// Submit feedback
api.submitVerificationFeedback(
  sessionId: string,
  slideIndex: number,
  isPositive: boolean,
  rationale?: string,
  traceId?: string
): Promise<{ status, message, linked_to_trace }>

// Get Genie link
api.getGenieLink(sessionId: string): Promise<{
  has_genie_conversation,
  conversation_id?,
  url?,
  message
}>

// Persist verification to session
api.updateSlideVerification(
  index: number,
  sessionId: string,
  verification: VerificationResult | null
): Promise<SlideDeck>
```

### MLflow APIs Used

```python
# Judge creation
from mlflow.genai.judges import custom_prompt_judge
from mlflow.genai.scorers import scorer

judge = custom_prompt_judge(
    name="slide_accuracy_judge",
    prompt_template=judge_prompt,
    model="databricks-claude-3-5-sonnet",
    parameters={"temperature": 0},
    scorer=scorer(target="score"),
)

# Evaluation
result = judge.score(slide_content, genie_data)

# Feedback logging
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

---

## Operational Notes

### Error Handling

1. **No Genie data (title slides, no-query sessions)**
   - Backend returns `score=0`, `rating="unknown"`, explanation indicates no source data
   - Frontend shows gray badge: "? Unknown"
   - Not considered an error – expected for non-data slides

2. **MLflow judge failure (network, model timeout)**
   - Backend catches exception, returns `error=true`, `error_message`
   - Frontend shows red badge: "! Error"
   - Error result not persisted (ephemeral)

3. **Feedback submission failure**
   - If `log_feedback()` fails (trace not found, network issue), error logged but request returns 200
   - Response includes `linked_to_trace: false` to indicate feedback wasn't linked
   - User sees success message (feedback captured in logs even if MLflow link fails)

4. **Slide edited after verification**
   - Verification cleared immediately on edit
   - Badge returns to gavel (no rating)
   - User must re-verify after changes

### Logging & Tracing

- **Verification events:** Structured logs in `src/api/routes/verification.py` with session_id, slide_index, score, rating
- **Feedback events:** Logged with trace_id, is_positive, rationale length
- **MLflow traces:** All verifications logged to Databricks with tag `feature=slide_verification`
- **Performance:** Judge latency typically 1-3 seconds (depends on Claude API)

### Configuration

```python
# src/services/evaluation/llm_judge.py
DATABRICKS_MODEL = "databricks-claude-3-5-sonnet"  # Model used for judging
JUDGE_TEMPERATURE = 0  # Deterministic judgments

# MLflow tracking URI
mlflow.set_tracking_uri("databricks")  # Logs to configured Databricks workspace
```

### Testing Hooks

- **Spike test:** `test_llm_judge_spike.py` validates judge with correct/wrong/title slide samples
- **Unit tests:** `tests/test_llm_judge_spike.py` mocks MLflow judge for fast CI
- **Manual testing:** Use Help page → Verification tab for user-facing guide

---

## Extension Guidance

### Adding New Validation Checks

**To extend the judge to check new aspects (e.g., chart labels, data freshness):**

1. Update judge prompt in `src/services/evaluation/llm_judge.py::_build_judge_prompt()`
2. Add new issue types to prompt (e.g., `"chart_labels_mismatch"`)
3. Parse new issues in `LLMJudgeResult` dataclass if needed
4. Update frontend `VerificationResult` interface to match
5. Add test cases in `test_llm_judge_spike.py`

### Changing Rating Thresholds

**To adjust score → rating mapping:**

1. Modify `RATING_SCORES` dict in `llm_judge.py`
2. Update `_score_to_rating()` function logic
3. Update frontend rating color mapping in `verification.ts::getRatingColor()`
4. Update Help page documentation (`HelpPage.tsx`)

### Custom Feedback Fields

**To capture additional feedback metadata:**

1. Add fields to `FeedbackRequest` Pydantic model in `verification.py`
2. Update frontend `api.submitVerificationFeedback()` call in `VerificationBadge.tsx`
3. Include new fields in `mlflow.log_feedback()` metadata dict
4. Query new fields via MLflow API for analysis

### Exporting Feedback for Analysis

**To bulk export feedback for model improvement:**

```python
from mlflow.tracking import MlflowClient

client = MlflowClient(tracking_uri="databricks")

# Search all verification traces with negative feedback
traces = client.search_traces(
    experiment_ids=["..."],
    filter_string='tags.user_feedback = "negative"',
    max_results=1000,
)

# Export to CSV
import pandas as pd
feedback_data = []
for trace in traces:
    assessments = trace.assessments  # Human feedback
    for a in assessments:
        feedback_data.append({
            "trace_id": trace.info.trace_id,
            "session_id": trace.tags.get("session_id"),
            "slide_index": trace.tags.get("slide_index"),
            "verification_score": trace.data["score"],
            "verification_rating": trace.data["rating"],
            "human_feedback": a.value,  # True/False
            "rationale": a.rationale,
            "timestamp": a.timestamp,
        })

df = pd.DataFrame(feedback_data)
df.to_csv("verification_feedback.csv", index=False)
```

---

## Known Limitations

### 1. Genie Conversation Deep-Linking

- **Issue:** "View Source Data" link opens Genie room/space, not specific conversation
- **Why:** Databricks Genie UI doesn't support conversation_id deep-linking
- **Workaround:** User must manually find recent conversation in Genie room
- **Potential solutions:** Wait for Databricks feature, build custom query viewer, use Genie SDK to fetch data in-app

### 2. No Slide → Query Mapping

- **Behavior:** All Genie query results passed to judge without explicit slide → query link
- **Rationale:** LLM generator has full context, chooses relevant data per slide
- **Impact:** Verification checks if slide data matches *any* query, not a specific query
- **Future:** Log which query(ies) LLM used per slide via LangGraph instrumentation

### 3. Narrative Quality Not Assessed

- **Status:** Phase 1 verifies numerical accuracy only
- **Phase 2 (future):** Add narrative quality judge for storytelling, logical flow, insight quality
- **Workaround:** Manual review for narrative coherence

---

## Cross-References

- [Frontend Overview](frontend-overview.md) – React component structure and API client
- [Backend Overview](backend-overview.md) – FastAPI routes and session management
- [LLM as Judge Plan](llm-as-judge-plan.md) – Implementation plan and detailed design decisions (user doc, supplemental)

---

**Last Updated:** 2024-12-15  
**Status:** ✅ Production-ready (Phase 1 – Numerical Accuracy)
