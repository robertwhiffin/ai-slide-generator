"""WC-02: every slide preview surface must use the SAME box model.

MEASURED: SlideSelection and PresentationMode each supply
``* { box-sizing: border-box }`` in their reset, while SLIDE_PREVIEW_RESET_STYLE
(SlideTile + VisualEditorPanel) and the template pop-out's preview document did
not. On reference-architecture #2 the tile-vs-selection difference was 91,146 px in
BOTH the dsv5 and dsv6 builds — pre-existing and identical, not a regression of
this branch.

WHICH RENDERING IS WRONG matters here: the correct one is already border-box, since
two of the four surfaces supply it and the uploaded templates were therefore
authored under it. So the fix moves the two surfaces that DISAGREED, and the
controlled experiment confirms it moves them onto the selection rendering rather
than the other way round: refarch #2/#3/#4/#5 go from 2 distinct renderings to all
four identical, with the SlideSelection screenshot hash unchanged, and corporate #2
was already identical.

GENERATED decks are unaffected — their own CSS sets box-sizing, which is why Wave M
measured every generated deck at 0.00 px across all four surfaces. Confirmed as a
provable no-op: all four audited decks are byte-identical on every surface before
and after. The gap bit only TEMPLATE slides, which rely on the host reset.

Source-level assertions, in the idiom test_export_csp.py already uses to read
slideDocument.ts (the frontend has no unit runner). The pixel proof lives in the
harness run recorded with the fix.
"""
from pathlib import Path

import pytest

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
_SLIDE_DOCUMENT = _FRONTEND / "services" / "slideDocument.ts"
_PREVIEW_DOC = _FRONTEND / "components" / "config" / "templatePreviewDoc.ts"
_SLIDE_SELECTION = _FRONTEND / "components" / "SlidePanel" / "SlideSelection.tsx"
_PRESENTATION = _FRONTEND / "components" / "PresentationMode" / "PresentationMode.tsx"

#: Tolerated spellings of the universal border-box reset.
_BORDER_BOX_FORMS = (
    "* { box-sizing: border-box; }",
    "*{box-sizing:border-box}",
    "box-sizing: border-box;",
)


def _declares_border_box(source: str) -> bool:
    return any(form in source for form in _BORDER_BOX_FORMS)


@pytest.fixture(scope="module")
def slide_document() -> str:
    return _SLIDE_DOCUMENT.read_text(encoding="utf-8")


def _preview_reset_block(slide_document: str) -> str:
    start = slide_document.index("export const SLIDE_PREVIEW_RESET_STYLE")
    return slide_document[start : slide_document.index("`;", start)]


def test_the_shared_preview_reset_declares_border_box(slide_document):
    """SlideTile + VisualEditorPanel render through this constant."""
    assert _declares_border_box(_preview_reset_block(slide_document))


def test_the_popout_preview_document_declares_border_box():
    """The surface the user complained about: the template pop-out lacked it too."""
    source = _PREVIEW_DOC.read_text(encoding="utf-8")
    start = source.index("export const PREVIEW_RESET_STYLE")
    assert _declares_border_box(source[start : source.index("\n\n", start)])


@pytest.mark.parametrize(
    "path,surface",
    [(_SLIDE_SELECTION, "SlideSelection"), (_PRESENTATION, "PresentationMode")],
)
def test_the_two_surfaces_that_were_already_correct_still_are(path, surface):
    """Non-vacuity for the whole finding: these two are the REFERENCE rendering.
    If they ever stop declaring it, the parity above would be agreement on the
    WRONG box model."""
    assert _declares_border_box(path.read_text(encoding="utf-8")), surface


def test_the_export_path_is_untouched(slide_document):
    """GUARDRAIL 13C. The standalone MULTI-slide export builder carries its OWN
    reset and must not pick this up from the preview constant — its layout was
    measured at 0.00 px on 18/18 slides and must stay there. The preview reset has
    exactly two consumers, neither of them an export path."""
    consumers = [
        p
        for p in (_FRONTEND).rglob("*.tsx")
        if "SLIDE_PREVIEW_RESET_STYLE" in p.read_text(encoding="utf-8")
        and "extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE" in p.read_text(encoding="utf-8")
    ]
    assert {p.name for p in consumers} == {"SlideTile.tsx", "VisualEditorPanel.tsx"}

    # The standalone export's wrapper style is a separate block that already had
    # its own border-box line, and it must not reference the preview constant.
    wrapper_start = slide_document.index("const wrapperStyle = `")
    wrapper = slide_document[wrapper_start : slide_document.index("`;", wrapper_start)]
    assert "SLIDE_PREVIEW_RESET_STYLE" not in wrapper
    assert _declares_border_box(wrapper)
