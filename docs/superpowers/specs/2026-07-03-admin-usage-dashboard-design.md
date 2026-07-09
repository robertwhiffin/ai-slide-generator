# Admin Usage Dashboard — Design

**Date:** 2026-07-03
**Status:** Approved (brainstormed with Robert; decisions recorded below)

## Motivation

The `/admin` page today shows only feedback-survey aggregates plus two usage counts
(distinct users, total sessions) bolted onto the feedback stats endpoint. Robert wants a
detailed view of historic usage: **who is using Tellr, how are they using it, and what
are their issues with it.** The current numbers also disagree with raw table counts
because the dashboard's rolling-window `COUNT(DISTINCT created_by)` on `user_sessions`
measures something different from `COUNT(*)` on identity tables.

### Data reality (verified)

- `user_sessions` is **durable history** — the TTL cleanup (`cleanup_expired_sessions`)
  is only reachable via the manual `POST /api/sessions/cleanup` endpoint; nothing
  schedules it. One row per editing session, with `created_by` + `created_at` +
  `last_activity`.
- `session_slide_decks` is durable, one row per deck (1:1 with session), `created_at` =
  first generation.
- **No login-event log exists.** Identity is resolved per request from Databricks Apps
  forwarded headers (middleware in `src/api/main.py` + `src/api/mcp_auth.py`) and held
  in a ContextVar. `app_identities` keeps one row per user with `first_seen_at`/
  `last_seen_at` (overwritten), so per-day login history is not reconstructable.
- `request_logs` records every `/api/*` request (anonymous: method, route template,
  status, duration) and is pruned at 30 days. Usable only for a rough, unattributed
  deck-retrieval volume over the last 30 days.
- `feedback_conversations` and `survey_responses` are **anonymous by design** (no user
  columns) and durable.

## Decisions (agreed)

1. **Login metrics = both**: use session-based history from `user_sessions` as the
   pre-ship proxy, AND add a durable `usage_events` log going forward for literal
   login/retrieval semantics.
2. **Lean event set**: `login`, `deck_created`, `deck_retrieved`. No edit/export/share
   events.
3. **Feedback stays anonymous.** Revamp = raw feedback browser (option 1). No
   attribution, no per-response survey drill-down.
4. **No access control** on `/admin` (hidden URL only), unchanged.
5. **On-the-fly SQL aggregation** (no rollup tables/jobs) — small data.
6. **Extras included**: new-vs-returning split, avg decks per active user, retention
   snapshot, day×hour activity heatmap, login→deck funnel. **Excluded:** CSV export.

## New table: `usage_events`

```python
class UsageEvent(Base):
    __tablename__ = "usage_events"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    event_type = Column(String(30), nullable=False)   # 'login' | 'deck_created' | 'deck_retrieved'
    session_id = Column(Integer, nullable=True)        # user_sessions.id when applicable; NOT a FK
    ts = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_usage_events_type_ts", "event_type", "ts"),
        Index("ix_usage_events_username_ts", "username", "ts"),
    )
```

`session_id` is deliberately **not** a foreign key: events must survive session
deletion (that is the point of the table).

### Event capture semantics

All writes are **fire-and-forget** (same pattern as `request_logs` middleware:
`loop.run_in_executor`, exceptions swallowed and logged at debug). Event writing must
never block or fail a user request.

| Event | Write site | Semantics / dedup |
|---|---|---|
| `login` | Identity middleware in `src/api/main.py`, alongside the existing `record_user_login` call | One event per "visit": first authenticated request from a username after **≥30 minutes** without one, tracked in an in-process `{username: last_seen_monotonic}` cache. Process restart resets the cache (occasional extra login events are acceptable). |
| `deck_created` | `session_manager.py` where `SessionSlideDeck(` is instantiated (~line 680) | One per deck creation; no dedup needed. |
| `deck_retrieved` | `GET /api/sessions/{session_id}` route (deck open) | Deduped per `(username, session_id)` with the same in-process 30-minute window, so repeated polling within a visit counts once. |

A single helper module (e.g. `src/api/services/usage_events.py`) owns the dedup caches
and the non-blocking write, and is imported by the middleware and session manager.

**Guard note:** `POST /api/sessions/cleanup` would destroy `user_sessions` history if
ever wired to a scheduler. It stays as-is, but the spec records: **do not schedule it**;
implementation adds a docstring warning on the endpoint.

## Backend API

New router `src/api/routes/admin_usage.py` mounted at `/api/admin/usage`, backed by a
new `src/api/services/usage_service.py` (all aggregation SQL). No auth guards
(decision 4). All windowed endpoints accept `?days=` in {7, 14, 21, 28}, default 7.
Day bucketing is UTC calendar days.

| Endpoint | Returns |
|---|---|
| `GET /api/admin/usage/summary` | `{ total_users_ever, total_decks_ever, window: { days, active_users, decks_created, avg_decks_per_active_user, logins } }` |
| `GET /api/admin/usage/daily?days=N` | Per-day arrays: `{ date, logins, distinct_users, new_users, returning_users, decks_created, decks_retrieved }` plus `history_boundary` (ISO date of first `usage_events` login row, or null) |
| `GET /api/admin/usage/top-users?days=N` | `[ { username, logins, sessions_created, decks_created } ]` top 20 |
| `GET /api/admin/usage/funnel?days=N` | `{ logins, users_who_logged_in, users_who_created_deck, decks_created }` |
| `GET /api/admin/usage/retention` | Last ~8 ISO weeks: `[ { week_start, active_users, retained_from_prev, retention_pct } ]` |
| `GET /api/admin/usage/heatmap?days=N` | 7×24 matrix of activity event counts (logins + deck events) |

### Metric definitions

- **Total users ever** = `COUNT(DISTINCT identity_name) FROM app_identities WHERE identity_type='USER'`,
  unioned with `DISTINCT created_by FROM user_sessions` (belt-and-braces; dedup by name).
  This resolves the "dashboard vs count(*)" discrepancy by counting identities, not
  windowed session creators.
- **Total decks ever** = `COUNT(*) FROM session_slide_decks` **plus** count of
  `deck_created` usage-events whose `session_id` no longer exists in
  `session_slide_decks` (so history survives any future deletion). Forward-safe.
- **Daily logins**: from `usage_events` where available. For days **before** the first
  login event (`history_boundary`), fall back to sessions-created-per-day from
  `user_sessions` as a labeled proxy.
- **Daily distinct users**: `DISTINCT username` per day from `usage_events` (any type);
  pre-boundary fallback: `DISTINCT created_by` per day from `user_sessions.created_at`.
- **New vs returning**: a user is *new* on day D if D is their first-ever appearance
  (min over `usage_events.ts` and `user_sessions.created_at` and
  `app_identities.first_seen_at`); otherwise returning.
- **Active user (window)**: appears in `usage_events` in window, OR has a session with
  `created_at` or `last_activity` in window.
- **Top users by logins**: `login` events grouped by username; pre-boundary windows fall
  back to sessions created. The table also shows sessions_created and decks_created per
  user for context.
- **Retention snapshot**: for each ISO week, `retained_from_prev` = users active in both
  week W-1 and W; `retention_pct = retained / active(W-1)`.
- **Deck retrievals backfill**: current-window retrieval counts come from `usage_events`;
  additionally the daily endpoint may include anonymous volume from `request_logs`
  (`GET /api/sessions/{session_id}` route template, status < 400) for pre-boundary days
  within the last 30 days, clearly flagged as `retrievals_proxy`.

### History boundary

Charts render real event data from `history_boundary` onward and proxy data before it.
The API returns the boundary; the UI renders a subtle marker/annotation ("event
tracking enabled") and legends distinguish proxy vs real series. Decks-per-day and
session-based series have true history throughout and need no marker.

## Feedback tab revamp

`GET /api/feedback/list?weeks=N&category=&severity=&page=&page_size=` (new endpoint in
existing feedback router/service): paginated `feedback_conversations` rows — `id`,
`created_at`, `category`, `severity`, `summary`, `raw_conversation`. Anonymous; no user
data exists or is added.

UI (`FeedbackDashboard.tsx` rework):

- **Headline: raw feedback browser** — table of date / category / severity / summary,
  expandable row revealing the full raw conversation (chat transcript rendering),
  filters for category and severity, newest first, paginated.
- Survey stat cards and weekly table remain as today.
- The **LLM theme summary is demoted** to a collapsed "AI summary" section at the
  bottom, loaded **only on expand** (stops the expensive LLM call on every page load).

## Frontend

- **New tab "Usage"** (default tab) in `frontend/src/components/Admin/AdminPage.tsx`;
  component `frontend/src/components/Admin/UsageDashboard.tsx`.
- **Charts: `recharts`** (new dependency) — line/bar for daily series, simple
  table-based heatmap (colored cells), stat cards reusing the existing card styles from
  `FeedbackDashboard`.
- Window selector (7/14/21/28 days) shared across the Usage tab; single state, all
  widgets refetch.
- New API client methods in `frontend/src/services/api.ts` with typed responses.

Layout (top to bottom): stat cards row → daily logins chart → daily distinct users
(new/returning stacked) → decks per day → funnel + avg-decks card → top users table →
retention table → heatmap.

## Testing

- **Unit (backend):** seeded-event fixtures → expected buckets for every aggregation
  (daily, new-vs-returning, funnel, retention, heatmap, totals incl. deleted-session
  deck counting); login/retrieval dedup-window behaviour; event writer never raises;
  feedback list pagination + filters.
- **Route tests:** response shapes for all new endpoints (following
  `tests/unit/test_feedback_routes.py` patterns).
- **Frontend:** existing test conventions; render tests for UsageDashboard with mocked
  API; feedback browser expand/filter behaviour.
- **E2E/manual:** deploy to devtest on a prod Lakebase branch, verify `/admin` renders
  both tabs against real data.

## Non-goals

- No access control on `/admin`.
- No CSV export.
- No feedback attribution or per-response survey drill-down.
- No pre-aggregation/rollup jobs.
- No backfill fabrication: pre-boundary login metrics are labeled proxies, not
  synthesized "logins".

## Migration

`usage_events` is a brand-new table, so the existing `Base.metadata.create_all()`
startup path creates it automatically (registered via `src/database/models/__init__.py`).
No `_run_migrations()` step in `src/core/database.py` is needed — those are only for
altering existing tables. The `GET /api/feedback/list` endpoint reads existing columns
only. See `docs/technical/database-configuration.md` for the Lakebase specifics
(schema qualification, shared-owner ownership).
