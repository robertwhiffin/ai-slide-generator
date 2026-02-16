# Feedback Mechanism Design

**Date:** 2026-02-13
**Status:** Draft

## Overview

Two complementary feedback features for tellr:

1. **Feedback Widget** - An always-visible chat icon (bottom-right) that opens an AI-powered feedback conversation, helping users articulate clear, structured feedback.
2. **Satisfaction Survey** - A periodic popup (at most once per 7 days) that collects star rating, time saved, and NPS score ~60 seconds after a successful slide generation.
3. **Reporting API** - Endpoints to retrieve aggregated stats and AI-generated feedback summaries without direct DB access.

## Feature A: Feedback Widget

### UX Flow

1. A floating circular icon button sits in the bottom-right corner (above the existing toast area).
2. Clicking opens an Intercom-style chat popover (~360x450px), anchored to the button.
3. The AI greets the user: *"What's on your mind? Tell me about your experience."*
4. The user describes their feedback in natural language.
5. The AI asks up to 2 clarifying questions (short, 1-2 sentences each). If the initial message is already clear, it skips straight to summary. After the 2nd question is answered, it must immediately produce the summary.
6. The AI presents a structured summary:
   - **Category:** Bug Report | Feature Request | UX Issue | Performance | Content Quality | Other
   - **Issue:** One sentence description
   - **Severity:** Low | Medium | High
   - **Details:** 2-3 sentences with specifics
7. The user sees a "Submit Feedback" button. They can click it to submit immediately, or type a correction in the text box below.
8. If user types a correction → AI revises the summary → Submit button reappears.
9. On submit → "Thank you" message → popover closes after 2 seconds.

### State Management

Local component state only. The conversation is ephemeral until submitted. No new React Context needed.

### AI System Prompt

```
You are a feedback assistant for tellr, a presentation generation tool. Your job is to help users articulate their feedback clearly.

Rules:
- Ask at most 2 clarifying questions to understand the user's feedback
- Keep your responses short (1-2 sentences per question)
- After at most 2 clarifying questions, produce a structured summary
- Present the summary in this exact format:

**Summary**
- **Category:** [Bug Report | Feature Request | UX Issue | Performance | Content Quality | Other]
- **Issue:** [One sentence description]
- **Severity:** [Low | Medium | High]
- **Details:** [2-3 sentences with specifics]

Does this look right?

- If the user sends a correction after the summary, revise it and present the updated summary
  in the same format above
- Do not ask "Does this look right?" or request confirmation - just present the summary
- If the user's initial message is already clear and specific, skip questions entirely
```

The backend detects `summary_ready` by the presence of `**Summary**` in the AI response. The frontend shows the summary as a message, with a Submit button and an optional correction text box below it.

## Feature B: Satisfaction Survey

### Trigger Logic

A `useSurveyTrigger` hook:

1. Listens for successful generation complete events (existing `onSlidesGenerated` in `AppLayout`).
2. Checks `localStorage` key `tellr_survey_last_shown`.
3. If absent or older than 7 days → starts a 60-second timer.
4. If the user starts another generation during the 60s → timer resets (don't interrupt active work).
5. After 60s → show the survey modal.
6. Immediately writes current timestamp to `tellr_survey_last_shown` (whether completed or dismissed).

### Modal Content

A centered modal with three vertically stacked sections:

**1. Star Rating** - "How would you rate tellr?" - 5 clickable star icons. Standard hover/click fill behavior.

**2. Time Saved** - "How much time has tellr saved you today?" - Single-select pill buttons: `15 min` | `30 min` | `1 hr` | `2 hrs` | `4 hrs` | `8 hrs`. Stored as integer minutes (15, 30, 60, 120, 240, 480).

**3. Recommendation (NPS)** - "How likely are you to recommend tellr to a colleague?" - Row of numbered buttons 0-10. Labels: "Not likely" (0), "Very likely" (10).

**Footer** - "Submit" button (disabled until at least star rating is filled). X close button top-right. Both submit and close count as "shown" for the 7-day cooldown.

All fields except star rating are optional - partial submissions are accepted.

## Feature C: Reporting API

### Stats Endpoint

`GET /api/feedback/report/stats?weeks=12`

Returns weekly breakdown:

- `avg_star_rating` (1-5 average)
- `avg_nps_score` (0-10 average)
- `total_time_saved_minutes` (sum, with `time_saved_display` as human-readable)
- `responses` (count per week)
- `totals` object with overall aggregates

Implementation: SQL aggregation with `DATE_TRUNC('week', created_at)`, `AVG()`, `SUM()`, `COUNT()`.

### AI Summary Endpoint

`GET /api/feedback/report/summary?weeks=4`

Returns:

- `summary` - AI-generated narrative covering top themes, common categories, severity distribution, and recommendations
- `category_breakdown` - count per category
- `top_themes` - extracted key themes (list of strings)
- `feedback_count` and `period`

Implementation: Queries all `feedback_conversations` summaries for the period, passes to the LLM with a report-generation prompt. No caching - regenerates on every call.

## Backend Design

### New Router: `/api/feedback/`

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/feedback/chat` | Send message in feedback conversation, returns AI response |
| `POST` | `/api/feedback/submit` | Submit confirmed feedback (raw conversation + summary) |
| `POST` | `/api/feedback/survey` | Submit survey responses |
| `GET` | `/api/feedback/report/stats` | Weekly aggregated stats |
| `GET` | `/api/feedback/report/summary` | AI-generated feedback narrative |

### `/api/feedback/chat`

**Request:** `{ "messages": [{"role": "user", "content": "..."}, ...] }`

Stateless - frontend sends full conversation history each call. Backend prepends system prompt and calls the LLM.

**Response:** `{ "content": "AI response text", "summary_ready": true/false }`

### LLM Configuration

- Environment variable: `FEEDBACK_LLM_ENDPOINT`
- Falls back to the active profile's `llm_endpoint` if not set
- Hardcoded defaults: temperature=0.3, max_tokens=500 (short, focused responses)
- Recommendation: point at a fast, cheap model (e.g. Haiku-class) for sub-second feedback chat responses

### Database Tables

**`feedback_conversations`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `category` | VARCHAR | Bug Report, Feature Request, UX Issue, Performance, Content Quality, Other |
| `summary` | TEXT | AI-generated summary the user confirmed |
| `severity` | VARCHAR | Low, Medium, High |
| `raw_conversation` | JSONB | Full message array |
| `created_at` | TIMESTAMP | |

**`survey_responses`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `star_rating` | INTEGER | 1-5, required |
| `time_saved_minutes` | INTEGER | 15/30/60/120/240/480, nullable |
| `nps_score` | INTEGER | 0-10, nullable |
| `created_at` | TIMESTAMP | |

Both tables are anonymous - no user identity columns.

## Frontend Components

### New Files

| File | Purpose |
|------|---------|
| `frontend/src/components/Feedback/FeedbackButton.tsx` | Floating icon button (fixed bottom-right) |
| `frontend/src/components/Feedback/FeedbackPopover.tsx` | Intercom-style chat popover |
| `frontend/src/components/Feedback/SurveyModal.tsx` | Satisfaction survey modal |
| `frontend/src/components/Feedback/StarRating.tsx` | 5-star rating component |
| `frontend/src/components/Feedback/NPSScale.tsx` | 0-10 button row |
| `frontend/src/components/Feedback/TimeSavedPills.tsx` | Time-saved pill buttons |
| `frontend/src/hooks/useSurveyTrigger.ts` | 60s timer + localStorage cooldown logic |

### Modified Files

| File | Change |
|------|--------|
| `frontend/src/services/api.ts` | Add `feedbackChat()`, `submitFeedback()`, `submitSurvey()` methods |
| `frontend/src/components/Layout/AppLayout.tsx` | Mount `FeedbackButton` and wire `useSurveyTrigger` to `onSlidesGenerated` |

### Backend New Files

| File | Purpose |
|------|---------|
| `src/api/routes/feedback.py` | Router with 5 endpoints |
| `src/api/services/feedback_service.py` | LLM calls, summary parsing, stats aggregation |
| `src/database/models/feedback.py` | `FeedbackConversation` and `SurveyResponse` models |
| `src/api/schemas/feedback.py` | Pydantic request/response schemas |
| Alembic migration | Create `feedback_conversations` and `survey_responses` tables |

### Backend Modified Files

| File | Change |
|------|--------|
| `src/api/main.py` | Register the new feedback router |
| `src/database/models/__init__.py` | Export new models |

## Tests

| File | Covers |
|------|--------|
| `tests/unit/test_feedback_service.py` | LLM call mocking, summary parsing, stats aggregation |
| `tests/unit/test_feedback_routes.py` | Endpoint request/response validation |
| `frontend/tests/feedback-widget.spec.ts` | Popover open/close, message flow, submit |
| `frontend/tests/survey-modal.spec.ts` | Trigger timing, localStorage cooldown, form submission |

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Simple LLM call (no LangChain agent) | Feedback chat doesn't need tools - lightweight and fast |
| Separate `FEEDBACK_LLM_ENDPOINT` env var | Decouple from the main slide generation model; use a faster/cheaper model |
| localStorage for survey cooldown | Simplest option; no user auth in the system to track server-side |
| Anonymous feedback | Low friction; no user identity system exists |
| `**Summary**` marker detection | Detects when AI produces structured summary; no sentinel token needed |
| No report caching | Low traffic admin endpoint; always-fresh data worth the LLM cost |
| Preset feedback categories | Structured enough for aggregation; flexible enough to cover most cases |
