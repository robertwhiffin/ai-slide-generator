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

GENERATED decks are unaffected either way — their own CSS sets box-sizing, which
is why they measured byte-identical before and after. The gap bit only TEMPLATE
slides, which rely on the host reset.
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


def test_the_export_path_is_untouched(slide_document):
    """GUARDRAIL 13C/G4, unchanged by the correction. The standalone MULTI-slide
    export carries its OWN reset and is NOT a preview surface: its universal
    block is legitimate (it lays out a scrolling stack of slides, not one framed
    slide against GT) and it was measured at 0.00 px on 95/95 components. The
    preview reset has exactly two consumers, neither an export path."""
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
    assert _universal_box_sizing_rules(wrapper) != []
