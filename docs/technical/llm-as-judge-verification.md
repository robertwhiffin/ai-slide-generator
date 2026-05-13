# LLM as Judge Verification System

Automatic numerical accuracy verification for generated slides using MLflow's custom prompt judge, with content-hash-based persistence and human feedback collection.

---

## Stack / Entry Points

- **Backend:** MLflow 3.11+ (`make_judge` API, optional UC trace location), litellm 1.80+ (Databricks model routing), FastAPI verification routes
- **Frontend:** React auto-verification in `SlidePanel`, verification badge component, feedback UI
- **Storage:** PostgreSQL `verification_map` column (JSON keyed by content hash)
- **MLflow:** Traces logged to Databricks (default control plane or [Unity Catalog tables](mlflow-uc-tracing.md) when configured)
- **Boot files:** `src/services/evaluation/llm_judge.py` (core evaluator), `src/api/routes/verification.py` (API endpoints), `src/utils/slide_hash.py` (content hashing)
- **Environment:** Requires `DATABRICKS_HOST` and `DATABRICKS_TOKEN` for MLflow tracking
- **Databricks Apps:** Allow egress to `*.storage.cloud.databricks.com` if `mlflow.genai.evaluate` must download trace artifacts; otherwise judge may fall back (see below).
- **`TELLR_MLFLOW_LANGCHAIN_AUTOLOG`:** Set to `1` / `true` / `on` to enable `mlflow.langchain.autolog()`. **Default is off** in the agent to avoid MLflow `ContextVar` “different Context” warnings under FastAPI/async + threads ([mlflow#22088](https://github.com/mlflow/mlflow/issues/22088)).
- **Judge fallback:** If `mlflow.genai.evaluate` fails with regional **storage** connection errors, `RESOURCE_DOES_NOT_EXIST` (orphaned experiment / run), or **`'NoneType' object has no attribute 'info'`** (MLflow harness: evaluation trace never became readable—often tracing/egress related), `evaluate_with_judge` runs a **direct** `ChatDatabricks` JSON judge (same rating rules, including **unknown** when source is non-substantive). You still get a verification rating, but **no** MLflow Evaluation Run for that request (`run_id` may be null). **Default** verification backend is **MLflow**; use **Admin → Judge → Direct** when storage egress is blocked or MLflow evaluate is unreliable.
- **Admin Judge panel:** Admin → **Judge** tab chooses **MLflow LLM judge** (default) or **Direct ChatDatabricks judge**. The choice is stored as `llm_judge_backend` on the resolved `config_profiles` row (`mlflow` \| `direct`). Direct mode skips MLflow for verification entirely (no Evaluation Run; `run_id` null). API: `GET`/`PUT /api/admin/judge-backend`. If no profile row exists yet, `GET` returns `mlflow`.
- **Unable to verify (`unknown`):** The judge prompts require **unknown** (not red) when source data has no substantive ground truth (e.g. only “no results” / empty tool payloads). The verification route also short-circuits common empty-result-only tool text before calling the LLM so the UI shows **Unable to verify** instead of **Review required**.

### Genie / chat vs verification (regional storage)

**Admin → Direct** turns off MLflow for **slide verification** only. Until this change, the **agent** still called `mlflow.start_span` around each slide generation (including Genie tool calls). That path uploads trace JSON to `*.storage.cloud.databricks.com` — the same host that `mlflow.genai.evaluate` uses — so you could still see `Connection refused` / retry logs while chatting even with Direct judge.

**Current behavior:** when `llm_judge_backend` is **Direct** (default auto policy), Tellr **does not** open MLflow generate spans for `generate_slides` / `generate_slides_streaming`, so Genie/tool runs should not hit regional trace artifact URLs. Override with environment variable:

| `TELLR_MLFLOW_DISABLE_AGENT_SPANS` | Meaning |
|------------------------------------|---------|
| *(unset)* | **Auto:** spans **off** if Admin judge is Direct; spans **on** if judge is MLflow |
| `1` / `true` / `on` | Spans **always off** (even with MLflow judge) |
| `0` / `false` / `off` | Spans **always on** (even with Direct judge — restores old behavior) |

Session creation may still ensure an MLflow **experiment** exists for the user; that uses the control plane and is separate from per-trace artifact uploads. If you still see storage errors, check **LangChain autolog** (`TELLR_MLFLOW_LANGCHAIN_AUTOLOG`) and other MLflow integrations outside Tellr.

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
              evaluate_with_judge(..., judge_backend from settings)
                                   ↓
              If backend is MLflow: make_judge + genai.evaluate; if Direct: ChatDatabricks JSON only (ratings include unknown when source is insufficient)
                                   ↓
              MLflow path: make_judge creates custom prompt judge:
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
    "unknown": 0,  # Unable to verify — no substantive source / non-verifiable
}

# Rating thresholds:
# - green: ≥80% — All data correctly represents source
# - amber: 50-79% — Some concerns, review suggested
# - red: &lt;50% — Significant issues when substantive source exists (review required)
# - unknown: No substantive source data (empty tool results, no-results-only payloads, etc.)
```

| Rating | Score Range | Badge Label | User Action |
|--------|-------------|-------------|-------------|
| 🟢 Green | ≥80% | No issues | Proceed with confidence |
| 🟡 Amber | 50-79% | Review suggested | Quick review recommended |
| 🔴 Red | &lt;50% | Review required | Must review before using |
| ⚪ Unknown | N/A | Unable to verify | No substantive source data to compare |

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

Prompt text lives in `llm_judge.py` as **`JUDGE_INSTRUCTIONS`** (MLflow `make_judge`) and **`_DIRECT_JUDGE_JSON_PROMPT`** (direct JSON path). Both instruct the model to return **`unknown`** when the source has no substantive ground truth (so the UI shows “Unable to verify” instead of treating empty results as fabrication / red).

---

## Component Responsibilities

### Backend

| Path | Responsibility | APIs Touched |
|------|----------------|--------------|
| `src/core/mlflow_agent_spans.py` | When to wrap slide generation in MLflow spans (avoids regional storage when Admin judge is Direct) | `get_settings`, env `TELLR_MLFLOW_DISABLE_AGENT_SPANS` |
| `src/services/evaluation/llm_judge.py` | Core judge: MLflow `make_judge` + `genai.evaluate`, or direct `ChatDatabricks` JSON | MLflow / Databricks model serving |
| `src/api/routes/admin.py` | `GET`/`PUT /api/admin/judge-backend` — persists `llm_judge_backend` on resolved profile | `config_profiles.llm_judge_backend` |
| `src/services/evaluation/__init__.py` | Exports `evaluate_with_judge`, `LLMJudgeResult`, `RATING_SCORES` | None (module exports) |
| `src/api/routes/verification.py` | FastAPI endpoints for verification and feedback | MLflow (`log_feedback`), `SessionManager`, `evaluate_with_judge` |
| `src/utils/slide_hash.py` | HTML normalization and content hash computation | None (pure functions) |
| `src/api/services/session_manager.py` | Load/save verification_map, merge verification on get_slide_deck | Database |

### Frontend

| Path | Responsibility | Backend Touchpoints |
|------|----------------|---------------------|
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | Auto-verification trigger, parallel verify calls, state management | `api.verifySlide`, `api.getSlides` |
| `frontend/src/components/SlidePanel/VerificationBadge.tsx` | Renders rating badge, details popup, feedback UI | `api.submitVerificationFeedback` |
| `frontend/src/components/SlidePanel/SlideTile.tsx` | Hosts badge, edit detection | — |
| `frontend/src/services/api.ts` | API client methods for verification flow | `/api/verification/*` endpoints |
| `frontend/src/types/verification.ts` | TypeScript types and utility functions (badge colors, icons) | None (types only) |
| `frontend/src/components/Admin/AdminJudgeSettings.tsx` | Admin UI: MLflow vs Direct judge backend | `GET`/`PUT /api/admin/judge-backend` |

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
   - Fetch slide HTML + tool results from the session (Genie, Vector Search, MCP, etc.)
   - If there is **no** tool source text → return `rating="unknown"` (skip judge)
   - If source text matches **insufficient-data heuristics** (e.g. only “no rows” / “no images found” with no substantive metrics) → return `unknown` without calling the LLM (same UX as empty source)
   - Otherwise call `evaluate_with_judge(genie_data, slide_content, judge_backend=…)` (**MLflow** by default; **Direct** if set in Admin)
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

### Verification and Save Points

Save points use a two-phase approach to ensure both deck content integrity and verification score preservation:

1. **Backend creates save point** immediately after deck persistence (no verification yet for new edits)
2. **Frontend calls sync-verification** after auto-verification completes, backfilling scores onto the latest save point via `POST /api/slides/versions/sync-verification`

This decoupling prevents the race condition where verification timing (especially fast `unable_to_verify` in no-Genie mode) could cause save points to capture stale deck state.

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
| `GET` | `/api/admin/judge-backend` | – | `{ backend: "mlflow" \| "direct" }` | Current workspace judge mode (default `mlflow` when no profile row) |
| `PUT` | `/api/admin/judge-backend` | `{ backend: "mlflow" \| "direct" }` | `{ backend }` | Persist judge mode on resolved `config_profiles` row |
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

1. **No tool source data (title slides, no-query sessions)**
   - Backend returns `score=0`, `rating="unknown"`
   - Frontend shows gray badge: "? Unknown"
   - Not an error – expected for non-data slides

2. **Only empty / no-result tool payloads** (e.g. “No images found matching your criteria” with no metrics)
   - Backend returns `unknown` (heuristic short-circuit or judge returns `unknown`)
   - Same gray badge as no-data

3. **MLflow judge failure (network, model timeout)**
   - Backend catches exception, returns `error=true`, `error_message`
   - Frontend shows red badge: "! Error"
   - Error result not persisted

4. **Feedback submission failure**
   - If `log_feedback()` fails, error logged but request returns 200
   - Response includes `linked_to_trace: false`

### Logging & Tracing

- **Verification events:** Structured logs with session_id, slide_index, score, rating, content_hash
- **MLflow traces / Evaluation Runs:** When backend is **mlflow** (default), verifications use the per-session experiment. **Direct** mode and automatic fallback skip Evaluation Runs (`run_id` may be null).
- **Performance:** Judge latency typically 1-3 seconds

### Configuration

**Judge backend (workspace-wide)**  
- Stored on `config_profiles.llm_judge_backend` (`mlflow` \| `direct`). The Admin API resolves the row with `resolve_config_profile_for_judge_backend` (prefer `is_default`, else oldest non-deleted profile).  
- **Default:** `mlflow` — `mlflow.genai.evaluate` + Evaluation Runs (per-session experiment).  
- **Direct:** ChatDatabricks JSON judge only — use when regional storage egress to `*.storage.cloud.databricks.com` is blocked or MLflow evaluate fails; no Evaluation Run (`run_id` null). Automatic **fallback** to Direct still occurs on certain MLflow infrastructure errors even when the saved preference is MLflow.

```python
# src/services/evaluation/llm_judge.py — model endpoint name (see DEFAULT_CONFIG)
# MLflow: mlflow.set_tracking_uri("databricks") before evaluate
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

1. Update judge prompts in `src/services/evaluation/llm_judge.py` (`JUDGE_INSTRUCTIONS` for MLflow, `_DIRECT_JUDGE_JSON_PROMPT` for Direct)
2. Add new issue types to prompt
3. Update frontend `VerificationResult` interface if needed
4. Add test cases in `tests/unit/test_llm_judge_fallback.py` (and integration verification tests as needed)

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

**Last Updated:** May 11, 2026  
**Status:** ✅ Production-ready (Phase 1 – Numerical Accuracy + Auto-Verification; MLflow default + optional Direct + `unknown` for non-substantive source)
