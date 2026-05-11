"""Tests for optional Databricks App Telemetry logging bootstrap."""

from __future__ import annotations

import logging

import pytest


def test_configure_skipped_without_otel_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    from src.core.otel_logging import configure_app_telemetry_logging_if_enabled

    assert configure_app_telemetry_logging_if_enabled() is None


def test_configure_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc._log_exporter")

    from src.core.otel_logging import configure_app_telemetry_logging_if_enabled

    root = logging.getLogger()
    before = len(root.handlers)
    h1 = configure_app_telemetry_logging_if_enabled()
    assert h1 is not None
    h2 = configure_app_telemetry_logging_if_enabled()
    assert h2 is h1
    assert len(root.handlers) == before + 