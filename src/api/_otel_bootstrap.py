"""Import side-effect: start OTLP logging when Databricks App Telemetry env is set.

Loaded first from ``main.py`` so ``LoggingHandler`` attaches before other ``src``
imports emit log records. See ``otel_guidance.md`` and ``src/core/otel_logging.py``.
"""

from __future__ import annotations

import logging
import os


def _bootstrap() -> None:
    if not (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip():
        return
    try:
        from src.core.otel_logging import configure_app_telemetry_logging_if_enabled

        configure_app_telemetry_logging_if_enabled()
    except Exception as exc:  # pragma: no cover
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        logging.getLogger("tellr.otel").warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but OTLP logging init failed: %s",
            exc,
        )


_bootstrap()
