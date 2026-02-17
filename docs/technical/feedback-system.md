# Feedback & Satisfaction Survey System

AI-powered feedback collection widget and periodic satisfaction survey with reporting API, designed to capture structured user feedback and quantify productivity savings.

---

## Stack / Entry Points

- **Backend:** FastAPI router (`src/api/routes/feedback.py`), feedback service (`src/api/services/feedback_service.py`), SQLAlchemy models (`src/database/models/feedback.py`)
- **Frontend:** React components in `frontend/src/components/Feedback/`, survey trigger hook (`frontend/src/hooks/useSurveyTrigger.ts`)
- **LLM:** `ChatDatabricks` via `databricks_langchain` — defaults to `databricks-gpt-oss-20b`, overridable with `FEEDBACK_LLM_ENDPOINT` env var
- **Storage:** PostgreSQL tables `feedback_conversations` and `survey_responses`
- **Schemas:** `src/api/schemas/feedback.py` (Pydantic request/response validation)

---

## Architecture Snapshot

```
┌─────────────────────────────────────────────────────────────────┐
│ Frontend (AppLayout.tsx)                                        │
│                                                                 │
│  FeedbackButton ──► FeedbackPopover (chat with AI)              │
│       │                    │                                    │
│       │           POST /api/feedback/chat  (stateless, full     │
│       │                history sent each call)                  │
│       │                    │                                    │
│       │           POST /api/feedback/submit (confirmed summary) │
│       │                                                         │
│  useSurveyTrigger ──► SurveyModal (stars + time + NPS)          │
│       │                    │                                    │
│       │           POST /api/feedback/survey                     │
│                                                                 │
│  Admin / reporting:                                             │
│       GET /api/feedback/report/stats    (SQL aggregation)       │
│       GET /api/feedback/report/summary  (LLM-generated)         │
└─────────────────────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
   FeedbackService          PostgreSQL
   (LLM chat + DB ops)      feedback_conversations
                             survey_responses
```

---

## Key Concepts / Data Contracts

### Feedback Chat (Request / Response)

```json
// POST /api/feedback/chat
// Request
{ "messages": [{ "role": "user", "content": "The text is hard to read" }] }

// Response
{ "content": "Can you tell me which slide styles are affected?", "summary_ready": false }
```

The frontend sends the full conversation history each call (stateless on the server). When the AI produces a structured `**Summary**` block, `summary_ready` becomes `true`.

### Feedback Submit

```json
// POST /api/feedback/submit
{
  "category": "Bug Report",
  "summary": "Text unreadable on dark backgrounds",
  "severity": "High",
  "raw_conversation": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

### Survey Submit

```json
// POST /api/feedback/survey
{
  "star_rating": 4,
  "time_saved_minutes": 120,
  "nps_score": 8
}
```

`star_rating` is required (1-5). `time_saved_minutes` (15/30/60/120/240/480) and `nps_score` (0-10) are optional.

### Feedback Categories & Severities

| Categories | Severities |
|------------|------------|
| Bug Report, Feature Request, UX Issue, Performance, Content Quality, Other | Low, Medium, High |

---

## Component Responsibilities

### Backend

| File | Responsibility |
|------|----------------|
| `src/api/routes/feedback.py` | 5 endpoints: chat, submit, survey, report/stats, report/summary |
| `src/api/services/feedback_service.py` | LLM chat, DB persistence, stats aggregation, AI summary generation |
| `src/api/schemas/feedback.py` | Pydantic validation for all request/response types |
| `src/database/models/feedback.py` | `FeedbackConversation` and `SurveyResponse` SQLAlchemy models |

### Frontend

| File | Responsibility |
|------|----------------|
| `frontend/src/components/Feedback/FeedbackButton.tsx` | Floating icon button (fixed bottom-right, z-60) |
| `frontend/src/components/Feedback/FeedbackPopover.tsx` | Chat UI: messages, input, summary detection, submit/correction flow |
| `frontend/src/components/Feedback/SurveyModal.tsx` | Star rating + time saved + NPS modal |
| `frontend/src/components/Feedback/StarRating.tsx` | 5-star interactive rating |
| `frontend/src/components/Feedback/NPSScale.tsx` | 0-10 numbered button row |
| `frontend/src/components/Feedback/TimeSavedPills.tsx` | Pill buttons: 15min, 30min, 1hr, 2hrs, 4hrs, 8hrs |
| `frontend/src/components/Feedback/FeedbackDashboard.tsx` | Hidden `/feedback` page — stats table, totals, AI summary (no nav link) |
| `frontend/src/hooks/useSurveyTrigger.ts` | 30s post-generation timer with 7-day localStorage cooldown |
| `frontend/src/services/api.ts` | `feedbackChat()`, `submitFeedback()`, `submitSurvey()`, `getReportStats()`, `getReportSummary()` |

---

## Data Flow

### Feedback Widget Flow

1. User clicks the floating feedback button (bottom-right corner).
2. `FeedbackPopover` opens with a greeting message.
3. User types feedback. Frontend sends full conversation to `POST /api/feedback/chat`.
4. Backend prepends the system prompt and calls `ChatDatabricks` (default: `databricks-gpt-oss-20b`).
5. AI asks up to 2 clarifying questions, then produces a structured `**Summary**` block.
6. Frontend detects `summary_ready: true` and displays a "Submit Feedback" button with an optional correction text box.
7. User clicks Submit → `POST /api/feedback/submit` stores the summary + raw conversation in `feedback_conversations`.
8. "Thank you" message → popover closes after 2 seconds.

### Survey Flow

1. User generates a presentation successfully.
2. `useSurveyTrigger` checks `localStorage` key `tellr_survey_last_shown`.
3. If eligible (no survey in last 7 days), starts a 30-second timer.
4. If the user starts another generation during the 30s, the timer resets.
5. After 30s idle → survey modal appears; timestamp written to `localStorage` immediately.
6. User fills in star rating (required), time saved, and NPS (optional), then clicks Submit.
7. `POST /api/feedback/survey` stores the response in `survey_responses`.
8. Dismissing (X button) without submitting still counts as "shown" for the 7-day cooldown.

### Feedback Dashboard (Hidden Page)

The `/feedback` route renders a read-only dashboard that displays the reporting API data. It is **not linked** from the navigation bar — access it by typing the URL directly (e.g. `https://<host>/feedback`).

The page shows:
- **Summary cards** — overall average star rating, NPS, total time saved, total responses.
- **Weekly stats table** — one row per week with response count, avg stars, avg NPS, and time saved.
- **AI-generated summary** — narrative analysis of feedback themes, category breakdown, and top themes.

Both the stats and summary sections have a configurable week-range selector.

---

## API Table

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/feedback/chat` | Send feedback conversation message, get AI response |
| `POST` | `/api/feedback/submit` | Submit confirmed feedback (summary + raw conversation) |
| `POST` | `/api/feedback/survey` | Submit satisfaction survey response |
| `GET` | `/api/feedback/report/stats?weeks=12` | Weekly aggregated stats (star avg, NPS avg, time saved sum) |
| `GET` | `/api/feedback/report/summary?weeks=4` | AI-generated narrative summary of feedback themes |

---

## Database Tables

### `feedback_conversations`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER (PK) | Auto-increment |
| `category` | VARCHAR(50) | One of 6 preset categories |
| `summary` | TEXT | AI-generated summary |
| `severity` | VARCHAR(10) | Low / Medium / High |
| `raw_conversation` | JSON | Full message array |
| `created_at` | TIMESTAMP | Default: `utcnow()` |

### `survey_responses`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER (PK) | Auto-increment |
| `star_rating` | INTEGER | 1-5, required |
| `time_saved_minutes` | INTEGER | 15/30/60/120/240/480 or NULL |
| `nps_score` | INTEGER | 0-10 or NULL |
| `created_at` | TIMESTAMP | Default: `utcnow()` |

Both tables are anonymous — no user identity columns.

---

## Operational Notes

### LLM Configuration

The feedback chat uses a separate LLM endpoint from slide generation to keep responses fast:

| Setting | Value |
|---------|-------|
| Default endpoint | `databricks-gpt-oss-20b` |
| Override | `FEEDBACK_LLM_ENDPOINT` env var |
| Temperature | 0.3 (chat), 0.2 (report summary) |
| Max tokens | 500 (chat), 800 (report summary) |

### Summary Detection

The backend detects when the AI has produced a summary by checking for the `**Summary**` marker in the response content. This avoids special sentinel tokens — the AI's structured output is both the detection mechanism and the displayed content.

### Error Handling

- LLM endpoint not configured → 503 Service Unavailable
- LLM call fails → 500 with logged error
- Invalid request payload → 422 Validation Error (Pydantic)
- Survey/feedback DB write fails → 500 with logged error

### Testing

| Test file | Coverage |
|-----------|----------|
| `tests/unit/test_feedback_models.py` | Model creation, constraints (10 tests) |
| `tests/unit/test_feedback_schemas.py` | Pydantic validation (14 tests) |
| `tests/unit/test_feedback_service.py` | LLM mocking, DB ops, stats, summaries (10 tests) |
| `tests/unit/test_feedback_routes.py` | Endpoint request/response (6 tests) |

---

## Extension Guidance

- **Add a feedback category:** Update `FEEDBACK_CATEGORIES` in `src/api/schemas/feedback.py` and the `CheckConstraint` in `src/database/models/feedback.py`. The system prompt in `feedback_service.py` also lists categories.
- **Change time-saved options:** Update `TIME_OPTIONS` in `TimeSavedPills.tsx`, `ALLOWED_TIME_SAVED` in `src/api/schemas/feedback.py`, and the `CheckConstraint` in the model.
- **Add user identity:** Add a `user_id` or `email` column to both tables, pass from frontend (would need an auth system first).
- **Export feedback data:** The `/api/feedback/report/stats` endpoint returns JSON suitable for dashboards. For raw export, query the tables directly or add a CSV export endpoint.
- **Adjust survey timing:** Change `DELAY_MS` (post-generation wait) and `COOLDOWN_MS` (minimum between surveys) in `frontend/src/hooks/useSurveyTrigger.ts`.

---

## Cross-References

- [Backend Overview](./backend-overview.md) — FastAPI router registration, service patterns
- [Frontend Overview](./frontend-overview.md) — React context providers, component layout
- [Real-Time Streaming](./real-time-streaming.md) — How `onSlidesGenerated` callback works (survey trigger hook)
- [Database Configuration](./database-configuration.md) — PostgreSQL setup, `Base.metadata.create_all()`
