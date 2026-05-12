> [< Back to Chapter Overview](README.md)

# Application Logging

Databricks Apps need a persistent, SQL-queryable logging sink for operational visibility. This guide covers the managed OTEL App Telemetry (preferred).

> **Key documentation:** [App Telemetry](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/observability)

---

## Tellr implementation (this repo)

Two different mechanisms can create similarly named Unity Catalog Delta tables; they do **not** share the same write path:

| Mechanism | What fills the tables | Tellr code |
|-----------|-------------------------|------------|
| **Databricks App Telemetry** (this page) | Python `logging` → OTLP gRPC → platform collector → `<prefix>_otel_logs` (and OTEL spans/metrics if you instrument traces/metrics) | [`src/core/otel_logging.py`](src/core/otel_logging.py), loaded via [`src/api/_otel_bootstrap.py`](src/api/_otel_bootstrap.py) from [`src/api/main.py`](src/api/main.py) when `OTEL_EXPORTER_OTLP_ENDPOINT` is set |
| **MLflow 3 UC trace storage** | MLflow GenAI / evaluation traces when the **tracking experiment** is created with `trace_location=UnityCatalog(...)` | [`src/core/mlflow_tracing.py`](src/core/mlflow_tracing.py), env `TELLR_MLFLOW_UC_*` — see [`docs/technical/mlflow-uc-tracing.md`](docs/technical/mlflow-uc-tracing.md) |

If UC shows `*_otel_spans` / `*_otel_logs` **schemas** (empty tables): the platform may have provisioned tables for App Telemetry or for MLflow’s UC trace layout, but **no writer** is active until (1) App Telemetry is enabled *and* this app exports OTLP logs/spans, or (2) MLflow successfully exports traces into a **new** UC-bound experiment (existing experiments keep their original trace backend).

---

## Managed OTEL App Telemetry (Beta)

> **Beta feature.** App Telemetry is currently in public beta with limited regional availability.
> **Configuration must be done manually through the Databricks App UI today.**
> DABs bundle support and write-capable SDK support are not yet available -- the SDK currently exposes `telemetry_export_destinations` as a read-only field that can be used to inspect the configuration of an existing deployment.

### How It Works

When App Telemetry is configured, the platform injects `OTEL_EXPORTER_OTLP_ENDPOINT` (and related env vars) into the app process as default system environment variables. The app ships log records directly to a local OTLP collector over gRPC, which forwards them to three auto-created Unity Catalog Delta tables:

| Table | Populated by |
|---|---|
| `<prefix>_otel_logs` | Python `logging` records (via `LoggingHandler`) |
| `<prefix>_otel_spans` | OTEL SDK trace spans |
| `<prefix>_otel_metrics` | OTEL SDK metrics |

### Schema of `otel_logs`

The auto-created table has the following key columns (the manual Zerobus fallback mirrors this schema exactly):

| Column | Type | Notes |
|---|---|---|
| `record_id` | STRING | UUID generated per record |
| `time` | TIMESTAMP | Log record timestamp (clustered) |
| `date` | DATE | Partition column |
| `service_name` | STRING | From `OTEL_SERVICE_NAME` env var |
| `severity_number` | STRING | `"9"` = INFO, `"13"` = WARN, `"17"` = ERROR |
| `severity_text` | STRING | `INFO`, `WARN`, `ERROR`, `FATAL` |
| `body` | VARIANT | Log message (raw, not formatter output) |
| `attributes` | VARIANT | Key-value extras (exception info etc.) |
| `instrumentation_scope` | STRUCT | `.name` = Python logger name |
| `resource` | STRUCT | `.attributes` = `{"service.name": ...}` |
| `trace_id` / `span_id` | STRING | Populated when a span is active |

### Setup -- One-Time via the App UI

1. Open the App details page -> **App telemetry** -> **Add**
2. Set **Catalog** and **Schema** (e.g. `users.david_tempelmann`)
3. Optionally set a **prefix** (e.g. `myapp`) -> tables become `myapp_otel_logs` etc.
4. Save and redeploy the app (the platform only injects the OTEL env vars after a fresh deployment)

### Verify Configuration via SDK (Read-Only)

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
app = w.apps.get("my-app-name")
for dest in (app.telemetry_export_destinations or []):
    print(dest.as_dict())
# -> {'unity_catalog': {'logs_table': '...', 'metrics_table': '...', 'traces_table': '...'}}
```

### App Implementation -- LoggingHandler Configuration

The critical requirement is that the OTEL `LoggingHandler` is configured before any default console/stderr logging setup, and that the `StreamHandler` is suppressed when the OTEL handler is active. If `basicConfig` (or equivalent startup code) configures a `StreamHandler` first and both handlers remain attached, each record is emitted twice -- once with correct severity via OTEL and once via stderr capture, which appears as `severity_text = UNKNOWN`.

```python
# app.py -- logging setup at module level, before any other logging calls

import logging
import os


def _configure_logging() -> logging.Handler | None:
    """
    Attach OTEL LoggingHandler when platform telemetry is active, console otherwise.
    Must be called before any logging.basicConfig() call.
    """
    root = logging.getLogger()
    root.setLevel(logging.NOTSET)  # let handlers filter; do not drop at the root

    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # Platform injects this env var when App Telemetry is configured.
        # Attach the OTEL handler as the sole sink -- suppress StreamHandler so
        # stderr does not produce duplicate UNKNOWN-severity records.
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "unknown")})
        provider = LoggerProvider(resource=resource)
        # OTLPLogExporter reads OTEL_EXPORTER_OTLP_ENDPOINT automatically
        provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(provider)
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
        root.addHandler(handler)
        return handler
    else:
        # Local development -- console only
        console = logging.StreamHandler()
        console.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO))
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s -- %(message)s"))
        root.addHandler(console)
        return None


_otel_handler = _configure_logging()
logger = logging.getLogger(__name__)
```

### Dependencies

Add these to `pyproject.toml`:

```toml
dependencies = [
    "opentelemetry-distro>=0.49b0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.28.0",
]
```

No `opentelemetry-instrument` CLI wrapper is needed -- the app reads the injected env var and configures the SDK itself.

In this repository, [`src/core/otel_logging.py`](src/core/otel_logging.py) mirrors the handler setup above; [`src/api/_otel_bootstrap.py`](src/api/_otel_bootstrap.py) runs it on import (imported from [`src/api/main.py`](src/api/main.py) after FastAPI, before `src.api.routes`) when `OTEL_EXPORTER_OTLP_ENDPOINT` is present.

### Query Examples

```sql
-- Recent errors from your app
SELECT time, body::string AS message, attributes
FROM users.david_tempelmann.myapp_otel_logs
WHERE service_name = 'my-app'
  AND severity_text = 'ERROR'
  AND time >= current_timestamp() - INTERVAL 1 HOUR
ORDER BY time DESC;

-- Auth events (automatically captured by the platform)
SELECT time, attributes:["event.name"]::string AS event
FROM users.david_tempelmann.myapp_otel_logs
WHERE attributes:["event.name"]::string = 'app.auth'
ORDER BY time DESC LIMIT 100;
```

---


**Practical guidance for production deployments:**

- **Log level discipline** -- set the root logger to `INFO` in production; suppress or sample `DEBUG` logs before they reach the handler
- **Cap body/stacktrace size** -- truncate exception stacktraces and long message bodies before enqueueing (e.g. `body = message[:4096]`)
- **Instrument the handler** -- add counters for queue depth, dropped records, and ingest errors; expose them on a `/metrics` endpoint or write them to a Databricks metric table
- **Batch where possible** -- the Zerobus SDK drains records one at a time; for high-frequency events consider aggregating (e.g. request counts per minute) before logging rather than one record per request
- **Load-test at peak RPS** -- verify the queue depth does not trend upward over a sustained window at expected peak traffic; if it does, reduce log rate or scale down verbosity

---
