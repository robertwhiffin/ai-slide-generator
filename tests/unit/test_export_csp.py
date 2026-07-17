"""AISEC-248: the server-side slide-document builder must inject the same
Content-Security-Policy the frontend uses, so the huashu/Playwright export
render and the standalone HTML export contain LLM-authored slide JS the same
way the in-app iframe does.
"""

import re
from pathlib import Path

from src.api.routes.export import build_slide_html
from src.utils.html_safety import SLIDE_CSP, SLIDE_CSP_META

_FRONTEND_SLIDE_DOC = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "services" / "slideDocument.ts"
)


def _frontend_slide_csp() -> str:
    """Extract and concatenate the SLIDE_CSP string literal from the TS source."""
    src = _FRONTEND_SLIDE_DOC.read_text()
    # Slice the `export const SLIDE_CSP = "..." + "..." ...;` declaration up to
    # the next statement (CSP_META), then join its string literals. (Can't stop
    # at the first ';' — the directives contain ';' inside the quotes.)
    m = re.search(
        r"export const SLIDE_CSP\s*=\s*(.*?)const CSP_META", src, re.DOTALL
    )
    assert m, "could not find SLIDE_CSP in slideDocument.ts"
    return "".join(re.findall(r'"([^"]*)"', m.group(1)))


def test_build_slide_html_injects_csp_meta():
    slide = {"slide_id": "s1", "html": "<div>hi</div>"}
    deck = {"title": "T", "css": "", "scripts": "", "external_scripts": []}
    html = build_slide_html(slide, deck)
    assert SLIDE_CSP_META in html
    assert "Content-Security-Policy" in html


def test_slide_csp_is_an_egress_boundary():
    # The whole point: block exfil channels and withhold eval.
    assert "default-src 'none'" in SLIDE_CSP
    assert "connect-src 'none'" in SLIDE_CSP
    assert "form-action 'none'" in SLIDE_CSP
    assert "unsafe-eval" not in SLIDE_CSP


def test_backend_csp_matches_frontend_csp():
    # Two render surfaces, one policy. If the frontend constant changes, this
    # fails loudly so the backend copy is updated in lockstep.
    assert SLIDE_CSP == _frontend_slide_csp()


def test_csp_meta_precedes_slide_content():
    # CSP must be parsed before any inline script/handler in the slide body.
    slide = {"slide_id": "s1", "html": '<div onclick="x()">hi</div>'}
    deck = {"title": "T", "css": "", "scripts": "", "external_scripts": []}
    html = build_slide_html(slide, deck)
    assert html.index("Content-Security-Policy") < html.index("<body>")


def test_non_allowlisted_external_script_is_logged(caplog):
    # A <script src> to a non-CDN host is silently blocked by CSP at runtime;
    # the scan must still surface it as telemetry.
    slide = {"slide_id": "s1", "html": "<div>hi</div>"}
    deck = {
        "title": "T", "css": "", "scripts": "",
        "external_scripts": ["https://evil.example.com/x.js"],
    }
    import logging
    with caplog.at_level(logging.WARNING):
        build_slide_html(slide, deck)
    assert any("Unsafe patterns in exported slide HTML" in r.message for r in caplog.records)


def test_allowlisted_external_script_is_not_flagged(caplog):
    slide = {"slide_id": "s1", "html": "<div>hi</div>"}
    deck = {
        "title": "T", "css": "", "scripts": "",
        "external_scripts": ["https://cdn.jsdelivr.net/npm/chart.js"],
    }
    import logging
    with caplog.at_level(logging.WARNING):
        build_slide_html(slide, deck)
    assert not any("Unsafe patterns" in r.message for r in caplog.records)


def _csp_directives(policy: str) -> dict[str, set[str]]:
    out = {}
    for directive in policy.split(";"):
        directive = directive.strip()
        if not directive:
            continue
        name, *sources = directive.split()
        out[name] = set(sources)
    return out


def test_document_csp_header_is_superset_of_slide_csp():
    # SDR-4437 PR-1a: srcdoc iframes inherit the embedding document's CSP in
    # addition to the SLIDE_CSP meta tag (both enforce; most restrictive
    # wins). Every fetch source SLIDE_CSP grants must therefore also be
    # granted by the document CSP header, or slide rendering breaks app-wide.
    from src.api.middleware.security_headers import DOCUMENT_CSP

    slide = _csp_directives(SLIDE_CSP)
    doc = _csp_directives(DOCUMENT_CSP)
    for directive in ("script-src", "style-src", "img-src", "font-src"):
        missing = slide[directive] - doc[directive]
        assert not missing, f"{directive}: document CSP header missing {missing}"
