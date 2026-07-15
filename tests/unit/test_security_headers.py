"""SDR-4437 CRITICAL-1: every response carries app-origin security headers,
with the document CSP on HTML responses and the strict CSP on everything else.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse

from src.api.middleware.security_headers import (
    API_CSP,
    DOCUMENT_CSP,
    SecurityHeadersMiddleware,
)

EXPECTED_STATIC = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/thing")
    async def api_thing():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return "<html><body>spa</body></html>"

    return TestClient(app)


def test_api_response_carries_headers_and_strict_csp(client):
    r = client.get("/api/thing")
    for name, value in EXPECTED_STATIC.items():
        assert r.headers[name] == value
    assert r.headers["Content-Security-Policy"] == API_CSP


def test_html_response_carries_document_csp(client):
    r = client.get("/")
    for name, value in EXPECTED_STATIC.items():
        assert r.headers[name] == value
    assert r.headers["Content-Security-Policy"] == DOCUMENT_CSP


def test_error_response_carries_headers(client):
    r = client.get("/does-not-exist")
    assert r.status_code == 404
    assert r.headers["Content-Security-Policy"] == API_CSP
    assert r.headers["X-Frame-Options"] == "DENY"


def test_document_csp_hardening_directives():
    # The document policy must still deny framing, plugins, and <base> rewrites,
    # and must not grant eval.
    assert "frame-ancestors 'none'" in DOCUMENT_CSP
    assert "object-src 'none'" in DOCUMENT_CSP
    assert "base-uri 'none'" in DOCUMENT_CSP
    assert "unsafe-eval" not in DOCUMENT_CSP


def test_api_csp_is_deny_all():
    assert API_CSP == "default-src 'none'; frame-ancestors 'none'"


def test_main_app_registers_security_headers():
    # Registration check against the real app (ENVIRONMENT=test via conftest;
    # the SPA is only mounted in production's lifespan, so use an API route).
    from src.api.main import app as main_app

    r = TestClient(main_app).get("/api/health")
    assert r.headers["Content-Security-Policy"] == API_CSP
    assert r.headers["X-Frame-Options"] == "DENY"
