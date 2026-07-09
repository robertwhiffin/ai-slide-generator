# Usage Analytics & Admin Usage Dashboard

Durable usage-event logging (`usage_events`) plus on-the-fly aggregation endpoints
powering the Usage tab on the hidden `/admin` page: who is using Tellr, how often,
and what they do with it.

---

## Stack / Entry Points

- **Backend:** FastAPI router (`src/api/routes/admin_usage.py`, mounted at `/api/admin/usage`), aggregation service (`src/api/services/usage_service.py`), fire-and-forget event writer (`src/api/services/usage_events.py`), SQLAlchemy model (`src/database/models/usage_event.py`)
- **Frontend:** `frontend/src/components/Admin/UsageDashboard.tsx` rendered as the default tab of `frontend/src/components/Admin/AdminPage.tsx`
- **Charts:** `recharts` (frontend dependency)
- **Storage:** PostgreSQL table `usage_events` (never pruned), plus read-only aggregation over `user_sessions`, `session_slide_decks`, `app_identities`, and `request_logs`
- **No auth guards:** like the rest of `/admin`, the endpoints are hidden-URL only (deliberate, recorded in the design spec)

---

## Architecture Snapshot

```
┌────────────────────────────────────────────────────────────────────┐
│ Event capture (write path, fire-and-forget)                        │
│                                                                    │
│  Identity middleware (main.py) ──► record_login(username)          │
│  SessionManager.save_slide_deck ──► record_deck_created(...)       │
│  GET /api/sessions/{id} route  ──► record_deck_retrieved(...)      │
│                    │                                               │
│                    ▼                                               │
│  usage_events.py: in-process 30-min dedup caches                   │
│    → run_in_executor / inline write, exceptions swallowed          │
│                    │                                               │
│                    ▼                                               │
│              usage_events table (durable, never pruned)            │
└────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────┐
│ Read path                                                          │
│                                                                    │
│  UsageDashboard.tsx ──► GET /api/admin/usage/* (6 endpoints)       │
│                    │                                               │
│                    ▼                                               │
│  UsageService: Python aggregation over time-filtered queries on    │
│  usage_events + user_sessions + session_slide_decks +              │
│  app_identities + request_logs                                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## Key Concepts / Data Contracts

### The `usage_events` table

```python
class UsageEvent(Base):
    __tablename__ = "usage_events"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    event_type = Column(String(30), nullable=False)  # 'login' | 'deck_created' | 'deck_retrieved'
    session_id = Column(Integer, nullable=True)      # user_sessions.id when applicable; NOT a FK
    ts = Column(DateTime, default=datetime.utcnow, nullable=False)
```

Indexes: `(event_type, ts)` and `(username, ts)`. `session_id` is deliberately **not**
a foreign key — events must survive session deletion; that is the point of the table.
Unlike `user_sessions`, this table is **never pruned**.

Event-type constants (`EVENT_LOGIN`, `EVENT_DECK_CREATED`, `EVENT_DECK_RETRIEVED`) live
in `src/database/models/usage_event.py`.

### Event capture semantics

All writes are **fire-and-forget** (same pattern as the `request_logs` middleware):
dispatched via `loop.run_in_executor` when called on the event loop, written inline when
already on a worker thread. Exceptions are swallowed and logged at debug — event writing
must never block or fail a user request.

| Event | Write site | Semantics / dedup |
|---|---|---|
| `login` | Identity middleware in `src/api/main.py` (alongside `record_user_login`), all environments | One event per "visit": the first authenticated request from a username after **≥ 30 minutes** without *any* authenticated request. The window is **sliding** — every authenticated request refreshes the in-process `{username: last_seen_monotonic}` cache, so continuous activity never re-emits a login. Process restart resets the cache (occasional extra login events are acceptable). |
| `deck_created` | `SessionManager.save_slide_deck` create branch (`src/api/services/session_manager.py`, where `SessionSlideDeck(...)` is instantiated) | One per deck creation; never deduped. `session_id` = the deck-owner session's id. |
| `deck_retrieved` | `GET /api/sessions/{session_id}` route (deck open, `src/api/routes/sessions.py`) | Deduped per `(username, session_id)` with the same in-process 30-minute window, so repeated polling within a visit counts once. |

`src/api/services/usage_events.py` owns both dedup caches and the non-blocking write.
`reset_dedup_caches()` is a test helper.

### Read-time visit collapse

Dedup caches are **per worker process** and the app runs multiple uvicorn workers
(`UVICORN_WORKERS=4`), so one visit can still write several `login` rows — up to one
per worker. All login *counts* therefore collapse raw rows at read time:
`_login_visit_count()` in `usage_service.py` counts **distinct
`(username, 30-minute bucket)`** pairs instead of raw rows, which reconstructs visit
counts from duplicated rows, including historical ones. This applies to the summary,
daily, top-users, and funnel login counts; distinct-user metrics are unaffected
(already set-based).

---

## Component Responsibilities

### Backend

| File | Responsibility |
|------|----------------|
| `src/database/models/usage_event.py` | `UsageEvent` model, event-type constants, indexes |
| `src/api/services/usage_events.py` | Dedup caches + fire-and-forget write (`record_login`, `record_deck_created`, `record_deck_retrieved`) |
| `src/api/services/usage_service.py` | All aggregation (`get_summary`, `get_daily`, `get_top_users`, `get_funnel`, `get_retention`, `get_heatmap`); history-boundary/proxy logic |
| `src/api/routes/admin_usage.py` | 6 GET endpoints; `?days=` validation; uniform 500 error handling |

### Frontend

| File | Responsibility |
|------|----------------|
| `frontend/src/components/Admin/AdminPage.tsx` | Tabbed `/admin` page — Usage is the **default tab** |
| `frontend/src/components/Admin/UsageDashboard.tsx` | Stat cards, recharts line/bar charts, funnel, top-users table, retention table, day×hour heatmap; shared 7/14/21/28-day window selector; history-boundary reference line and proxy legends |
| `frontend/src/services/api.ts` | `getUsageSummary()`, `getUsageDaily()`, `getUsageTopUsers()`, `getUsageFunnel()`, `getUsageRetention()`, `getUsageHeatmap()` with typed responses |

---

## API Table

All windowed endpoints accept one of three window forms (precedence top to bottom;
invalid combinations return 422):

| Form | Params | Semantics |
|------|--------|-----------|
| All data | `?all=true` | No lower bound — the full history |
| Date range | `?start=YYYY-MM-DD&end=YYYY-MM-DD` | Both required, both inclusive, `start <= end` |
| Rolling days | `?days=N` (1..365) | Last `N` UTC calendar days including today; **default 7** when no params |

The UI offers presets {7, 14, 21, 28}, "All data", and a custom range picker.
Responses echo the resolved window as `window: {days, start, end, all}` (`days` is
null for range/all modes). `get_daily` caps at 730 rows in range/all modes.
Day bucketing is **UTC calendar days**. Aggregation failures return 500.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/admin/usage/summary?days=N` | All-time totals + windowed activity headline numbers |
| `GET` | `/api/admin/usage/daily?days=N` | Per-day series (logins, users, new/returning, decks) + `history_boundary` |
| `GET` | `/api/admin/usage/top-users?days=N` | Top 20 users by logins (then sessions created) |
| `GET` | `/api/admin/usage/funnel?days=N` | Login → deck-creation funnel |
| `GET` | `/api/admin/usage/retention` | Last 8 ISO weeks of week-over-week retention (no `days` param) |
| `GET` | `/api/admin/usage/heatmap?days=N` | 7×24 day-of-week × UTC-hour activity matrix |

### Example responses

```json
// GET /api/admin/usage/summary?days=7
{
  "total_users_ever": 42,
  "total_decks_ever": 310,
  "window": {
    "days": 7,
    "start": "2026-07-02",
    "end": "2026-07-08",
    "all": false,
    "active_users": 12,
    "decks_created": 31,
    "avg_decks_per_active_user": 2.6,
    "logins": 45
  }
}
```

```json
// GET /api/admin/usage/daily?days=7  (one row per day, oldest first)
{
  "history_boundary": "2026-07-01",
  "days": [
    {
      "date": "2026-07-08",
      "logins": 9,
      "logins_proxy": false,
      "distinct_users": 7,
      "new_users": 2,
      "returning_users": 5,
      "decks_created": 4,
      "decks_retrieved": 11,
      "retrievals_proxy": null
    }
  ]
}
```

```json
// GET /api/admin/usage/top-users?days=7
[
  { "username": "alice@example.com", "logins": 14, "sessions_created": 6, "decks_created": 5 }
]
```

```json
// GET /api/admin/usage/funnel?days=7
{
  "logins": 45,
  "users_who_logged_in": 12,
  "users_who_created_deck": 8,
  "decks_created": 31,
  "proxy": false
}
```

```json
// GET /api/admin/usage/retention  (8 rows, oldest week first)
[
  { "week_start": "2026-06-29", "active_users": 10, "retained_from_prev": 6, "retention_pct": 60.0 }
]
```

```json
// GET /api/admin/usage/heatmap?days=7
// matrix: 7 weekday rows (Mon..Sun), each with 24 UTC-hour columns.
// Excerpt — first two rows (Mon, Tue) shown; real responses have all 7:
{
  "matrix": [
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 4, 9, 6, 3, 5, 7, 2, 1, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 1, 2, 5, 8, 7, 4, 6, 5, 3, 0, 1, 0, 0, 0, 0, 0, 0]
  ],
  "max": 9
}
```

---

## Metric Definitions

- **Total users ever** = `COUNT(DISTINCT identity_name)` from `app_identities` where
  `identity_type='USER'`, unioned with `DISTINCT created_by` from `user_sessions`
  (belt-and-braces; dedup by name). This resolves the old "dashboard vs `count(*)`"
  discrepancy by counting identities, not windowed session creators.
- **Total decks ever** = `COUNT(*)` from `session_slide_decks` **plus** count of
  `deck_created` usage-events whose `session_id` no longer exists in
  `session_slide_decks` (so history survives any future deletion). Forward-safe.
- **Daily logins**: from `usage_events` where available, collapsed to visits —
  distinct `(username, 30-min bucket)` per day (see *Read-time visit collapse*). For
  days **before** the first login event (`history_boundary`), fall back to
  sessions-created-per-day from `user_sessions` as a labeled proxy
  (`logins_proxy: true`).
- **Daily distinct users**: `DISTINCT username` per day from `usage_events` (any type);
  pre-boundary fallback: `DISTINCT created_by` per day from `user_sessions.created_at`.
- **New vs returning**: a user is *new* on day D if D is their first-ever appearance
  (min over `usage_events.ts`, `user_sessions.created_at`, and
  `app_identities.first_seen_at`); otherwise returning.
- **Active user (window)**: appears in `usage_events` in the window, OR has a session
  with `created_at` or `last_activity` in the window.
- **Top users by logins**: `login` events grouped by username and collapsed to
  visits (distinct 30-min buckets per user), ranked by
  `(logins, sessions_created)` descending, top 20. The table also shows
  `sessions_created` and `decks_created` per user for context (deck counts join
  `session_slide_decks` to `user_sessions.created_by`).
- **Funnel**: login visits (collapsed as above) and distinct login users in the
  window; when the window
  contains **no** login events at all, the whole login side falls back to sessions
  created (flagged `proxy: true`). `users_who_created_deck` unions `deck_created`
  event users with `user_sessions` creators of decks created in the window.
- **Retention snapshot**: for each of the last 8 ISO weeks (Monday start),
  `retained_from_prev` = users active in both week W-1 and W;
  `retention_pct = 100 * retained / active(W-1)`. When the previous week had no
  active users, **both** `retained_from_prev` and `retention_pct` are null.
  Activity = usage events or session creation.
- **Heatmap**: 7×24 matrix (rows Monday→Sunday, columns UTC hours) counting all usage
  events plus session creations in the window; `max` is the largest cell for color
  scaling.
- **Deck retrievals**: current-window counts come from `deck_retrieved` events. For
  pre-boundary days the daily endpoint also reports anonymous deck-open volume from
  `request_logs` (`GET /api/sessions/{session_id}` route template, status < 400,
  30-day retention) as `retrievals_proxy`; post-boundary days return
  `retrievals_proxy: null`.

---

## History Boundary & Proxy Semantics

`usage_events` only has data from the deploy that introduced it. The **history
boundary** is the UTC date of the first `login` event row (or `null` when none exist
yet).

- Days **on or after** the boundary render real event data.
- Days **before** the boundary (or all days when the boundary is null) use
  `user_sessions` as a labeled proxy: sessions created stand in for logins, and session
  creators stand in for distinct users. Rows are flagged with `logins_proxy: true` and
  the funnel with `proxy: true` — proxies are **labeled, never synthesized** as real
  logins.
- The UI draws a dashed reference line at the boundary ("event tracking enabled") and
  the legend/subtitle distinguishes proxy from real series.
- Decks-per-day, session, and retention series have true history throughout and need no
  marker.

---

## Operational Notes

### `user_sessions` is durable history — never schedule session cleanup

Pre-boundary metrics (and parts of retention, heatmap, top-users, and active-user
counts) depend on `user_sessions` rows surviving forever. The TTL cleanup
(`SessionManager.cleanup_expired_sessions`) is intentionally reachable **only** via the
manual `POST /api/sessions/cleanup` endpoint; nothing schedules it.

> **Warning:** do **not** wire `POST /api/sessions/cleanup` (or
> `cleanup_expired_sessions`) to any scheduler or cron. Doing so would permanently
> destroy the session history that the `/admin` usage dashboard's pre-event-log
> aggregations rely on. The method's docstring in
> `src/api/services/session_manager.py` carries the same warning.

### Write-path guarantees

- `record_*` functions never raise; failures are logged at debug and dropped.
- Dedup caches are per-process and use `time.monotonic()`; a restart may produce
  occasional extra `login` events, which is acceptable.
- DB sessions for event writes are created from `get_session_local()` per write and
  always closed; failed writes roll back.

### Migration

`usage_events` is created automatically by the `Base.metadata.create_all()` startup
path (registered via `src/database/models/__init__.py`). No `_run_migrations()` step is
needed — those are only for altering existing tables. See
[Database Configuration](./database-configuration.md) for Lakebase specifics.

### Testing

| Test file | Coverage |
|-----------|----------|
| `tests/unit/test_usage_event_model.py` | Model shape, defaults, indexes (4 tests) |
| `tests/unit/test_usage_events_writer.py` | Dedup windows (incl. sliding-window no-re-emit), never-raises guarantee, dispatch (11 tests) |
| `tests/unit/test_usage_event_capture.py` | Middleware/session-manager/route capture sites (3 tests) |
| `tests/unit/test_usage_service.py` | Seeded-event fixtures → every aggregation incl. boundary/proxy, visit collapse, and deleted-session deck counting (12 tests) |
| `tests/unit/test_admin_usage_routes.py` | Response shapes, `days` validation, error handling (9 tests) |
| `tests/unit/test_feedback_list.py` | Feedback list pagination + filters (6 tests) |

---

## Extension Guidance

- **Add an event type:** add a constant in `src/database/models/usage_event.py`, a
  `record_*` helper in `src/api/services/usage_events.py` (decide dedup semantics), a
  call at the capture site, and extend the aggregations in `usage_service.py` that
  should count it. Keep the event set lean — edit/export/share events were considered
  and excluded.
- **Change the visit window:** `_DEDUP_WINDOW_SECONDS` in
  `src/api/services/usage_events.py` (30 minutes).
- **Change window options:** `ALLOWED_WINDOWS` in `src/api/services/usage_service.py`
  and `WINDOW_OPTIONS` in `UsageDashboard.tsx`.
- **Heavier traffic:** aggregation is on-the-fly Python over windowed queries (a
  deliberate small-data choice). If volume grows, move aggregations into SQL
  `GROUP BY`s first; only add rollup tables if that fails.
- **CSV export / access control:** explicitly out of scope per the design spec
  (`docs/superpowers/specs/2026-07-03-admin-usage-dashboard-design.md`).

---

## Cross-References

- [Feedback & Satisfaction Survey System](./feedback-system.md) — the `/admin` page's Feedback tab, `GET /api/feedback/list`
- [Backend Overview](./backend-overview.md) — router registration, service patterns
- [Request Monitoring](./request-monitoring.md) — `request_logs` middleware the writer pattern mirrors; source of the retrievals proxy
- [Multi-User Concurrency](./multi-user-concurrency.md) — `user_sessions` lifecycle and identity resolution
- [Database Configuration](./database-configuration.md) — `Base.metadata.create_all()`, Lakebase schema/ownership
