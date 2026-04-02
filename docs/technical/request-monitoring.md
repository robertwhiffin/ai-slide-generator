# Request Monitoring – Per-Request Performance Logging to Lakebase

ASGI middleware that captures per-request metrics (method, path, status code, duration) and writes them to a `request_logs` table in Lakebase. Provides SQL analysis queries for identifying slow endpoints, error rates, and traffic patterns.

---

## Stack / Entry Points

| Component | Path | Purpose |
|-----------|------|---------|
| RequestLog Model | `src/database/models/request_log.py` | SQLAlchemy model for the `request_logs` table |
| Logging Middleware | `src/api/middleware/request_logging.py` | ASGI middleware + background cleanup task |
| App Registration | `src/api/main.py` | Middleware and cleanup lifecycle wiring |
| Analysis Queries | `scripts/request_log_analysis.sql` | Ready-to-run SQL for diagnosing performance |

---

## Architecture Snapshot

```
  Incoming Request
        │
        ▼
┌──────────────────────────────┐
│  RequestLoggingMiddleware    │
│  1. Generate X-Request-ID    │
│  2. Start timer              │
│  3. Call next middleware      │
│  4. Stop timer               │
│  5. Fire-and-forget DB write │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Application (FastAPI)       │
│  Processes request, returns  │
│  response with status code   │
└──────────────────────────────┘

  Background (separate thread via run_in_executor):
  ┌────────────────────────────┐
  │  _enqueue_log()            │
  │  Opens DB session → INSERT │
  │  into request_logs → close │
  └────────────────────────────┘

  Background (asyncio task, hourly check):
  ┌────────────────────────────┐
  │  request_log_cleanup_loop  │
  │  DELETE rows > 30 days old │
  └────────────────────────────┘
```

---

## Data Contract

### `request_logs` Table

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | `Integer` | No (PK) | Auto-incrementing primary key |
| `timestamp` | `DateTime` | No | UTC time the request was received |
| `method` | `String(10)` | No | HTTP method (`GET`, `POST`, etc.) |
| `path` | `String(500)` | No | Route template, e.g. `/api/sessions/{session_id}` |
| `status_code` | `Integer` | No | HTTP response status code |
| `duration_ms` | `Float` | No | Wall-clock request duration in milliseconds |
| `request_id` | `String(36)` | Yes | UUID v4 correlating with the `X-Request-ID` response header |

**Indexes:**
- `ix_request_logs_timestamp` on `timestamp` — supports time-range queries and cleanup deletes

### Route Template Aggregation

Paths are stored as route templates, not literal URLs. This enables meaningful `GROUP BY` aggregation:

| Raw URL | Stored Path |
|---------|-------------|
| `/api/sessions/abc-123` | `/api/sessions/{session_id}` |
| `/api/sessions/abc-123/slides/5` | `/api/sessions/{session_id}/slides/{slide_id}` |
| `/api/profiles` | `/api/profiles` |

The middleware extracts templates from Starlette's `request.scope["route"].path` when available, falling back to the literal URL path.

---

## Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| `RequestLoggingMiddleware.dispatch()` | Intercept requests, measure duration, attach `X-Request-ID`, dispatch async log write |
| `_should_log(path)` | Filter: only `/api/*` paths, excluding health, streaming, and static assets |
| `_get_route_template(request)` | Extract route template from Starlette scope for path aggregation |
| `_enqueue_log(log_entry)` | Synchronous DB write (runs in thread pool via `run_in_executor`) |
| `request_log_cleanup_loop()` | Background asyncio task: hourly check, daily DELETE of rows older than 30 days |

---

## Request Flow

1. Request arrives at `RequestLoggingMiddleware.dispatch()`
2. `_should_log()` checks if the path qualifies — returns early if excluded
3. A UUID v4 `request_id` is generated and a high-resolution timer starts
4. The request is forwarded to the application via `call_next(request)`
5. On response (or unhandled exception), the timer stops and `duration_ms` is calculated
6. The `X-Request-ID` header is added to the response
7. A log entry dict is dispatched to `_enqueue_log()` via `loop.run_in_executor(None, ...)`
8. The response is returned immediately — the DB write happens asynchronously in a thread

### Excluded Paths

| Path / Prefix | Reason |
|---------------|--------|
| `/api/health` | High-frequency health checks would dominate the table |
| `/api/chat/stream` | Long-lived SSE connections; duration is not meaningful |
| `/assets/*` | Static file serving; not relevant to API performance |
| Non-`/api/` paths | Frontend routes served by FastAPI's static file mount |

---

## Lifecycle Integration

The middleware and cleanup task are wired into the FastAPI app in `src/api/main.py`:

**Middleware registration** (module level):
```python
from src.api.middleware.request_logging import RequestLoggingMiddleware
app.add_middleware(RequestLoggingMiddleware)
```

**Cleanup task** (lifespan startup, skipped in test mode):
```python
from src.api.middleware.request_logging import request_log_cleanup_loop
_cleanup_task = asyncio.create_task(request_log_cleanup_loop())
```

The cleanup loop runs indefinitely: it sleeps for 1 hour, then checks if 24 hours have passed since the last cleanup. If so, it executes:
```sql
DELETE FROM request_logs WHERE timestamp < NOW() - INTERVAL '30 days'
```

---

## Error Isolation

The middleware is designed so that logging failures never affect request handling:

- **DB write failures**: caught and logged at `DEBUG` level; the response is returned normally
- **Enqueue failures**: wrapped in a bare `except Exception` — the response is always returned
- **Unhandled request exceptions**: the middleware still attempts to log a `500` entry before re-raising
- **Cleanup failures**: caught per-cycle; the loop continues and retries on the next hourly check

---

## Usage: Analysis Queries

All queries are in `scripts/request_log_analysis.sql`. Run them against the Lakebase instance directly (e.g. via a Databricks notebook or `psql`).

### 1. Slowest Endpoints by Average Duration (last 24h)

```sql
SELECT
    method,
    path,
    COUNT(*) AS hits,
    ROUND(AVG(duration_ms)::numeric, 1) AS avg_ms,
    ROUND(MAX(duration_ms)::numeric, 1) AS max_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 1) AS p95_ms
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY method, path
ORDER BY avg_ms DESC
LIMIT 20;
```

**Use when:** you need to identify which endpoints are consistently slow.

### 2. Most Called Endpoints (last 24h)

```sql
SELECT
    method,
    path,
    COUNT(*) AS hits,
    ROUND(AVG(duration_ms)::numeric, 1) AS avg_ms,
    COUNT(*) FILTER (WHERE status_code >= 500) AS errors_5xx,
    COUNT(*) FILTER (WHERE status_code >= 400 AND status_code < 500) AS errors_4xx
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY method, path
ORDER BY hits DESC
LIMIT 20;
```

**Use when:** you want to see traffic distribution and identify hot endpoints or unexpected polling.

### 3. Requests Over 1 Second (last 24h)

```sql
SELECT
    timestamp,
    method,
    path,
    status_code,
    ROUND(duration_ms::numeric, 1) AS duration_ms,
    request_id
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
  AND duration_ms > 1000
ORDER BY duration_ms DESC
LIMIT 50;
```

**Use when:** you need to find individual slow requests. Correlate `request_id` with the `X-Request-ID` response header or stdout logs.

### 4. Error Rate by Endpoint (last 24h)

```sql
SELECT
    method,
    path,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE status_code >= 400) AS errors,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status_code >= 400) / COUNT(*), 1) AS error_pct
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY method, path
HAVING COUNT(*) FILTER (WHERE status_code >= 400) > 0
ORDER BY error_pct DESC, total DESC;
```

**Use when:** you suspect a particular endpoint is failing frequently or returning 4xx/5xx errors.

### 5. Hourly Throughput and Latency Trend (last 24h)

```sql
SELECT
    DATE_TRUNC('hour', timestamp) AS hour,
    COUNT(*) AS requests,
    ROUND(AVG(duration_ms)::numeric, 1) AS avg_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 1) AS p95_ms,
    COUNT(*) FILTER (WHERE status_code >= 500) AS errors_5xx
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', timestamp)
ORDER BY hour;
```

**Use when:** you want to see how load and latency change over time — useful for correlating with user-reported slowness.

### 6. Slowest Individual Requests (last 24h)

```sql
SELECT
    timestamp,
    method,
    path,
    status_code,
    ROUND(duration_ms::numeric, 1) AS duration_ms,
    request_id
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
ORDER BY duration_ms DESC
LIMIT 20;
```

**Use when:** you need to find the absolute worst-case requests for deep-dive investigation.

---

## Operational Notes

- **Retention**: 30 days. The cleanup loop deletes older rows daily.
- **Write strategy**: fire-and-forget via `run_in_executor` (thread pool). Each log write opens and closes its own DB session to avoid contention with the application's connection pool.
- **Table creation**: the `request_logs` table is auto-created on app startup via `Base.metadata.create_all()` in `init_db()`. No manual migration needed.
- **Testing**: 14 tests across three files — `tests/unit/test_request_log_model.py` (3), `tests/unit/test_request_logging_middleware.py` (8), `tests/integration/test_request_logging.py` (3).
- **Log level**: failures are logged at `DEBUG` to avoid noise in production stdout.

---

## Extension Guidance

- **Changing retention period**: modify the `INTERVAL '30 days'` in `request_log_cleanup_loop()` and the `86400` (24h gate) if you want more/less frequent cleanup
- **Adding columns**: add to the `RequestLog` model in `src/database/models/request_log.py`, update the `log_entry` dict construction in the middleware, and let `create_all()` handle the new table (or `ALTER TABLE` for existing deployments)
- **Filtering more paths**: add entries to `_EXCLUDED_PATHS` (exact match) or `_EXCLUDED_PREFIXES` (prefix match) in `src/api/middleware/request_logging.py`
- **Alerting on slow requests**: query #3 or #5 from a scheduled notebook to detect latency spikes

---

## Cross-References

- [Lakebase Integration](lakebase-integration.md) – Database connectivity, authentication, and schema setup
- [Backend Overview](backend-overview.md) – FastAPI application structure and middleware stack
- [Database Configuration](database-configuration.md) – Local PostgreSQL setup for development
