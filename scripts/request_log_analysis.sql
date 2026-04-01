-- Request Log Analysis: Top Offenders
-- Run against the request_logs table in Lakebase/PostgreSQL

-- 1. Slowest endpoints by average duration (last 24h)
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

-- 2. Most called endpoints (last 24h)
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

-- 3. Requests over 1 second (last 24h)
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

-- 4. Error rate by endpoint (last 24h)
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

-- 5. Hourly throughput and latency trend (last 24h)
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

-- 6. Slowest individual requests (last 24h) — for request_id correlation
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
