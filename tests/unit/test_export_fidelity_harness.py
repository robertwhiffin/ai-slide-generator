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
  scores do not compare with these.

No browser, PowerPoint or Drive: MuPDF is stood in for by a fake ``fitz``
module, and the later stages of ``main()`` are stubbed. One test draws a real
page with MuPDF, and is skipped where pymupdf is not installed (the harness
passes it with ``uv run --with pymupdf``).
"""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tests.fixtures.export_snapshot_support import CORPUS_DIR, fidelity_harness

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
    def test_a_baseline_rasterised_another_way_is_said_not_to_compare(
        self, tmp_path: Path, raster: str | None
    ) -> None:
        """A baseline run before the 4x raster (no harness.json), or with another, is flagged."""
        harness = fidelity_harness()
        baseline = _run_dir(
            tmp_path, "baseline", {"01-cover": {"powerpoint": 4.35, "gslides": 2.82}}, raster=raster
        )
        markdown = harness.write_summary(_current_run(tmp_path), NAMES, baseline).read_text(
            encoding="utf-8"
        )
        assert "rasterised its PowerPoint PDFs another way" in markdown, markdown
        rows = _rows(markdown)
        assert rows["Slide"][1] == "PowerPoint (baseline rasterised otherwise)"
        # The baseline scored the first slide alone, so both means are over it alone.
        assert rows["**mean**"][1:3] == ["**4.35 → 4.29**", "**2.82 → 2.82**"], rows["**mean**"]

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
        }, record
        rows = _rows((out_dir / "summary.md").read_text(encoding="utf-8"))
        assert rows["01-text"][1] == "2.00 → 1.50", rows["01-text"]
