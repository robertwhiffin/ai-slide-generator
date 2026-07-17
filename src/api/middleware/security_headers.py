"""App-origin security headers (SDR-4437 CRITICAL-1, PR-1a).

Sets browser hardening headers on every response that flows back through
the middleware stack (known limit: raw 500s from genuinely unhandled
exceptions are synthesized by Starlette's ``ServerErrorMiddleware``
outside all user middleware and are NOT stamped; those bodies are
``text/plain`` and non-executable), plus a
Content-Security-Policy differentiated by response type:

- HTML documents (the SPA index/catch-all AND the Google OAuth callback
  popup, which carries inline <script>) get ``DOCUMENT_CSP``. Two
  constraints rule out a strict policy here:

  1. srcdoc inheritance: slides render in ``srcdoc`` iframes, and srcdoc
     documents inherit the embedding document's CSP in addition to their
     own SLIDE_CSP meta tag (both policies enforce; most restrictive
     wins). A ``default-src 'self'`` header on the SPA would block every
     slide's inline <script>, Chart.js/Tailwind CDN loads, and Google
     Fonts — breaking slide rendering app-wide. The document policy must
     therefore be a superset of SLIDE_CSP's allowances
     (``src/utils/html_safety.py``; sync-tested in
     ``tests/unit/test_export_csp.py``).
  2. Inline styles: the React app uses ``style={{...}}`` attributes and
     Radix UI injects inline styles at runtime; CSP hashes apply to
     <style>/<script> *elements*, not style *attributes*, so
     ``style-src`` needs 'unsafe-inline'.

  ``script-src 'unsafe-inline'`` + CDNs is a deliberate, documented
  trade-off forced by srcdoc inheritance: slides remain confined by the
  stricter SLIDE_CSP meta policy (connect-src 'none', form-action
  'none', no eval) plus the html_safety.py scanner, and any header at
  all is a strict improvement over the previous no-CSP state.

- Everything else (JSON APIs, assets, SSE) gets the deny-all
  ``API_CSP`` — nothing executes in a JSON response.

``frame-ancestors 'none'`` / ``X-Frame-Options: DENY`` is safe: all
in-app slide iframes use ``srcdoc`` (never a backend-served ``src``), and
the only other HTML endpoint, the Google OAuth callback, opens as a
popup, not an iframe.

``frame-src 'self'`` does not affect the srcdoc slide iframes: a srcdoc
document loads no URL (its address is the local scheme ``about:srcdoc``,
no fetch occurs), and per CSP3 local-scheme handling plus current
Chrome/Firefox/Safari behavior it is NOT subject to frame-src source
matching — even ``frame-src 'none'`` pages can create srcdoc iframes.
Instead it inherits this document policy, which is exactly the
srcdoc-inheritance constraint handled above. Pre-decided fallback if a
browser ever refuses the slide iframe with a frame-src violation
("Refused to frame ..."): ``frame-src 'self' about:`` — the ``about:``
scheme-source matches ``about:srcdoc`` (the historical workaround for
old-Chrome behavior that did URL-match about: frames).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# CSP for HTML document responses: union of SPA needs and SLIDE_CSP
# allowances (kept a superset of SLIDE_CSP by test_export_csp.py).
DOCUMENT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data:; "
    "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'none'"
)

# CSP for everything else.
API_CSP = "default-src 'none'; frame-ancestors 'none'"

_STATIC_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp security headers on every response (registered outermost)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _STATIC_HEADERS.items():
            response.headers[name] = value
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Content-Security-Policy"] = DOCUMENT_CSP
        else:
            response.headers["Content-Security-Policy"] = API_CSP
        return response
