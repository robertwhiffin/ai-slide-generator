# LLM as Judge Verification System

Automatic numerical accuracy verification for generated slides using MLflow's custom prompt judge, with content-hash-based persistence and human feedback collection.

---

## Stack / Entry Points

- **Backend:** MLflow 3.6+ (`make_judge` API), litellm 1.80+ (Databricks model routing), FastAPI verification routes
- **Frontend:** React auto-verification in `SlidePanel`, verification badge component, feedback UI
- **Storage:** PostgreSQL `verification_map` column (JSON keyed by content hash)
- **MLflow:** Traces logged to Databricks workspace for verification runs and human feedback
- **Boot files:** `src/services/evaluation/llm_judge.py` (core evaluator), `src/api/routes/verification.py` (API endpoints), `src/utils/slide_hash.py` (content hashing)
- **Environment:** Requires `DATABRICKS_HOST` and `DATABRICKS_TOKEN` for MLflow tracking

---

## Architecture Snapshot

```
Slides generated/modified → Frontend (SlidePanel.tsx)
                                   ↓
                    Auto-verify slides without verification
                    (parallel API calls for each unverified slide)
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
              Backend saves to verification_map[content_hash]
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
  score: number;                    // 0-100 (internal use)
  rating: VerificationRating;       // 'green' | 'amber' | 'red' | 'error' | 'unknown'
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
  content_hash?: string;            // Hash of slide content (for persistence)
}
```

### 2. Rating Scale & Thresholds (RAG System)

The verification uses a simple RAG (Red/Amber/Green) indicator system:

```python
# src/services/evaluation/llm_judge.py
RATING_SCORES = {
    "green": 85,   # No issues detected (≥80%)
    "amber": 65,   # Review suggested (50-79%)
    "red": 25,     # Review required (&lt;50%)
}

# Rating thresholds:
# - green: ≥80% — All data correctly represents source
# - amber: 50-79% — Some concerns, review suggested
# - red: &lt;50% — Significant issues, review required
# - unknown: No source data available (title slides, etc.)
```

| Rating | Score Range | Badge Label | User Action |
|--------|-------------|-------------|-------------|
| 🟢 Green | ≥80% | No issues | Proceed with confidence |
| 🟡 Amber | 50-79% | Review suggested | Quick review recommended |
| 🔴 Red | &lt;50% | Review required | Must review before using |
| ⚪ Unknown | N/A | Unable to verify | No source data available |

### 3. Content Hash Persistence

Verification results persist separately from slide content using content-hash-based storage:

```python
# Database schema
class SessionSlideDeck(Base):
    deck_json = Column(Text)           # Slides (html, scripts, css) - NO verification
    verification_map = Column(Text)    # JSON: {"content_hash": VerificationResult}

# Hash computation (src/utils/slide_hash.py)
def compute_slide_hash(html: str) -> str:
    normalized = normalize_html(html)  # Strip whitespace, comments, lowercase
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]
```

**Why content hash?** Decouples verification from slide regeneration. When chat modifies slides, `deck_json` is overwritten but `verification_map` is preserved. On load, verification is merged back by matching content hashes.

### 4. Judge Prompt Structure

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
| `src/utils/slide_hash.py` | HTML normalization and content hash computation | None (pure functions) |
| `src/api/services/session_manager.py` | Load/save verification_map, merge verification on get_slide_deck | Database |

### Frontend

| Path | Responsibility | Backend Touchpoints |
|------|----------------|---------------------|
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | Auto-verification trigger, parallel verify calls, state management | `api.verifySlide`, `api.getSlides` |
| `frontend/src/components/SlidePanel/VerificationBadge.tsx` | Renders rating badge, details popup, feedback UI | `api.submitVerificationFeedback` |
| `frontend/src/components/SlidePanel/SlideTile.tsx` | Hosts badge, Genie source data button, edit detection | `api.getGenieLink` |
| `frontend/src/services/api.ts` | API client methods for verification flow | `/api/verification/*` endpoints |
| `frontend/src/types/verification.ts` | TypeScript types and utility functions (badge colors, icons) | None (types only) |
| `frontend/src/components/Help/HelpPage.tsx` | Verification tab with user documentation | None (UI only) |

---

## State/Data Flow

### Auto-Verification Flow

1. **Slides generated or modified**
   - Chat completes → frontend fetches slides via `api.getSlides()`
   - Backend returns slides with `content_hash` computed for each

2. **Frontend triggers auto-verification**
   - `SlidePanel` effect detects slides without verification
   - Filters out already-attempted hashes (prevents re-triggering)
   - Calls `runAutoVerification()` for unverified slides in parallel

3. **Backend verifies each slide**
   - Fetch slide HTML + Genie query results
   - If no Genie data → return `rating="unknown"` (skip verification)
   - Call `evaluate_with_judge(genie_data, slide_content)`
   - Save result to `verification_map[content_hash]`

4. **Frontend displays results**
   - Refresh slides to get merged verification
   - Badges appear on each slide with color-coded rating

### Verification Persistence Behavior

| Action | Verification Behavior |
|--------|----------------------|
| Generate new slides | All slides auto-verified (no hash match) |
| Edit a slide | Only edited slide re-verified (hash changed) |
| Add slides via chat | Existing slides keep verification, new slides auto-verified |
| Delete a slide | Other slides keep verification (different hashes) |
| Reorder slides | All slides keep verification (position-independent) |
| Restore session | Verification merged back by hash match |

### Human Feedback Flow

1. User clicks verification badge → popup shows details
2. User provides feedback via 👍/👎 buttons
3. 👎 opens rationale input → user explains issue
4. Frontend calls `api.submitVerificationFeedback(... , traceId)`
5. Backend logs to MLflow as structured Assessment
6. Feedback visible in MLflow UI under original trace

---

## Interfaces / API Table

### Backend REST API

| Method | Path | Request Body | Response | Purpose |
|--------|------|--------------|----------|---------|
| `POST` | `/api/verification/{slide_index}` | `{ session_id }` | `VerifySlideResponse` | Verify slide accuracy |
| `POST` | `/api/verification/{slide_index}/feedback` | `{ session_id, is_positive, rationale?, trace_id? }` | `{ status, message, linked_to_trace }` | Submit human feedback |
| `GET` | `/api/verification/genie-link?session_id=...` | – | `{ has_genie_conversation, url?, message }` | Get Genie conversation URL |

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
  url?,
  message
}>
```

### MLflow APIs Used

```python
# Feedback logging
mlflow.set_tracking_uri("databricks")
mlflow.log_feedback(
    trace_id=trace_id,
    name="human_verification_feedback",
    value=is_positive,
    rationale=user_comment,
    source=AssessmentSource(
        source_type=AssessmentSourceType.HUMAN,
        source_id=f"session_{session_id[:8]}"
    ),
    metadata={"session_id": session_id, "slide_index": slide_index}
)
```

---

## Operational Notes

### Error Handling

1. **No Genie data (title slides, no-query sessions)**
   - Backend returns `score=0`, `rating="unknown"`
   - Frontend shows gray badge: "? Unknown"
   - Not an error – expected for non-data slides

2. **MLflow judge failure (network, model timeout)**
   - Backend catches exception, returns `error=true`, `error_message`
   - Frontend shows red badge: "! Error"
   - Error result not persisted

3. **Feedback submission failure**
   - If `log_feedback()` fails, error logged but request returns 200
   - Response includes `linked_to_trace: false`

### Logging & Tracing

- **Verification events:** Structured logs with session_id, slide_index, score, rating, content_hash
- **MLflow traces:** All verifications logged to Databricks
- **Performance:** Judge latency typically 1-3 seconds

### Configuration

```python
# src/services/evaluation/llm_judge.py
DATABRICKS_MODEL = "databricks-claude-3-5-sonnet"
JUDGE_TEMPERATURE = 0  # Deterministic judgments

# MLflow tracking
mlflow.set_tracking_uri("databricks")
```

### Database Migration

If upgrading from a version without `verification_map`:

```sql
ALTER TABLE session_slide_decks ADD COLUMN verification_map TEXT;
```

Backward compatible – NULL treated as empty dict `{}`.

---

## Extension Guidance

### Adding New Validation Checks

1. Update judge prompt in `src/services/evaluation/llm_judge.py::_build_judge_prompt()`
2. Add new issue types to prompt
3. Update frontend `VerificationResult` interface if needed
4. Add test cases in `test_llm_judge_spike.py`

### Changing Rating Thresholds

The RAG system uses these thresholds:
- **Green**: ≥80% (judge returns "green")
- **Amber**: 50-79% (judge returns "amber")  
- **Red**: &lt;50% (judge returns "red")

To modify:
1. Update `RATING_SCORES` dict in `llm_judge.py`
2. Update judge prompt instructions in `JUDGE_INSTRUCTIONS`
3. Update frontend `verification.ts::getRatingColor()` and related functions
4. Update Help page documentation in `HelpPage.tsx`

### Custom Feedback Fields

1. Add fields to `FeedbackRequest` Pydantic model
2. Update frontend `api.submitVerificationFeedback()` call
3. Include new fields in `mlflow.log_feedback()` metadata

---

## Known Limitations

### 1. No Slide → Query Mapping

The LLM as Judge verifies each slide against **all** Genie query results from the session, not the specific query that generated that slide.

**Why:** The agent makes multiple queries during slide generation but doesn't tag which query's data goes to which slide.

**Practical impact:** Verification still works correctly—the judge finds matching data. However, it cannot tell you *which* query produced a specific slide's content.

**Future consideration:** Log query attribution per slide during generation.

### 2. Narrative Quality Not Assessed (Future Consideration)

- Phase 1 verifies numerical accuracy only
- Nice to have: Add narrative coherence scoring for story flow and logical structure

---

## Cross-References

- [Frontend Overview](frontend-overview.md) – React component structure
- [Backend Overview](backend-overview.md) – FastAPI routes and session management
- [Database Configuration](database-configuration.md) – Schema details including verification_map

---

**Last Updated:** 2024-12-16  
**Status:** ✅ Production-ready (Phase 1 – Numerical Accuracy + Auto-Verification)
