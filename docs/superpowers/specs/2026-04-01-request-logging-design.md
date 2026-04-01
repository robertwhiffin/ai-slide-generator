# Request Logging & Monitoring Design

## Problem

The app experiences significant slowdowns under load (~30 concurrent users) on Databricks Apps. Navigation, page loads, and database fetches are slow — not the core slide generation loop. Databricks Apps only surfaces logs via real-time stdout with no persistence, making post-hoc analysis impossible. There is currently no request-level instrumentation.

## Goal

Capture request-level metrics (endpoint, duration, status) in Lakebase so developers can query historical data to identify which endpoints are slow, how often they're called, and how performance degrades under load.

## Non-Goals

- Sub-request tracing (DB query time, LLM call time breakdown)
- Frontend request instrumentation
- In-app dashboard or metrics API
- User attribution per request
- OpenTelemetry integration

## Design

### 1. Data Model

A new `request_log` SQLAlchemy model and corresponding Lakebase table, auto-created via the existing migration-on-startup pattern.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID, PK | Row identifier |
| `timestamp` | DateTime (UTC) | When the request started |
| `method` | String(10) | HTTP method |
| `path` | String(500) | URL path |
| `status_code` | Integer | HTTP response status |
| `duration_ms` | Float | Total request wall-clock time in milliseconds |
| `request_id` | UUID | For correlating with stdout log output |

Excluded: request/response bodies, query strings, headers, user identity.

### 2. Middleware

A new ASGI middleware registered in `main.py`, placed before the auth middleware to capture full request time including auth overhead.

**Behavior:**
- Generates a `request_id` UUID per request
- Records wall-clock time around `call_next(request)` — this captures the entire handler lifecycle including all DB queries, external calls, and I/O
- Skips `/api/health` to avoid noise
- Writes a `RequestLog` row using a dedicated async DB session (not the request's session) so logging failures cannot affect the request
- All DB writes wrapped in try/except — monitoring never takes down the app
- Attaches `X-Request-ID` response header for correlation with stdout logs

### 3. TTL Cleanup

A background task started via FastAPI's `lifespan` event (same pattern as Lakebase token refresh).

**Behavior:**
- Checks every hour, executes cleanup if 24+ hours since last run
- Runs `DELETE FROM request_logs WHERE timestamp < NOW() - INTERVAL '30 days'`
- Logs number of deleted rows to stdout
- Silently handles failures, retries on next cycle

30-day retention hardcoded initially.

## Files Changed

| File | Change |
|------|--------|
| `src/database/models/request_log.py` | New model |
| `src/database/models/__init__.py` | Export new model |
| `src/api/middleware/request_logging.py` | New middleware |
| `src/api/main.py` | Register middleware, start cleanup task |
| `src/core/database.py` | Add cleanup task function |

## Example Queries

Once deployed, developers can query Lakebase directly:

```sql
-- Slowest endpoints (avg) in the last 24 hours
SELECT path, method,
       AVG(duration_ms) as avg_ms,
       MAX(duration_ms) as max_ms,
       COUNT(*) as request_count
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY path, method
ORDER BY avg_ms DESC;

-- Requests over 2 seconds
SELECT * FROM request_logs
WHERE duration_ms > 2000
ORDER BY timestamp DESC
LIMIT 50;

-- Request volume by endpoint per hour
SELECT date_trunc('hour', timestamp) as hour,
       path, method, COUNT(*) as count
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY hour, path, method
ORDER BY hour DESC, count DESC;

-- Error rate by endpoint
SELECT path, method,
       COUNT(*) FILTER (WHERE status_code >= 500) as errors,
       COUNT(*) as total,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status_code >= 500) / COUNT(*), 1) as error_pct
FROM request_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY path, method
ORDER BY error_pct DESC;
```
