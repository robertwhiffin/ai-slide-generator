"""Databricks App Telemetry: Python logging → OTLP → UC Delta tables.

When the platform injects ``OTEL_EXPORTER_OTLP_ENDPOINT`` (App Telemetry beta),
attach an OpenTelemetry ``LoggingHandler`` so ``logging`` records land in
``<prefix>_otel_logs`` (and correlate with spans when active).

**Not** the same path as MLflow GenAI UC traces (``src/core/mlflow_tracing.py``):
those tables are written by MLflow when an experiment is created with
``trace_location=UnityCatalog(...)`` and traces are exported by MLflow.

See ``otel_guidance.md`` at the repository root.
"""

from __future__ import annotations

import logging
import os


def configure_app_telemetry_logging_if_enabled() -> logging.Handler | None:
    """Attach OTLP log export to the root logger when App Telemetry env is set.

    Returns the handler instance if attached, else ``None``. Safe to call
    multiple times: second call is a no-op if a ``LoggingHandler`` is already
    on the root logger from this module.
    """
    if not (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip():
        return None

    root = logging.getLogger()
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
    except ImportError as e:
        logging.getLogger(__name__).warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but OpenTelemetry OTLP log "
            "dependencies are missing (%s). Install opentelemetry-exporter-otlp-proto-grpc.",
            e,
        )
        return None

    for h in root.handlers:
        if isinstance(h, LoggingHandler):
            return h

    service_name = (os.environ.get("OTEL_SERVICE_NAME") or "tellr").strip()
    resource = Resource.create({"service.name": service_name})
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(provider)
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
    root.addHandler(handler)
    logging.getLogger(__name__).info(
        "App Telemetry: OTLP LoggingHandler attached (service.name=%s)",
        service_name,
    )
    return handler
