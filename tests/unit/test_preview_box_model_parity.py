"""WC-02, CORRECTED: every slide preview surface must use the box model the
CLAUDE DESIGN GROUND TRUTH uses — which is CONTENT-box for slide content.

WHAT THIS FILE USED TO PIN, AND WHY THAT WAS WRONG. The first version of this
test asserted that all four preview resets DECLARE a universal
``* { box-sizing: border-box }``, on the stated premise that "the correct
rendering is already border-box, because SlideSelection and PresentationMode
supply it, so uploaded templates were authored under it". That premise was
FALSIFIED by measurement:

  * the templates' own ``index.html`` declares NO ``box-sizing`` at all;
  * their ``deck-stage.js`` (73,974 B, byte-identical across all four families)
    declares it only SCOPED — ``::slotted(*)`` twice, from inside the shadow
    root, plus its own ``.rail`` chrome. Its one universal ``*`` rule is a
    print-color-adjust rule. So slide content is CONTENT-box in Claude Design;
  * the two surfaces the premise treated as the reference were themselves
    ~91,034 px away from ground truth, in dsv5 AND dev13 alike.

Adding the universal declaration therefore bought cross-surface agreement by
moving all four surfaces AWAY from ground truth: C6 (pop-out vs the template
rendered by its own authentic ``deck-stage.js``) went 0 -> 283,317 / 29,491,200
differing pixels on 7 slides, and GT-faithful surfaces went 3/5 -> 0/5.

THE CORRECTED REFERENCE. Removing the UNIVERSAL block from all four resets while
KEEPING the SCOPED one that mirrors ``::slotted(*)`` satisfies both definitions
at once: 0 px vs GT on all four surfaces, cross-surface parity retained, and
generated decks byte-identical on 40/40 cells.

WHY BOTH HALVES ARE PINNED BELOW. Inter-surface agreement is NECESSARY BUT NOT
SUFFICIENT — that is the whole lesson of the regression, because the falsified
version of this file was GREEN while all four surfaces agreed on the wrong box
model. So the surfaces must agree (``test_all_four_preview_surfaces_agree``) AND
agree on ground truth (``test_and_they_agree_on_the_ground_truth_box_model``). A
future "fix" that restores parity by re-adding the universal block to all four
satisfies the first and FAILS the second, which is exactly the regression this
file now exists to catch.

SCOPE, stated honestly: these are SOURCE-level assertions, in the idiom
test_export_csp.py already uses to read slideDocument.ts (the frontend has no
unit runner), and the ground-truth bundle is not vendored into this repo. This
file pins the invariant GT implies and the direction of the reference; the pixel
proof lives in the harness run recorded with the fix.

"GENERATED DECKS ARE UNAFFECTED EITHER WAY" — this file used to close with that
claim, on the grounds that a generated deck's own CSS sets box-sizing, and it is
FALSE as stated. Of the 46 live decks, 29 declare a UNIVERSAL box-sizing rule and
are genuinely immune; the other 17 declare one only SCOPED (`.slide { … }`), so
their descendants take whatever the host injects. Measuring only decks of the
first kind is what produced an earlier "0.00 px on 95/95 components" result and
hid a live 40-72 px divergence — see
``test_the_export_documents_use_the_same_box_model_as_the_previews``. A corpus
that cannot distinguish the two classes cannot answer this question at all.
"""
import re
from pathlib import Path

import pytest

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
_SLIDE_DOCUMENT = _FRONTEND / "services" / "slideDocument.ts"
_PREVIEW_DOC = _FRONTEND / "components" / "config" / "templatePreviewDoc.ts"
_SLIDE_SELECTION = _FRONTEND / "components" / "SlidePanel" / "SlideSelection.tsx"
_PRESENTATION = _FRONTEND / "components" / "PresentationMode" / "PresentationMode.tsx"

#: A universal-selector rule, captured with its declaration list. Matching the
#: BLOCK rather than one spelling of one declaration is deliberate: it catches
#: the reset coming back in a different shape (extra declarations, minified, or
#: broken across lines) instead of only the three spellings that shipped.
_UNIVERSAL_RULE_RE = re.compile(r"\*\s*\{([^{}]*)\}")


def _universal_box_sizing_rules(css: str) -> list[str]:
    """Every universal rule in `css` that sets `box-sizing`."""
    return [
        body.strip()
        for body in _UNIVERSAL_RULE_RE.findall(css)
        if "box-sizing" in body
    ]


@pytest.fixture(scope="module")
def slide_document() -> str:
    return _SLIDE_DOCUMENT.read_text(encoding="utf-8")


def _preview_reset_block(slide_document: str) -> str:
    """The SLIDE_PREVIEW_RESET_STYLE literal (SlideTile + VisualEditorPanel)."""
    start = slide_document.index("export const SLIDE_PREVIEW_RESET_STYLE")
    return slide_document[start : slide_document.index("`;", start)]


def _popout_reset_block() -> str:
    """The template pop-out's PREVIEW_RESET_STYLE literal."""
    source = _PREVIEW_DOC.read_text(encoding="utf-8")
    start = source.index("export const PREVIEW_RESET_STYLE")
    return source[start : source.index("\n\n", start)]


def _host_frame_block(slide_document: str) -> str:
    """The body of `slideHostFrameStyle` — the SCOPED mirror of `::slotted(*)`."""
    start = slide_document.index("export function slideHostFrameStyle")
    return slide_document[start : slide_document.index("\n}", start)]


def _inline_reset_literal(path: Path, declaration: str) -> str:
    """The body of a ``const <declaration> = `...`;`` template literal.

    SlideSelection and PresentationMode build their reset inline rather than as
    an exported constant. Only the LITERAL is returned, never the whole file:
    these components now carry comments that quote the forbidden declaration in
    order to explain why it is forbidden, and a file-wide scan would match the
    explanation. (The same trap `stripCssImports` is written to avoid — a
    text-level pattern matches anything SHAPED like the construct.)
    """
    source = path.read_text(encoding="utf-8")
    anchor = f"const {declaration} = `"
    start = source.index(anchor) + len(anchor)
    return source[start : source.index("`;", start)]


def _four_preview_resets(slide_document: str) -> dict[str, str]:
    """The four preview surfaces' resets, by surface name."""
    return {
        "SlideTile+VisualEditorPanel": _preview_reset_block(slide_document),
        "template pop-out": _popout_reset_block(),
        "SlideSelection": _inline_reset_literal(_SLIDE_SELECTION, "resetStyle"),
        "PresentationMode": _inline_reset_literal(_PRESENTATION, "extraHeadStyle"),
    }


def test_all_four_preview_surfaces_agree(slide_document):
    """The VALID half of WC-02: the four surfaces must not disagree on the box
    model. Necessary, but — as the falsified premise proved — NOT sufficient on
    its own, which is why the next test pins the DIRECTION they agree on."""
    declared = {
        surface: _universal_box_sizing_rules(css)
        for surface, css in _four_preview_resets(slide_document).items()
    }
    assert len({bool(rules) for rules in declared.values()}) == 1, (
        "preview surfaces disagree on whether they declare a universal "
        f"box-sizing reset: {declared}"
    )


@pytest.mark.parametrize(
    "surface",
    ["SlideTile+VisualEditorPanel", "template pop-out", "SlideSelection", "PresentationMode"],
)
def test_and_they_agree_on_the_ground_truth_box_model(slide_document, surface):
    """THE PART THAT ACTUALLY MATTERS. Ground truth — not inter-surface
    agreement — is the reference, and ground truth lays slide content out in
    CONTENT-box: no preview surface may declare a UNIVERSAL box-sizing reset.

    All four are asserted, including the two that carried it before WC-02: they
    were never the reference, and dev13's C6 of 0 px held only because C6
    measures the POP-OUT, which was content-box at the time."""
    reset = _four_preview_resets(slide_document)[surface]
    assert _universal_box_sizing_rules(reset) == [], (
        f"{surface} declares a universal box-sizing reset; slide content is "
        "CONTENT-box in Claude Design (deck-stage.js scopes it to ::slotted(*))"
    )


def test_the_scoped_stage_container_declaration_is_retained(slide_document):
    """The other half of the corrected direction: dropping the universal block
    must NOT drop the SCOPED one. This rule is the in-app mirror of the
    ``::slotted(*)`` block every shipped `deck-stage.js` applies to the stage's
    direct children, so removing it would move the preview AWAY from ground
    truth just as surely as the universal block did."""
    host_frame = _host_frame_block(slide_document)
    assert "box-sizing: border-box !important;" in host_frame

    # Scoped to the host's CHILD, never universal — that scope is the mirror.
    assert _universal_box_sizing_rules(host_frame) == []
    assert "> :not(#tellr-host-frame-boost):not(.slide-wrapper)" in host_frame

    # The mirrored set, as deck-stage.js declares it on ::slotted(*).
    for declaration in ("position: absolute", "inset: 0", "width: 100%", "height: 100%"):
        assert declaration in host_frame, declaration


def test_every_preview_surface_routes_its_frame_through_the_shared_contract(slide_document):
    """Non-vacuity for the test above: it only protects the four surfaces if all
    four actually get their box model FROM `slideHostFrameStyle` rather than
    declaring one of their own."""
    assert "${slideHostFrameStyle('body')}" in _preview_reset_block(slide_document)
    assert "slideHostFrameStyle(" in _PREVIEW_DOC.read_text(encoding="utf-8")
    assert "${slideHostFrameStyle('body')}" in _SLIDE_SELECTION.read_text(encoding="utf-8")
    assert "${slideHostFrameStyle('.slide-container')}" in _PRESENTATION.read_text(
        encoding="utf-8"
    )


def test_the_preview_reset_has_exactly_two_consumers(slide_document):
    """Neither of them an export path, so the preview reset and the export resets
    stay separately attributable."""
    consumers = [
        p
        for p in (_FRONTEND).rglob("*.tsx")
        if "SLIDE_PREVIEW_RESET_STYLE" in p.read_text(encoding="utf-8")
        and "extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE" in p.read_text(encoding="utf-8")
    ]
    assert {p.name for p in consumers} == {"SlideTile.tsx", "VisualEditorPanel.tsx"}

    wrapper_start = slide_document.index("const wrapperStyle = `")
    wrapper = slide_document[wrapper_start : slide_document.index("`;", wrapper_start)]
    assert "SLIDE_PREVIEW_RESET_STYLE" not in wrapper


def test_the_export_documents_use_the_same_box_model_as_the_previews(slide_document):
    """WHAT THIS ASSERTION USED TO SAY, AND WHY IT WAS WRONG.

    It used to assert the OPPOSITE — that the standalone export's wrapper still
    DOES declare a universal box-sizing reset — on the stated premise that the
    export "lays out a scrolling stack of slides, not one framed slide against
    GT", citing 0.00 px on 95/95 components. That corpus could not see the defect:
    EVERY deck in it declared a universal reset of its OWN, which masks the
    injected one. Across the 46 live decks, 29 are immune for exactly that reason
    and 17 declare `box-sizing` only SCOPED — and those 17 are the exposed ones.

    So f19627d, which correctly removed the universal reset from the four PREVIEW
    resets, left slide descendants CONTENT-box on screen and BORDER-box in the
    export. Measured on `.step-card`: UI w=256 vs export w=220 at identical
    padding; MAX component drift 40-72 px on 6 live slides, and 230 elements
    disagreeing on computed `box-sizing`. Scoping the reset to `html, body` — the
    shape the previews already use — returns all 6 to 0.00 px and leaves the 29
    immune decks at 0.00 px.

    BOTH document builders are asserted. They are separate implementations (TS for
    the standalone "Save as HTML" export, Python for the PPTX / huashu /
    Google-Slides path) and BOTH carried the rule, so fixing one alone would look
    closed while the other still diverged (69.87 px on the same slides).
    """
    wrapper_start = slide_document.index("const wrapperStyle = `")
    wrapper = slide_document[wrapper_start : slide_document.index("`;", wrapper_start)]
    assert _universal_box_sizing_rules(wrapper) == [], (
        "buildStandaloneDeckDocument declares a universal box-sizing reset; slide "
        "content is CONTENT-box on every preview surface, so the export diverges"
    )
    # The scoped replacement must actually be there — dropping the universal rule
    # without it leaves `html, body { width: 100% }` plus `body { padding }` to
    # overflow the page by 40px and shift the slide card 20px.
    assert "html, body {" in wrapper
    assert "box-sizing: border-box;" in wrapper

    # The Python builder, asserted on the RENDERED document rather than on source
    # text: its resets live in an f-string where every brace is doubled, so a
    # source-level regex for `* { … }` would not match the rule even if present.
    from src.api.routes.export import build_slide_html

    document = build_slide_html(
        {"slide_id": "s1", "html": '<div class="slide">x</div>', "scripts": ""},
        {"css": ".slide { color: red }", "title": "t", "external_scripts": [], "scripts": ""},
    )
    assert _universal_box_sizing_rules(document) == [], (
        "build_slide_html injects a universal box-sizing reset; the PPTX/huashu "
        "export document must use the previews' box model too"
    )
