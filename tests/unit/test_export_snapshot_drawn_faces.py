"""The deck names the face the browser drew (Task 15 B8, N4), and symbols every app draws alike.

N4: for a run with no loaded webfont the snapshot wrote its stack's first family,
"Inter" for ``Inter, "SF Pro Display", Helvetica, Arial, sans-serif``, while the
browser drew Helvetica (a Mac) or Liberation Sans (Databricks Apps, with the
sidecar's font bundle). Google drew real Inter, wider than the layout, and
PowerPoint for Mac Calibri, narrower. Now the run names the face the browser
drew (snapshot_text_metrics.mjs resolveWrittenFaces): each token of the stack is
probed alone, on the run's own text, with the coverage probe font after it, so
the first token that draws a character is the one the browser's own font
matching took. That face is written by a name all three apps draw with its
metrics:

* Arial = Helvetica = Liberation Sans = Arimo -> ``Arial``;
* Times New Roman = Times = Liberation Serif = Tinos -> ``Times New Roman``;
* Courier New = Courier = Liberation Mono = Cousine -> ``Courier New``;
* a generic or system face the apps lack (the Mac's system-ui is SF) -> the
  table face the container draws for it: sans-serif and system-ui ``Arial``,
  serif, cursive and fantasy ``Times New Roman``, monospace ``Courier New``;
* a stack nothing draws (fontless text, ``Inter`` alone) -> the standard face,
  ``Times New Roman``;
* a webfont the page loaded later in the stack -> that webfont, named by weight;
* any other face the browser drew (a font installed on the machine) -> itself;
* never the container's base-image DejaVu, a face the page did not load (its
  fontconfig keeps it for per-character fallback and lets no stack name it); a
  webfont the page loaded named DejaVu is the page's own bytes, the face the layout
  was measured in, and is written as itself, as any loaded webfont is.

The global Review Focus 3 holds: ``system-ui, Arial`` at 600 is ``Arial`` plus bold.

Symbols (D8, extended): the characters outside WGL4 that MS PGothic and MS Gothic
draw in both PowerPoint and Google Slides (982 measured, CALIBRATION.md D8) are
written in MS PGothic (MS Gothic for monospace) where the run's written face
lacks them in the apps: always for Arial, Times New Roman and Courier New (bar
the few each draws itself), and for a webfont where the coverage probe says it
lacks them. PowerPoint for Mac otherwise draws them from Segoe UI Symbol, Cambria
Math or Apple Color Emoji at 0.72 to 1.12 em, Google from MS PGothic.

Every expectation that depends on the machine reads the face the browser drew
from the DevTools protocol (``CSS.getPlatformFontsForNode``), independently of
the engine.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator

import pytest
from lxml import etree

from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    Shape,
    browser_face_families,
    browser_loaded_weights,
    export_slides,
    requires_huashu_sidecar,
    slide_document,
    slide_shapes,
)
from tests.unit.test_export_snapshot_lists import LYING_ZERO_PROBES_SCRIPT

pytestmark = [pytest.mark.slow, requires_huashu_sidecar]

DS_OFF_STACK = "Inter, &quot;SF Pro Display&quot;, Helvetica, Arial, sans-serif"
HARVEY = "Legend: ○ lowest · ◔ low · ◑ medium · ◕ high · ● highest"
# Where a paragraph's stack names the page's own face called DejaVu (_slide).
DEJAVU = "@DEJAVU@"
# Characters the page's DejaVu face lacks (it covers ASCII alone): a run of them alone.
DEJAVU_LACKS = "½ ◔"

# (id, inline style, text): each paragraph of the slide.
PARAGRAPHS = (
    ("ds-off", f"font-family: {DS_OFF_STACK};", "Quarterly revenue grew"),
    ("system-ui", "font-family: system-ui;", "System face text"),
    ("system-arial", "font-family: system-ui, Arial; font-weight: 600;", "System Arial bold"),
    ("fontless", "font-family: initial;", "Fontless text"),
    ("inter", "font-family: Inter;", "Inter alone"),
    (
        "brand",
        "font-family: &quot;Brand Sans Missing&quot;, &quot;DM Sans&quot;, sans-serif; "
        "font-weight: 600;",
        "Brand falls back caf\u00e9",
    ),
    ("dejavu", f"font-family: &quot;{DEJAVU}&quot;, Arial;", "DejaVu named"),
    (
        "dejavu-later",
        f"font-family: &quot;Missing Face&quot;, &quot;{DEJAVU}&quot;, sans-serif;",
        "DejaVu later in the stack",
    ),
    ("dejavu-lacks", f"font-family: &quot;{DEJAVU}&quot;, Arial;", DEJAVU_LACKS),
    ("serif-first", "font-family: serif, Arial;", "Serif comes first"),
    (
        "arimo-webfont",
        "font-family: &quot;Missing Face&quot;, Arimo, sans-serif;",
        "Arimo webfont text",
    ),
    ("mono", "font-family: monospace;", "Generic mono"),
    ("cursive", "font-family: cursive;", "Cursive text"),
    (
        "platform",
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;",
        "Platform stack",
    ),
    ("menlo", "font-family: &quot;SF Mono&quot;, Menlo, monospace;", "Mono stack"),
    ("georgia", "font-family: Georgia, serif;", "Georgia stack"),
    ("harvey", "font-family: initial;", HARVEY),
    ("harvey-mono", "font-family: monospace;", "Mono ○◔ ● end"),
    ("symbols", "", "Status ◆ done ✓ ok"),
    ("won-arial", "font-family: Arial;", "Price ₩5 here"),
    ("won-webfont", "", "Cost ₩7 now"),
)
# A webfont the page loads whose name the metric table holds (here a local() alias of
# Arial): a loaded webfont keeps its own name, as every webfont does.
ARIMO_FACE = (
    "<style>@font-face { font-family: 'Arimo'; "
    "src: local('Arial'), local('Liberation Sans'); }</style>"
)


def _slide(dejavu: str) -> str:
    """The slide, the page's own face that its DejaVu paragraphs name called ``dejavu``.

    That face is a webfont the page loads, a local() alias of Arial for ASCII alone, named
    as the export's container names its base image's DejaVu.
    """
    face = (
        f"<style>@font-face {{ font-family: '{dejavu}'; "
        "src: local('Helvetica'), local('Arial'), local('Liberation Sans'); "
        "unicode-range: U+0000-007F; }</style>"
    )
    return (
        '<div class="slide">'
        + face
        + ARIMO_FACE
        + "".join(
            f'<p id="{element_id}" style="{style.replace(DEJAVU, dejavu)} font-size: 20px; '
            f'margin: 0 0 4px;">{text}</p>'
            for element_id, style, text in PARAGRAPHS
        )
        + '<table id="cell-table" style="border-collapse: collapse; font-size: 16px;">'
        f'<tr><td id="empty-cell" style="font-family: {DS_OFF_STACK}; width: 80px; height: 24px;">'
        "</td><td>Filled</td></tr></table>"
        "</div>"
    )


SLIDE = _slide("DejaVu Sans")
# The same slide, its DejaVu face a webfont of another name, which no rule singles out.
TWIN_FACE = "Twin Sans"
TWIN_SLIDE = _slide(TWIN_FACE)
# The same slide whose script replaces the page realm's FontFace and FontFaceSet methods.
HOSTILE_SLIDE = (
    "<script>"
    "window.FontFace = function () { throw new Error('no FontFace'); };"
    "const set = Object.getPrototypeOf(document.fonts);"
    "set.add = function () { throw new Error('no add'); };"
    "set.delete = function () { throw new Error('no delete'); };"
    "</script>" + SLIDE
)

# The metric-compatible families, by the platform family the browser drew.
METRIC_FACES = {
    "arial": "Arial",
    "helvetica": "Arial",
    "liberation sans": "Arial",
    "arimo": "Arial",
    "times new roman": "Times New Roman",
    "times": "Times New Roman",
    "liberation serif": "Times New Roman",
    "tinos": "Times New Roman",
    "courier new": "Courier New",
    "courier": "Courier New",
    "liberation mono": "Courier New",
    "cousine": "Courier New",
}


def _written_for(drawn: str) -> str:
    """The typeface a face the browser drew is written as: macOS's hidden system faces
    (``.SF NS``, system-ui's) as the face the container draws for system-ui, Arial."""
    if drawn.startswith("."):
        return "Arial"
    return METRIC_FACES.get(drawn.lower(), drawn)


@pytest.fixture(scope="module")
def decks() -> Iterator[dict[str, bytes]]:
    """The slide, its hostile twin and its renamed twin, exported once for each target."""
    exported = {}
    with pytest.MonkeyPatch.context() as monkeypatch:
        for target in ("pptx", "gslides"):
            exported[target], failures = export_slides(
                [SLIDE, HOSTILE_SLIDE, TWIN_SLIDE],
                css=DECK_CSS,
                monkeypatch=monkeypatch,
                target=target,
            )
            assert failures == [], f"the export rejected the slide: {failures}"
    yield exported


@pytest.fixture(scope="module")
def document() -> str:
    return slide_document(SLIDE, css=DECK_CSS, slide_id="snapshot-1")


def _box(shapes: list[Shape], fragment: str) -> Shape:
    matches = [shape for shape in shapes if shape.paras and fragment in shape.text]
    assert len(matches) == 1, f"{len(matches)} text boxes hold {fragment!r}"
    return matches[0]


def _runs(shape: Shape) -> list[tuple[str, str | None, bool]]:
    return [
        (run.text, run.typeface, run.bold)
        for paragraph in shape.paras
        for run in paragraph.runs
        if run.text
    ]


def _faces(shape: Shape) -> set[str | None]:
    return {typeface for text, typeface, _ in _runs(shape) if text.strip()}


def _first_cell_mark_typeface(deck: bytes) -> str | None:
    """The typeface of the paragraph mark (a:endParaRPr) of slide 1's first table cell."""
    with zipfile.ZipFile(io.BytesIO(deck)) as archive:
        slide = etree.fromstring(archive.read("ppt/slides/slide1.xml"))
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    cells = slide.findall(f".//{a}tbl/{a}tr/{a}tc")
    assert cells, "slide 1 has no table cell"
    latin = cells[0].find(f"{a}txBody/{a}p/{a}endParaRPr/{a}latin")
    return None if latin is None else latin.get("typeface")


def _drawn(document: str, element_id: str) -> str:
    families = browser_face_families(document, f"#{element_id}")
    assert families, f"the browser drew no face for #{element_id}"
    return families[0]


def _webfont_lacks(character: str) -> bool:
    """Whether the deck's DM Sans draws ``character`` from another face: the face the browser
    drew it in, from the protocol, for a paragraph of that one character in DM Sans alone."""
    guard = slide_document(
        '<div class="slide"><p id="guard" style="font-family: &quot;DM Sans&quot;;">'
        f"{character}</p></div>",
        css=DECK_CSS,
        slide_id="snapshot-guard",
    )
    families = browser_face_families(guard, "#guard")
    return not (families and families[0].startswith("DM Sans"))


class TestTheWrittenFaceIsTheFaceDrawn:
    @pytest.mark.parametrize(
        ("element_id", "fragment", "typeface", "bold"),
        [
            pytest.param("ds-off", "Quarterly", "Arial", False, id="ds-off-stack"),
            pytest.param("system-ui", "System face", "Arial", False, id="system-ui"),
            pytest.param("system-arial", "System Arial", "Arial", True, id="review-focus-3"),
            pytest.param("fontless", "Fontless", "Times New Roman", False, id="fontless"),
            pytest.param("inter", "Inter alone", "Times New Roman", False, id="nothing-draws"),
            pytest.param("mono", "Generic mono", "Courier New", False, id="monospace"),
            pytest.param("cursive", "Cursive", "Times New Roman", False, id="cursive"),
            pytest.param("platform", "Platform stack", "Arial", False, id="platform-stack"),
            pytest.param(
                "serif-first", "Serif comes", "Times New Roman", False, id="generic-in-order"
            ),
        ],
    )
    def test_the_face_drawn_is_written_by_its_metric_compatible_name(
        self,
        decks: dict[str, bytes],
        document: str,
        element_id: str,
        fragment: str,
        typeface: str,
        bold: bool,
    ) -> None:
        """Each paragraph is one run in the typeface the face the browser drew is written as,
        in both decks. The drawn face is read from the protocol, and the expectation checked
        against it, except for the generics the container sets in its own faces (cursive)."""
        drawn = _drawn(document, element_id)
        if element_id != "cursive":
            assert _written_for(drawn) == typeface, (
                f"fixture drift: #{element_id} is drawn in {drawn!r}, written as "
                f"{_written_for(drawn)!r}, not {typeface!r}"
            )
        for target, deck in decks.items():
            runs = _runs(_box(slide_shapes(deck, 0), fragment))
            wrong = [run for run in runs if run[1:] != (typeface, bold)]
            assert not wrong, (
                f"{target}: #{element_id} (drawn in {drawn!r}) must be {typeface!r} with "
                f"bold={bold}: {runs}"
            )

    @pytest.mark.parametrize(
        ("element_id", "fragment"),
        [
            pytest.param("menlo", "Mono stack", id="menlo"),
            pytest.param("georgia", "Georgia", id="georgia"),
        ],
    )
    def test_a_face_installed_on_the_machine_is_written_as_itself_or_its_table_name(
        self, decks: dict[str, bytes], document: str, element_id: str, fragment: str
    ) -> None:
        """Menlo or Georgia where the machine has it (a Mac), the stack's generic where not."""
        typeface = _written_for(_drawn(document, element_id))
        for target, deck in decks.items():
            faces = _faces(_box(slide_shapes(deck, 0), fragment))
            assert faces == {typeface}, (
                f"{target}: #{element_id} is written {faces}, not {typeface}"
            )

    def test_a_loaded_webfont_later_in_the_stack_is_written_by_its_weight(
        self, decks: dict[str, bytes], document: str
    ) -> None:
        """``"Brand Sans Missing", "DM Sans", sans-serif`` at 600, DM Sans loaded: DM Sans
        SemiBold, as a first-family DM Sans would be, never the missing brand face."""
        drawn = _drawn(document, "brand")
        assert drawn.startswith("DM Sans"), f"fixture drift: #brand is drawn in {drawn!r}"
        for target, deck in decks.items():
            runs = _runs(_box(slide_shapes(deck, 0), "Brand falls"))
            assert runs == [("Brand falls back caf\u00e9", "DM Sans SemiBold", False)], (
                f"{target}: {runs}"
            )

    def test_a_loaded_webfont_whose_name_the_table_holds_keeps_its_name(
        self, decks: dict[str, bytes]
    ) -> None:
        """The metric table maps the faces of runs with no loaded webfont alone: a webfont the
        page loaded named Arimo is written Arimo, by the webfont rules, never Arial."""
        for target, deck in decks.items():
            runs = _runs(_box(slide_shapes(deck, 0), "Arimo webfont"))
            assert runs == [("Arimo webfont text", "Arimo", False)], f"{target}: {runs}"

    def test_a_loaded_webfont_named_dejavu_is_written_as_itself(
        self, decks: dict[str, bytes], document: str
    ) -> None:
        """A webfont the page loaded named DejaVu is the page's own bytes, the same on a laptop
        and on Apps, and the face the layout was measured in: it is written by its own name,
        first in its stack or later, as any loaded webfont is. A run of characters it lacks
        alone keeps it too, as every webfont's run does: ½ (WGL4) is written in the run's
        fallback face, Arial, and ◔ in MS PGothic (D8). Only the container's own DejaVu, a face
        the page did not load, is never written; the sidecar's fontconfig keeps it from every
        stack (test_huashu_font_bundle.py)."""
        assert "DejaVu Sans" in browser_loaded_weights(document), (
            "fixture drift: the page's DejaVu Sans is no loaded webfont"
        )
        for target, deck in decks.items():
            shapes = slide_shapes(deck, 0)
            assert _runs(_box(shapes, "DejaVu named")) == [
                ("DejaVu named", "DejaVu Sans", False)
            ], target
            assert _runs(_box(shapes, "DejaVu later")) == [
                ("DejaVu later in the stack", "DejaVu Sans", False)
            ], target
            assert _runs(_box(shapes, DEJAVU_LACKS)) == [
                ("½", "Arial", False),
                (" ", "DejaVu Sans", False),
                ("◔", "MS PGothic", False),
            ], target

    def test_a_loaded_webfont_named_dejavu_is_written_as_one_of_any_other_name(
        self, decks: dict[str, bytes]
    ) -> None:
        """The slide again with the page's DejaVu face named Twin Sans: every text box is written
        alike, the name aside. That includes a run of characters the face lacks alone (½ ◔),
        which keeps its loaded webfont as its face, as every webfont's run does, its characters
        written as D8 says."""
        for target, deck in decks.items():
            named = [_runs(shape) for shape in slide_shapes(deck, 0) if shape.paras]
            renamed = [
                [
                    (text, "DejaVu Sans" if typeface == TWIN_FACE else typeface, bold)
                    for text, typeface, bold in _runs(shape)
                ]
                for shape in slide_shapes(deck, 2)
                if shape.paras
            ]
            assert any(DEJAVU_LACKS in "".join(run[0] for run in runs) for runs in named), (
                f"fixture drift: {target} has no box of {DEJAVU_LACKS!r}"
            )
            assert renamed == named, target

    def test_a_table_cells_own_face_is_the_face_drawn(self, decks: dict[str, bytes]) -> None:
        """The empty cell's face, its paragraph mark's, is Arial, not the stack's first family."""
        for target, deck in decks.items():
            assert _first_cell_mark_typeface(deck) == "Arial", target

    def test_a_page_that_replaces_its_font_api_is_written_as_the_plain_slide(
        self, decks: dict[str, bytes]
    ) -> None:
        """Hostile slide script: the probes add the coverage font through the pristine realm."""
        for target, deck in decks.items():
            plain = {
                fragment: _runs(_box(slide_shapes(deck, 0), fragment))
                for fragment in ("Quarterly", "Fontless", "Legend", "Status")
            }
            hostile = {fragment: _runs(_box(slide_shapes(deck, 1), fragment)) for fragment in plain}
            assert hostile == plain, f"{target}: the hostile slide is written {hostile}"

    def test_a_run_whose_probes_all_measure_nothing_keeps_its_stacks_first_family(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A page whose every offscreen probe measures no width writes ``Georgia, serif`` as Georgia.

        Its slide script makes each probe report zero sizes (as one the page
        hid would), so no probe says which family drew the run: the run keeps
        its stack's first family, as it does when the probes cannot be read
        at all. Taking that as "nothing in the stack drew it" writes serif's
        table face, Times New Roman.
        """
        slide = (
            '<div class="slide"><p id="georgia" style="font-family: Georgia, serif; font-size: 20px;">'
            f"Georgia stack</p><script>{LYING_ZERO_PROBES_SCRIPT}</script></div>"
        )
        deck, failures = export_slides([slide], css=DECK_CSS, monkeypatch=monkeypatch)
        assert failures == [] and deck, f"the export rejected the slide: {failures}"

        assert _faces(_box(slide_shapes(deck, 0), "Georgia stack")) == {"Georgia"}


class TestSymbolsAreWrittenInAFaceEveryAppDraws:
    def test_harvey_quarters_in_a_serif_run_are_ms_pgothic(self, decks: dict[str, bytes]) -> None:
        """Fontless text (Times New Roman): ○ and ● are WGL4, which Times New Roman draws in
        every app; ◔◑◕ are not, so each is an MS PGothic run of its own."""
        expected = [
            ("Legend: ○ lowest · ", "Times New Roman", False),
            ("◔", "MS PGothic", False),
            (" low · ", "Times New Roman", False),
            ("◑", "MS PGothic", False),
            (" medium · ", "Times New Roman", False),
            ("◕", "MS PGothic", False),
            (" high · ● highest", "Times New Roman", False),
        ]
        for target, deck in decks.items():
            assert _runs(_box(slide_shapes(deck, 0), "Legend")) == expected, target

    def test_a_monospace_runs_symbols_are_ms_gothic(self, decks: dict[str, bytes]) -> None:
        for target, deck in decks.items():
            assert _runs(_box(slide_shapes(deck, 0), "Mono ○")) == [
                ("Mono ○", "Courier New", False),
                ("◔", "MS Gothic", False),
                (" ● end", "Courier New", False),
            ], target

    def test_symbols_a_webfont_lacks_are_ms_pgothic(self, decks: dict[str, bytes]) -> None:
        """DM Sans lacks ◆ and ✓ (guarded): each is an MS PGothic run, the rest DM Sans."""
        for character in "◆✓":
            assert _webfont_lacks(character), f"fixture drift: DM Sans has {character}"
        for target, deck in decks.items():
            assert _runs(_box(slide_shapes(deck, 0), "Status")) == [
                ("Status ", "DM Sans", False),
                ("◆", "MS PGothic", False),
                (" done ", "DM Sans", False),
                ("✓", "MS PGothic", False),
                (" ok", "DM Sans", False),
            ], target

    def test_a_symbol_the_table_face_draws_itself_stays_in_its_run(
        self, decks: dict[str, bytes]
    ) -> None:
        """₩ is one of the 19 symbols Arial draws itself in both apps: an Arial run keeps it,
        and a webfont that lacks it (guarded) writes it in Arial, its generic's table face."""
        assert _webfont_lacks("₩"), "fixture drift: DM Sans has ₩"
        for target, deck in decks.items():
            shapes = slide_shapes(deck, 0)
            assert _runs(_box(shapes, "Price")) == [("Price ₩5 here", "Arial", False)], target
            assert _runs(_box(shapes, "Cost")) == [
                ("Cost ", "DM Sans", False),
                ("₩", "Arial", False),
                ("7 now", "DM Sans", False),
            ], target
