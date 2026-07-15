"""Origin-validation CSRF protection (SDR-4437 CRITICAL-2, PR-1b).

Threat model: the app sets no cookies of its own — auth arrives via
proxy-attested ``x-forwarded-*`` headers. The CSRF-relevant ambient
credential is the platform SSO cookie at the Databricks Apps proxy: a
cross-site browser request to the app URL rides that cookie, the proxy
authenticates it and forwards it carrying the victim's identity.
Validating the browser-attested ``Origin`` (falling back to ``Referer``)
against the app's own origin closes this at the app layer.

Deliberate choices (documented for security review):

- **Neither header present -> allow.** Cross-origin browser POSTs always
  send ``Origin``, so the realistic attack always presents a mismatch;
  header-less mutating requests are non-browser clients (scripts/curl via
  the proxy), which rejecting would break for no security gain. A strict
  mode can be revisited if security review requires it.
- **/mcp is exempt.** It authenticates with bearer tokens, not cookies, so
  it is not a CSRF target. The mounted sub-app IS wrapped by the parent
  app's middleware (that is how ``normalize_mcp_path`` works), so the
  exemption must be this explicit path check, not an assumption that
  mounts bypass middleware. This middleware runs OUTSIDE
  ``normalize_mcp_path``, so it sees the raw ``/mcp`` (un-rewritten) path
  — both ``/mcp`` and ``/mcp/...`` are matched; ``/mcp-anything`` is not.
- **Expected origin:** ``DATABRICKS_APP_URL`` (platform-injected on
  Databricks Apps deploys — same assumption as
  ``src/api/mcp_server.py::_public_app_url``). If unset, fall back to the
  origin reconstructed from ``x-forwarded-proto``/``x-forwarded-host``
  (the proxy always sends these; same pattern as
  ``google_slides.py::_build_redirect_uri``), so a missing var degrades to
  a self-referential check instead of blocking all writes.
- **Inactive outside production** — consistent with the dev-only CORS gate
  in ``main.py`` (dev auth is ``DEV_USER_ID`` with no proxy in front).
"""

import logging
import os
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _origin_of(url: str) -> str:
    """Normalize a URL (or Origin header value) to ``scheme://host[:port]``.

    Returns "" for values with no parseable scheme+host (e.g. ``null``).
    """
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests whose Origin/Referer is cross-site."""

    def __init__(self, app, enabled: bool | None = None):
        super().__init__(app)
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("ENVIRONMENT", "development") == "production"
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or request.method not in _UNSAFE_METHODS:
            return await call_next(request)

        path = request.url.path
        if path == "/mcp" or path.startswith("/mcp/"):
            return await call_next(request)

        claimed = request.headers.get("origin") or request.headers.get("referer")
        if not claimed:
            return await call_next(request)

        claimed_origin = _origin_of(claimed)
        expected_origin = self._expected_origin(request)
        if claimed_origin and expected_origin and claimed_origin == expected_origin:
            return await call_next(request)

        logger.warning(
            "CSRF: rejected cross-origin %s %s (claimed=%r, expected=%r)",
            request.method,
            path,
            claimed_origin,
            expected_origin,
        )
        return JSONResponse(
            status_code=403,
            content={"detail": "Cross-origin request rejected"},
        )

    @staticmethod
    def _expected_origin(request: Request) -> str:
        app_url = os.getenv("DATABRICKS_APP_URL", "")
        if app_url:
            return _origin_of(app_url)
        host = request.headers.get("x-forwarded-host", "")
        proto = request.headers.get("x-forwarded-proto", "https")
        if host:
            return f"{proto.strip().lower()}://{host.split(',')[0].strip().lower()}"
        return ""
