"""The export fidelity harness's raster of PowerPoint's PDF, and its ``summary.md``.

``scripts/export_fidelity/run.py`` scores each slide against the browser's own
rendering of it:

* **The PDF raster.** PowerPoint's PDF embeds each picture at twice its slide
  size, with an alpha mask and ``/Interpolate true``. MuPDF drawing such a page
  at the slide's own 1280 px draws a picture's 1 px rules dark and a fringe
  round a mark in the ground's own colour, which neither the UI nor Apple's
  Quartz drawing the same PDF shows (Task 14 Phase A, H1). So the harness
  draws every page at ``PDF_RASTER_SCALE`` (4) times the slide's size and
  box-filters it down to 1280x720, each pixel the mean of the 16 it covers
  (``rasterise_pdf``), and records that method in the run's ``harness.json``.
* **``summary.md``.** One table row per slide: each app's score, against a
  baseline run's (``--baseline``) when one is given; the words each deck loses
  (``text_loss.json``, ``text_loss-gslides.json``); its MODEL DROPS and its
  captures taken and failed, per deck (``summaries*.json``). A baseline whose
  PDFs were rasterised another way is said to be so, because its PowerPoint
  scores do not compare with these; a baseline whose truth was rendered from
  another document, and each slide whose truth image changed, are named.
* **The truth** (Task 15 H1) is the slide as the UI shows it: each slide's
  document built by the UI's own ``slideDocument.ts``, bundled with the
  frontend's esbuild (``build_ui_documents``). Without that esbuild the harness
  stops before it exports, naming what to install.

No PowerPoint or Drive: MuPDF is stood in for by a fake ``fitz`` module, and
the later stages of ``main()`` are stubbed. One test draws a real page with
MuPDF, and is skipped where pymupdf is not installed (the harness passes it
with ``uv run --with pymupdf``). The truth tests render in the sidecar's
browser and build the UI's documents, and are skipped without the sidecar or
the frontend's esbuild.
"""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tests.fixtures.export_snapshot_support import (
    CORPUS_DIR,
    fidelity_harness,
    requires_huashu_sidecar,
    requires_ui_documents,
    ui_document,
)
from tests.unit.test_export_csp import (
    _frontend_preview_reset,
    _frontend_slide_csp,
)

# PowerPoint's PDF page for a 1280x720 slide: 960x540 pt.
PAGE_WIDTH_PT = 960.0
PAGE_HEIGHT_PT = 540.0
# A pixel of a box-filtered raster is the mean of the pixels it covers, so a
# raster of 1 px stripes, half 0 and half 255, is this grey to within rounding.
STRIPES_MEAN = 127.5
ROUNDING = 1.0


def _stripes(width: int, height: int) -> Image.Image:
    """Vertical stripes one pixel wide, black then white."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, width, 2):
        draw.line([(x, 0), (x, height - 1)], fill="black")
    return image


class _FakePixmap:
    """A MuPDF pixmap of the page drawn at the zoom asked for: 1 px stripes at that size."""

    def __init__(self, width: int, height: int) -> None:
        self.image = _stripes(width, height)
        self.width = width
        self.height = height
        self.samples = self.image.tobytes()

    def save(self, path: str) -> None:
        self.image.save(path)


class _FakePage:
    def __init__(self, zooms: list[float]) -> None:
        self.rect = types.SimpleNamespace(width=PAGE_WIDTH_PT, height=PAGE_HEIGHT_PT)
        self._zooms = zooms

    def get_pixmap(self, matrix) -> _FakePixmap:
        self._zooms.append(matrix.a)
        return _FakePixmap(round(PAGE_WIDTH_PT * matrix.a), round(PAGE_HEIGHT_PT * matrix.d))


def _fake_fitz(zooms: list[float], pages: int) -> types.ModuleType:
    """A ``fitz`` module whose PDFs hold ``pages`` pages, each recording the zoom it is drawn at."""
    module = types.ModuleType("fitz")
    module.open = lambda path: [_FakePage(zooms) for _ in range(pages)]
    module.Matrix = lambda a, d: types.SimpleNamespace(a=a, d=d)
    return module


class TestPdfRaster:
    def test_each_page_is_drawn_at_four_times_and_box_filtered_to_the_slide(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each page is drawn at 4x the slide's 1280 px, then box-filtered down to 1280x720.

        The fake MuPDF draws 1 px stripes at whatever size it is asked for, so
        a page drawn at 4x and box-filtered comes out a flat mid grey, each
        pixel the mean of four stripes; drawn at 1x it would come out as stripes.
        """
        harness = fidelity_harness()
        zooms: list[float] = []
        monkeypatch.setitem(sys.modules, "fitz", _fake_fitz(zooms, pages=2))
        names = ["01-first", "02-second"]
        harness.rasterise_pdf(tmp_path / "export.pdf", names, tmp_path)
        expected_zoom = 4 * 1280 / PAGE_WIDTH_PT
        assert zooms == [pytest.approx(expected_zoom)] * 2, (
            f"the pages were drawn at zooms {zooms}, not 4x the slide ({expected_zoom:.4f})"
        )
        for name in names:
            raster = Image.open(tmp_path / f"{name}.png").convert("L")
            assert raster.size == (1280, 720), f"{name} is {raster.size}, not the slide's 1280x720"
            low, high = raster.getextrema()
            assert abs(low - STRIPES_MEAN) <= ROUNDING and abs(high - STRIPES_MEAN) <= ROUNDING, (
                f"{name} ranges {low}..{high}: not each pixel the mean of the 4x pixels it covers"
            )

    def test_a_masked_2x_picture_keeps_its_rule_light_with_mupdf(self, tmp_path: Path) -> None:
        """With MuPDF itself: a 1 px rule in a picture embedded as PowerPoint embeds one.

        The picture is 2x its slide size, with an alpha mask (its clear pixels
        black, as Chrome captures them) and ``/Interpolate true``, and lies
        0.36 px off the pixel grid. Drawn at 1x, MuPDF spreads its EBEBEB rule
        over two rows seven times as dark as the rule; the harness's raster
        keeps it under half of that.
        """
        fitz = pytest.importorskip("fitz")
        picture = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
        ImageDraw.Draw(picture).rectangle([0, 200, 799, 201], fill=(235, 235, 235, 255))
        encoded = io.BytesIO()
        picture.save(encoded, "PNG")
        document = fitz.open()
        page = document.new_page(width=PAGE_WIDTH_PT, height=PAGE_HEIGHT_PT)
        page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        top = (100 + 0.36) * 0.75
        xref = page.insert_image(fitz.Rect(75, top, 375, top + 150), stream=encoded.getvalue())
        document.xref_set_key(xref, "Interpolate", "true")
        pdf_path = tmp_path / "export.pdf"
        document.save(pdf_path)

        def rule_weight(image: Image.Image) -> int:
            """How much darker than white the column through the rule is, summed."""
            return sum(255 - image.getpixel((300, y)) for y in range(195, 206))

        one = fitz.open(pdf_path)[0].get_pixmap(matrix=fitz.Matrix(1280 / 960, 1280 / 960))
        one_x = Image.frombytes("RGB", (one.width, one.height), one.samples).convert("L")
        fidelity_harness().rasterise_pdf(pdf_path, ["rule"], tmp_path)
        harness_raster = Image.open(tmp_path / "rule.png").convert("L")
        assert rule_weight(one_x) > 5 * 20, (
            f"fixture drift: MuPDF at 1x draws the rule's weight {rule_weight(one_x)}, which no "
            "longer shows the artefact (the rule's own weight is 20)"
        )
        assert rule_weight(harness_raster) < rule_weight(one_x) / 2, (
            f"the harness draws the rule's weight {rule_weight(harness_raster)}, MuPDF at 1x "
            f"{rule_weight(one_x)}: the raster is not the 4x box-filtered one"
        )


# ---------------------------------------------------------------------------
# summary.md
# ---------------------------------------------------------------------------

NAMES = ["01-cover", "02-table", "03-failed"]


def _summary(captures: int = 2, failures: int = 0, drops: int = 0) -> dict:
    """A slide summary line as the sidecar logs it, with the fields the summary reads."""
    return {
        "captures": captures,
        "captureFailures": failures,
        "modelDrops": drops,
        "hiddenText": "",
        "target": "pptx",
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _run_dir(tmp_path: Path, name: str, scores: dict, *, raster: str | None) -> Path:
    """A finished run's --out: its scores, and its harness.json unless ``raster`` is None."""
    out_dir = tmp_path / name
    out_dir.mkdir()
    _write_json(out_dir / "scores.json", scores)
    if raster is not None:
        _write_json(
            out_dir / "harness.json",
            {"fixture": str(CORPUS_DIR), "slides": len(scores), "pdfRaster": raster},
        )
    return out_dir


def _current_run(tmp_path: Path) -> Path:
    """A run of three slides: the third failed the PowerPoint export and was never rendered."""
    raster = fidelity_harness().PDF_RASTER
    out_dir = _run_dir(
        tmp_path,
        "run",
        {
            "01-cover": {"powerpoint": 4.29, "gslides": 2.82},
            "02-table": {"powerpoint": 2.13, "gslides": 1.80},
            "03-failed": {"gslides": 3.10},
        },
        raster=raster,
    )
    _write_json(out_dir / "summaries.json", [_summary(), _summary(9, 0, 2), None])
    _write_json(out_dir / "summaries-gslides.json", [_summary(), _summary(9, 1), _summary(1)])
    _write_json(out_dir / "text_loss.json", {"02-table": ["profit1", "a|b"]})
    _write_json(out_dir / "text_loss-gslides.json", {})
    return out_dir


def _rows(markdown: str) -> dict[str, list[str]]:
    """The summary table's rows by their first cell, each its cells, outer pipes dropped."""
    rows = {}
    for line in markdown.splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split(" | ")]
        rows[cells[0]] = cells
    return rows


class TestSummary:
    def test_each_slide_has_its_scores_against_the_baseline_its_losses_drops_and_captures(
        self, tmp_path: Path
    ) -> None:
        harness = fidelity_harness()
        out_dir = _current_run(tmp_path)
        baseline = _run_dir(
            tmp_path,
            "baseline",
            {
                "01-cover": {"powerpoint": 4.35, "gslides": 2.82},
                "02-table": {"powerpoint": 2.00, "gslides": 1.80},
                "03-failed": {"gslides": 3.10},
            },
            raster=harness.PDF_RASTER,
        )
        path = harness.write_summary(out_dir, NAMES, baseline)
        assert path == out_dir / "summary.md"
        markdown = path.read_text(encoding="utf-8")
        rows = _rows(markdown)
        header = rows["Slide"]
        assert header == [
            "Slide",
            "PowerPoint",
            "Google Slides",
            "Text loss (pptx / gslides)",
            "MODEL DROPS (pptx / gslides)",
            "Captures taken / failed (pptx; gslides)",
        ], header
        assert rows["01-cover"] == [
            "01-cover",
            "4.35 → 4.29",
            "2.82 → 2.82",
            "none / none",
            "0 / 0",
            "2 / 0; 2 / 0",
        ], rows["01-cover"]
        assert rows["02-table"] == [
            "02-table",
            "2.00 → 2.13",
            "1.80 → 1.80",
            "profit1 a\\|b / none",
            "2 / 0",
            "9 / 0; 8 / 1",
        ], rows["02-table"]
        assert rows["03-failed"] == [
            "03-failed",
            "—",
            "3.10 → 3.10",
            "none / none",
            "export failed / 0",
            "export failed; 1 / 0",
        ], rows["03-failed"]
        assert rows["**mean**"][1:3] == ["**3.17 → 3.21**", "**2.57 → 2.57**"], rows["**mean**"]
        assert "Worse than the baseline by more than 0.05: 02-table (PowerPoint +0.13)." in (
            markdown
        ), markdown
        assert harness.PDF_RASTER in markdown, "the summary names how PowerPoint was rasterised"
        assert str(CORPUS_DIR) in markdown, "the summary names its fixture"

    def test_without_a_baseline_each_score_stands_alone(self, tmp_path: Path) -> None:
        markdown = (
            fidelity_harness()
            .write_summary(_current_run(tmp_path), NAMES)
            .read_text(encoding="utf-8")
        )
        rows = _rows(markdown)
        assert rows["01-cover"][1:3] == ["4.29", "2.82"], rows["01-cover"]
        assert rows["**mean**"][1:3] == ["**3.21**", "**2.57**"], rows["**mean**"]
        assert "Worse than the baseline" not in markdown

    @pytest.mark.parametrize("raster", [None, "MuPDF at 1x"], ids=["no-record", "another-raster"])
    def test_a_baseline_rasterised_another_way_compares_no_pdf_scores(
        self, tmp_path: Path, raster: str | None
    ) -> None:
        """A baseline before the 4x raster (no harness.json), or on another: its PDFs' scores
        do not compare.

        PowerPoint and LibreOffice, both scored from a rasterised PDF, are not
        set against it: each row shows this run's score alone, the mean is this
        run's over every slide it scored, and no rise of theirs is listed as
        worse, so a rise the raster alone makes (02-table's PowerPoint +0.13
        here) is no regression. Google Slides, scored from its thumbnails, is
        compared as before.
        """
        harness = fidelity_harness()
        out_dir = _current_run(tmp_path)
        _write_json(
            out_dir / "scores.json",
            {
                "01-cover": {"powerpoint": 4.29, "gslides": 2.82, "libreoffice": 6.0},
                "02-table": {"powerpoint": 2.13, "gslides": 1.90, "libreoffice": 5.0},
                "03-failed": {"gslides": 3.10},
            },
        )
        baseline = _run_dir(
            tmp_path,
            "baseline",
            {
                "01-cover": {"powerpoint": 4.35, "gslides": 2.82, "libreoffice": 5.0},
                "02-table": {"powerpoint": 2.00, "gslides": 1.80, "libreoffice": 4.0},
            },
            raster=raster,
        )
        markdown = harness.write_summary(out_dir, NAMES, baseline).read_text(encoding="utf-8")
        assert "rasterised its PowerPoint PDFs another way" in markdown, markdown
        rows = _rows(markdown)
        assert rows["Slide"][1:4] == [
            "PowerPoint (not compared: raster differs)",
            "Google Slides",
            "LibreOffice (not compared: raster differs)",
        ], rows["Slide"]
        assert rows["02-table"][1:4] == ["2.13", "1.80 → 1.90", "5.00"], rows["02-table"]
        assert rows["**mean**"][1:4] == ["**3.21**", "**2.31 → 2.36**", "**5.50**"], rows[
            "**mean**"
        ]
        assert "Worse than the baseline by more than 0.05: 02-table (Google Slides +0.10)." in (
            markdown
        ), markdown

    def test_a_truth_rendered_another_way_or_changed_is_named(self, tmp_path: Path) -> None:
        """The truth is held against the baseline's, so a score's change can be read.

        A baseline from before harness.json recorded the truth rendered it from
        the export document, which the summary says. Each slide whose truth
        image differs from the baseline's pixel for pixel is named (02-table);
        one whose image is the same (01-cover, 03-failed, the latter written
        again byte for byte apart, the same pixels) is not.
        """
        harness = fidelity_harness()
        out_dir = _current_run(tmp_path)
        _write_json(
            out_dir / "harness.json", {"pdfRaster": harness.PDF_RASTER, "truth": harness.TRUTH}
        )
        baseline = _run_dir(
            tmp_path, "baseline", {"01-cover": {"gslides": 2.82}}, raster=harness.PDF_RASTER
        )
        for run, colours in (
            (out_dir, ("white", "red", "blue")),
            (baseline, ("white", "green", "blue")),
        ):
            (run / "truth").mkdir()
            for name, colour in zip(NAMES, colours):
                Image.new("RGB", (32, 18), colour).save(run / "truth" / f"{name}.png")
        Image.new("RGBA", (32, 18), "blue").save(baseline / "truth" / "03-failed.png")
        markdown = harness.write_summary(out_dir, NAMES, baseline).read_text(encoding="utf-8")
        assert (
            "The baseline's truth is the export document (from before harness.json recorded the "
            f"truth); this run's is {harness.TRUTH}."
        ) in markdown, markdown
        assert "The truth image differs from the baseline's on 02-table:" in markdown, markdown

        _write_json(
            baseline / "harness.json",
            {"pdfRaster": harness.PDF_RASTER, "truth": harness.TRUTH},
        )
        Image.new("RGB", (32, 18), "green").save(out_dir / "truth" / "02-table.png")
        markdown = harness.write_summary(out_dir, NAMES, baseline).read_text(encoding="utf-8")
        assert "The baseline's truth is" not in markdown, markdown
        assert "The truth image is the baseline's, pixel for pixel, on every slide." in markdown, (
            markdown
        )

    def test_a_run_without_google_slides_reports_its_deck_alone(self, tmp_path: Path) -> None:
        out_dir = _current_run(tmp_path)
        (out_dir / "summaries-gslides.json").unlink()
        (out_dir / "text_loss-gslides.json").unlink()
        _write_json(out_dir / "scores.json", {"01-cover": {"powerpoint": 4.29}})
        rows = _rows(fidelity_harness().write_summary(out_dir, NAMES).read_text(encoding="utf-8"))
        assert rows["Slide"] == [
            "Slide",
            "PowerPoint",
            "Text loss (pptx)",
            "MODEL DROPS (pptx)",
            "Captures taken / failed (pptx)",
        ], rows["Slide"]
        assert rows["02-table"] == ["02-table", "—", "profit1 a\\|b", "2", "9 / 0"], rows[
            "02-table"
        ]


class TestMainSummary:
    """``main()`` records how it rasterised, checks both decks' text and writes summary.md."""

    def test_main_writes_the_record_both_text_checks_and_the_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = fidelity_harness()
        fixture_dir = tmp_path / "fixture"
        (fixture_dir / "slides").mkdir(parents=True)
        (fixture_dir / "deck.css").write_text(".slide { color: red; }\n", encoding="utf-8")
        (fixture_dir / "deck.json").write_text(
            (CORPUS_DIR / "deck.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (fixture_dir / "slides" / "01-text.html").write_text(
            '<div class="slide"><h1>Revenue grew</h1></div>', encoding="utf-8"
        )
        out_dir = tmp_path / "out"
        baseline = _run_dir(
            tmp_path, "baseline", {"01-text": {"gslides": 2.0}}, raster=harness.PDF_RASTER
        )
        checked: list[tuple[str, str]] = []

        def export_pptx(deck, documents, out, target="pptx"):
            suffix = "" if target == "pptx" else f"-{target}"
            _write_json(out / f"summaries{suffix}.json", [_summary()])
            return out / f"export{suffix}.pptx"

        def check_text_loss(pptx_path, names, out, hidden_text=None, target="pptx"):
            checked.append((Path(pptx_path).name, target))
            suffix = "" if target == "pptx" else f"-{target}"
            _write_json(out / f"text_loss{suffix}.json", {})
            return {}

        def compare(names, out):
            scores = {"01-text": {"gslides": 1.5}}
            _write_json(out / "scores.json", scores)
            return scores

        monkeypatch.setattr(harness, "ui_documents_missing", lambda: None)
        monkeypatch.setattr(harness, "build_ui_documents", lambda deck, slides, out: [])
        monkeypatch.setattr(harness, "render_truth", lambda documents, out: None)
        monkeypatch.setattr(harness, "export_pptx", export_pptx)
        monkeypatch.setattr(harness, "check_text_loss", check_text_loss)
        monkeypatch.setattr(harness, "render_with_google_slides", lambda path, names, out: "url")
        monkeypatch.setattr(harness, "compare", compare)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run.py",
                str(fixture_dir),
                "--out",
                str(out_dir),
                "--gslides",
                "--baseline",
                str(baseline),
            ],
        )
        assert harness.main() == 0
        assert checked == [("export.pptx", "pptx"), ("export-gslides.pptx", "gslides")], checked
        record = json.loads((out_dir / "harness.json").read_text(encoding="utf-8"))
        assert record == {
            "fixture": str(fixture_dir),
            "slides": 1,
            "pdfRaster": harness.PDF_RASTER,
            "truth": harness.TRUTH,
        }, record
        rows = _rows((out_dir / "summary.md").read_text(encoding="utf-8"))
        assert rows["01-text"][1] == "2.00 → 1.50", rows["01-text"]


# ---------------------------------------------------------------------------
# The truth: the slide as the UI shows it (Task 15 H1)
# ---------------------------------------------------------------------------

# A design-system template deck, as the matrix's template decks are made: the
# slide's ground is on a bare <section> wrapper, its .slide absolutely placed
# inside it, so the wrapper has no height of its own and only the UI's frame
# contract (slideHostFrameStyle) gives it the frame. The page's own ground,
# html and body's, is dark, as the template's deck-stage page is.
TEMPLATE_DECK_CSS = (
    "html, body { background: #0E1A1F; }\n"
    "section { background: #F9F7F4; color: #3A3838; font-family: sans-serif; }\n"
    ".slide { position: absolute; inset: 0; padding: 72px 88px; }\n"
)
TEMPLATE_SLIDE = '<section><div class="slide"><h1>Acme quarterly review</h1></div></section>'
TEMPLATE_HEADING = "Acme quarterly review"
SECTION_GROUND = (0xF9, 0xF7, 0xF4)
PAGE_GROUND = (0x0E, 0x1A, 0x1F)
# A point of the slide's ground well clear of its text.
GROUND_POINT = (640, 600)
# A flat ground is the colour it paints, give or take colour management.
GROUND_TOLERANCE = 3


def _near(colour: tuple[int, ...], expected: tuple[int, int, int]) -> bool:
    return all(abs(shown - wanted) <= GROUND_TOLERANCE for shown, wanted in zip(colour, expected))


def _template_fixture(tmp_path: Path) -> Path:
    fixture_dir = tmp_path / "template-fixture"
    (fixture_dir / "slides").mkdir(parents=True)
    (fixture_dir / "deck.css").write_text(TEMPLATE_DECK_CSS, encoding="utf-8")
    (fixture_dir / "deck.json").write_text(
        json.dumps({"title": "Template deck", "scripts": "", "external_scripts": []}),
        encoding="utf-8",
    )
    (fixture_dir / "slides" / "01-template.html").write_text(TEMPLATE_SLIDE, encoding="utf-8")
    return fixture_dir


def _stub_export(harness, monkeypatch: pytest.MonkeyPatch, exported: list) -> None:
    """main()'s stages after the truth, stubbed: what they were asked to export is recorded."""

    def export_pptx(deck, documents, out, target="pptx"):
        exported.append(target)
        return out / "export.pptx"

    monkeypatch.setattr(harness, "export_pptx", export_pptx)
    monkeypatch.setattr(harness, "recorded_summaries", lambda out, target="pptx": [None])
    monkeypatch.setattr(harness, "check_text_loss", lambda *arguments, **keywords: {})
    monkeypatch.setattr(harness, "compare", lambda names, out: {})


@pytest.mark.slow
@requires_huashu_sidecar
@requires_ui_documents
class TestTruthIsTheUIDocument:
    def test_a_template_decks_truth_shows_its_slide_ground_as_the_ui_does(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main()'s truth of a template deck is the slide the UI shows.

        The UI's frame contract gives the <section> wrapper the frame, so its
        light ground fills the slide; the export document has no contract (a
        choice export.py records), so there the wrapper has no height and the
        page's dark ground shows. That the export document draws the dark
        ground is checked first, so the fixture tells the two apart. The truth
        image is the light ground, and its text reference holds the heading.
        """
        harness = fidelity_harness()
        fixture_dir = _template_fixture(tmp_path)
        deck, slides = harness.load_fixture_deck(fixture_dir)
        export_dir = tmp_path / "export-document"
        export_documents = harness.build_documents(deck, slides, export_dir)
        harness.render_truth(export_documents, export_dir)
        with Image.open(export_dir / "truth" / "01-template.png") as drawn:
            export_ground = drawn.convert("RGB").getpixel(GROUND_POINT)
        assert _near(export_ground, PAGE_GROUND), (
            f"fixture drift: the export document draws {export_ground} at {GROUND_POINT}, not the "
            f"page's dark ground {PAGE_GROUND}; the fixture no longer tells the documents apart"
        )

        out_dir = tmp_path / "out"
        exported: list = []
        _stub_export(harness, monkeypatch, exported)
        monkeypatch.setattr(sys, "argv", ["run.py", str(fixture_dir), "--out", str(out_dir)])
        assert harness.main() == 0
        with Image.open(out_dir / "truth" / "01-template.png") as drawn:
            truth_ground = drawn.convert("RGB").getpixel(GROUND_POINT)
        assert _near(truth_ground, SECTION_GROUND), (
            f"the truth draws {truth_ground} at {GROUND_POINT}: the UI shows the section's ground "
            f"{SECTION_GROUND} there (the export document's dark ground is {PAGE_GROUND})"
        )
        reference = (out_dir / "truth" / "01-template.txt").read_text(encoding="utf-8")
        assert TEMPLATE_HEADING in reference, f"the truth's text reference is {reference!r}"
        assert exported == ["pptx"], f"main() exported {exported}"

    def test_the_truth_document_is_the_one_slide_document_ts_builds(self) -> None:
        """The UI document is buildSlideDocument's, read from the TS source itself.

        Its CSP is the frontend's SLIDE_CSP, its one stylesheet is the deck's CSS
        and then SLIDE_PREVIEW_RESET_STYLE (the root reset and the frame
        contract), and its body is the slide, then the slide's script: what the
        viewer's stage builds, and not the export's shell.
        """
        css = ".slide { color: #1B3139; }"
        body = '<div class="slide"><p>Revenue grew</p></div>'
        script = "document.title = 'charted';"
        document = ui_document(body, css=css, scripts=script)

        assert f'content="{_frontend_slide_csp()}"' in document, document[:400]
        assert f"<style>{css}\n{_frontend_preview_reset()}</style>" in document, document
        assert document.count("<style>") == 1, "the UI document has one stylesheet"
        assert f"<body>\n  {body}\n  <script>{script}</script>" in document, document
        assert "font-family" not in document, "the UI's shell sets no font"


class TestUiDocumentsMissing:
    def test_main_names_what_to_install_and_exports_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Without the frontend's esbuild, main() stops before it exports, naming `npm ci`."""
        harness = fidelity_harness()
        monkeypatch.setattr(harness, "FRONTEND_ESBUILD", tmp_path / "node_modules" / "esbuild")
        exported: list = []
        _stub_export(harness, monkeypatch, exported)
        out_dir = tmp_path / "out"
        monkeypatch.setattr(
            sys, "argv", ["run.py", str(_template_fixture(tmp_path)), "--out", str(out_dir)]
        )
        assert harness.main() == 2
        error = capsys.readouterr().err
        assert "`npm ci` in frontend/" in error and "slideDocument.ts" in error, error
        assert not exported and not out_dir.exists(), "main() went on without the truth"

    def test_build_ui_documents_raises_naming_what_to_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = fidelity_harness()
        monkeypatch.setattr(harness, "FRONTEND_ESBUILD", tmp_path / "node_modules" / "esbuild")
        with pytest.raises(harness.UiDocumentError, match="npm ci"):
            harness.build_ui_documents({"css": ""}, [("01", "<div></div>")], tmp_path)
