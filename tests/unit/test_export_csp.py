"""AISEC-248: the server-side slide-document builder must inject the same
Content-Security-Policy the frontend uses, so the huashu/Playwright export
render and the standalone HTML export contain LLM-authored slide JS the same
way the in-app iframe does.
"""

import re
from pathlib import Path

import pytest

from src.api.routes.export import build_slide_html
from src.utils.html_safety import (
    SLIDE_CSP,
    SLIDE_CSP_META,
    SLIDE_ROOT_RESET_STYLE,
)

_FRONTEND_SLIDE_DOC = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "services" / "slideDocument.ts"
)

#: A real Google Fonts import — the WF-03 shape, whose query contains SEMICOLONS.
_FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700&display=swap');"
)


def _deck_with_css(css: str) -> dict:
    return {"title": "T", "css": css, "scripts": "", "external_scripts": []}


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


def _frontend_slide_root_reset() -> str:
    """Extract the SLIDE_ROOT_RESET_STYLE template literal from the TS source."""
    src = _FRONTEND_SLIDE_DOC.read_text()
    m = re.search(
        r"export const SLIDE_ROOT_RESET_STYLE = `(.*?)`;", src, re.DOTALL
    )
    assert m, "could not find SLIDE_ROOT_RESET_STYLE in slideDocument.ts"
    return m.group(1)


def test_backend_root_reset_matches_frontend_root_reset():
    # dsv2 cross-review F2: ONE root-slide reset for every surface. If the
    # frontend constant changes, this fails loudly so the backend mirror is
    # updated in lockstep.
    assert SLIDE_ROOT_RESET_STYLE == _frontend_slide_root_reset()


def _frontend_frame_dims() -> tuple[int, int]:
    """The frontend's fixed slide-frame dimensions."""
    src = _FRONTEND_SLIDE_DOC.read_text()
    w = re.search(r"export const SLIDE_FRAME_W = (\d+);", src)
    h = re.search(r"export const SLIDE_FRAME_H = (\d+);", src)
    assert w and h, "could not find SLIDE_FRAME_W/H in slideDocument.ts"
    return int(w.group(1)), int(h.group(1))


def _frontend_host_frame(host_selector: str) -> str:
    """Render the TS `slideHostFrameStyle` body for `host_selector`.

    Substitutes the template literal's interpolations rather than reimplementing
    the rule, so this cannot silently agree with a Python copy that drifted.
    """
    src = _FRONTEND_SLIDE_DOC.read_text()
    m = re.search(
        r"export function slideHostFrameStyle\(hostSelector: string\): string \{\s*"
        r"return `(.*?)`;",
        src,
        re.DOTALL,
    )
    assert m, "could not find slideHostFrameStyle in slideDocument.ts"
    width, height = _frontend_frame_dims()
    return (
        m.group(1)
        .replace("${hostSelector}", host_selector)
        .replace("${SLIDE_FRAME_W}", str(width))
        .replace("${SLIDE_FRAME_H}", str(height))
    )


#: The four EXPORT builders. None of them may inject a slide-host frame contract.
#:
#: A contract framing `body` (or `section.slide-container`) and stretching its
#: CHILD to `position: absolute !important; inset: 0 !important; width/height: 100%
#: !important` was injected into all four at 0.4.2.dev17 and reverted. On the
#: huashu -> PPTX -> Google Slides path it DESTROYS TABLES:
#: preprocess.mjs::flattenTables() re-emits every <td>/<th> as an absolutely
#: positioned <div> whose left/top/width/height are NON-important INLINE styles and
#: appends it to `body`, so a stylesheet !important rule on `body > *` outranks each
#: cell's own position and collapses all of them onto one rect. Measured on a real
#: 21-cell deck: distinct cell rects in ppt/slides/slide1.xml 42 -> 11.
#:
#: There is deliberately NO Python mirror of the rule any more — it existed only to
#: serve build_slide_html. The frontend `slideHostFrameStyle` REMAINS, because the
#: four PREVIEW surfaces still depend on it
#: (tests/unit/test_preview_box_model_parity.py pins those); it simply may not
#: reach an export builder.
_EXPORT_BUILDERS = (
    "src/api/routes/export.py",
    "frontend/src/services/pdf_client.ts",
    "frontend/src/services/screenshotCapture.ts",
    "frontend/src/services/domWalker.ts",
)

#: Substring that appears in a CALL to the contract builder, in either language.
#: Matches `slideHostFrameStyle(` / `slide_host_frame_style(` but NOT the prose in
#: the reverted-comment blocks, which name the function without calling it.
_CONTRACT_CALLS = ("slideHostFrameStyle(", "slide_host_frame_style(")

#: The contract's fingerprint in EMITTED CSS. The `#tellr-host-frame-boost` id is
#: never minted on any element; it exists purely to lift the rule's specificity, so
#: its presence in a document means the contract rendered into it.
_CONTRACT_MARKER = ":not(#tellr-host-frame-boost)"


@pytest.mark.parametrize("rel_path", _EXPORT_BUILDERS)
def test_no_export_builder_injects_the_frame_contract(rel_path):
    """THE REGRESSION GUARD. Reintroducing the contract into a builder fails here.

    Deliberately a source scan and not a document assertion: three of the four
    builders are TypeScript, and the huashu damage is EMIT-TIME (the built document
    is unchanged, so a document-level probe reads 0.00 px and is blind to it).
    Scanning the source is what actually catches the reintroduction.
    """
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / rel_path).read_text(encoding="utf-8")
    for call in _CONTRACT_CALLS:
        assert call not in src, (
            f"{rel_path} injects the slide-host frame contract again. On the huashu "
            "path this collapses every flattened table cell onto one rect "
            "(42 -> 11 distinct rects measured). If a DS-pinned deck's ground needs "
            "fixing on a capture surface, re-aim the capture with findSlideRoot "
            "instead — it injects no CSS."
        )


def test_the_export_builder_scan_is_not_vacuous():
    """Non-vacuity for the guard above: the paths must exist and be readable.

    A renamed builder would make the scan pass against a file that is not there.
    """
    repo_root = Path(__file__).resolve().parents[2]
    for rel_path in _EXPORT_BUILDERS:
        path = repo_root / rel_path
        assert path.is_file(), f"{rel_path} no longer exists — the guard is vacuous"
        assert path.read_text(encoding="utf-8").strip(), f"{rel_path} is empty"

    # And the pattern must be capable of matching: it matches the PREVIEW surface
    # that legitimately still calls the contract builder.
    preview = (
        repo_root / "frontend" / "src" / "components" / "SlidePanel" / "SlideSelection.tsx"
    ).read_text(encoding="utf-8")
    assert "slideHostFrameStyle(" in preview, (
        "the scan pattern no longer matches a known call site, so the guard above "
        "would pass no matter what an export builder does"
    )


def test_the_host_frame_contract_is_not_vacuous():
    """Non-vacuity: the extractor must actually be reading a rule out of the TS.

    A regex that silently matched nothing would make the parity test above pass
    against an empty string on both sides.
    """
    rendered = _frontend_host_frame("body")
    assert "position: relative !important" in rendered
    assert "width: 1280px !important" in rendered
    # The CHILD arm is the load-bearing half — sizing the host alone leaves the
    # background-carrying wrapper collapsed.
    assert "body > :not(#tellr-host-frame-boost):not(.slide-wrapper)" in rendered
    assert "height: 100% !important" in rendered


def test_the_host_frame_contract_cannot_reach_the_standalone_export_wrapper():
    """`.slide-wrapper` is the per-slide block of the standalone MULTI-slide export.

    Stretching those to one frame would stack the whole deck into a single pile, so
    the contract is written to be incapable of it wherever the PREVIEW surfaces
    inject it. Read from the TS source: there is no longer a Python mirror.
    """
    assert ":not(.slide-wrapper)" in _frontend_host_frame("body")


def test_build_slide_html_flattens_the_slide_root_after_deck_css():
    # dsv2 cross-review F2: the old `body > *` reset lost the specificity
    # fight against authored `.slide { margin: 40px auto !important }`, so the
    # huashu render kept the print-preview card offset (and its rounding and
    # shadow) that other surfaces stripped. The shared reset must sit AFTER
    # deck CSS and carry all three flattening declarations.
    slide = {"slide_id": "s1", "html": '<div class="slide">hi</div>'}
    deck = {
        "title": "T",
        "css": ".slide { margin: 40px auto !important; border-radius: 18px !important; }",
        "scripts": "",
        "external_scripts": [],
    }
    html = build_slide_html(slide, deck)
    assert SLIDE_ROOT_RESET_STYLE in html
    assert html.index(SLIDE_ROOT_RESET_STYLE) > html.index(deck["css"])
    assert "border-radius: 0 !important" in html
    assert "box-shadow: none !important" in html


#: A DESIGN-SYSTEM-PINNED deck: the ground is painted by a bare TYPE selector on a
#: <section> wrapper, and the slide root inside it is out of flow. An UNWRAPPED
#: corpus cannot see this defect at all — 0 of 47 pre-existing decks wrap — and a
#: `dark`/`event`/`white` variant class would paint its own ground and be immune,
#: so the fixture carries a BARE class="slide".
_WRAPPED_DECK_CSS = (
    "html, body { background: #0E1A1F; }"
    "section { background: #F9F7F4; color: #3A3838; }"
    ".slide { position: absolute; inset: 0; padding: 72px 88px; }"
)
_WRAPPED_SLIDE = {
    "slide_id": "s1",
    "html": '<section><div class="slide"><h1>Acme</h1></div></section>',
}


def test_build_slide_html_does_not_inject_the_frame_contract():
    """The export document must carry NO frame contract, on a WRAPPED deck too.

    The wrapped fixture is the one the contract was added for, so it is the case
    most likely to tempt a reintroduction. Asserted on the emitted document, which
    is the artifact the huashu sidecar actually consumes.
    """
    html = build_slide_html(_WRAPPED_SLIDE, _deck_with_css(_WRAPPED_DECK_CSS))

    assert _CONTRACT_MARKER not in html, (
        "the frame contract is back in the server slide document; on the huashu "
        "path this collapses every flattened table cell onto one rect"
    )
    # The declarations that did the damage, checked individually: a reintroduction
    # under a different selector would still collapse the cells.
    assert "inset: 0 !important" not in html
    assert "height: 100% !important" not in html


def test_the_post_deck_sheet_carries_only_the_root_reset():
    """WF-03 still holds with the contract gone: 3 sheets, sheet 2 byte-equal.

    `@import` is only valid before every other rule of ITS OWN stylesheet, so a
    single injected declaration in the deck's sheet costs a deck that opens with
    `@import url(fonts.googleapis…)` its webfont. Sheet 2 must stay verbatim.

    Sheet 3 keeps the html/body reset and the shared slide-root reset, and must
    carry no frame contract in any sheet.
    """
    css = f"{_FONT_IMPORT}\n{_WRAPPED_DECK_CSS}"
    html = build_slide_html(_WRAPPED_SLIDE, _deck_with_css(css))
    blocks = re.findall(r"<style>(.*?)</style>", html, re.DOTALL)

    assert len(blocks) == 3, [b[:60] for b in blocks]
    assert blocks[1] == css, "sheet 2 is no longer byte-equal to the deck's CSS"
    assert blocks[1].startswith("@import"), "the deck's leading @import moved"

    for i, block in enumerate(blocks):
        assert _CONTRACT_MARKER not in block, f"the contract is back in sheet {i + 1}"

    # Sheet 3 still does its own job — this is what must NOT be reverted with it.
    assert SLIDE_ROOT_RESET_STYLE in blocks[2]
    assert "margin: 0;" in blocks[2]


def test_build_slide_html_neutralises_deck_authored_body_padding():
    """WM-01: a deck-authored `body { padding }` must not translate the slide.

    The html/body reset is emitted BEFORE the deck, so `body { padding: 48px 0 }`
    — real generator output — won on order and pushed `.slide` to y=48. The .pptx
    then carried that offset on every positioned component (dy 46-48 px) including
    the background rectangle, whose bottom landed at 768 inside a 720 frame: a 48 px
    unpainted band at the top and content pushed past the clip. Measured with the
    shipped builder: `.slide` @ 0,48 on 4 of 4 slides before, 0,0 after.

    The reset is restated AFTER the deck, which is exactly what the frontend
    preview surfaces already do (SLIDE_PREVIEW_RESET_STYLE is appended after deck
    CSS), so the export agrees with what the user saw on screen.
    """
    slide = {"slide_id": "s1", "html": '<div class="slide">hi</div>'}
    deck = {
        "title": "T",
        "css": "body { padding: 48px 0; gap: 48px; } .slide { height: 720px; }",
        "scripts": "",
        "external_scripts": [],
    }
    html = build_slide_html(slide, deck)

    body_reset = "html, body {\n      margin: 0;\n      padding: 0;\n    }"
    assert body_reset in html, "post-deck body reset missing"
    # Order is the whole mechanism: at equal specificity the LATER rule wins.
    assert html.index(body_reset) > html.index(deck["css"])


def test_build_slide_html_body_reset_is_not_in_the_shared_root_reset():
    """The body reset must stay LOCAL to the single-slide export document.

    SLIDE_ROOT_RESET_STYLE is also injected into the standalone MULTI-slide
    export, whose scrolling layout depends on `body { padding: 40px 20px }`.
    Folding a body-padding reset into the shared constant would flatten that
    deck into one pile — and would also break the byte-identity this module
    asserts against the frontend constant.
    """
    assert "body {" not in SLIDE_ROOT_RESET_STYLE
    assert "padding" not in SLIDE_ROOT_RESET_STYLE


def test_external_scripts_carry_no_crossorigin_attribute():
    """WM-02: `crossorigin` blocked Tailwind in the export document.

    It makes these CORS requests; cdn.tailwindcss.com answers 302 with no CORS
    headers, so the request failed net::ERR_FAILED and Preflight never landed —
    DS-OFF headings rendered at a different size and weight in the file than on
    screen (measured: 3 font-size differences and up to 22.50 px of drift, both
    gone once the attribute is dropped). The frontend emits the same tag without
    it and it loads (302 -> 200 /3.4.17, verified).

    Dropping it is only safe while there is NO `integrity` attribute: with SRI
    present, removing `crossorigin` blocks the script outright, which would turn a
    typography drift into no styling at all. This test pins BOTH halves.
    """
    slide = {"slide_id": "s1", "html": "<canvas id='c'></canvas>"}
    deck = {
        "title": "T",
        "css": "",
        "scripts": "",
        "external_scripts": [
            "https://cdn.tailwindcss.com",
            "https://cdn.jsdelivr.net/npm/chart.js",
        ],
    }
    html = build_slide_html(slide, deck)

    script_tags = [
        line for line in html.splitlines() if "<script src=" in line
    ]
    assert script_tags, "external scripts were not emitted at all"
    for tag in script_tags:
        assert "crossorigin" not in tag, tag
        # If SRI is ever added, `crossorigin` becomes REQUIRED again — fail here
        # rather than silently shipping a script the browser will refuse.
        assert "integrity" not in tag, (
            "integrity added without crossorigin — the CDN script will be blocked"
        )


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
