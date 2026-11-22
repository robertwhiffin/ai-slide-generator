"""The export fidelity harness's ``--pin-fonts``: one font binary per face, run after run.

A fixture deck loads its webfonts with a Google Fonts ``@import``, and Google
now and then answers it with another stylesheet naming another font file, so
two harness runs of one deck can render it differently (text widths move
PowerPoint scores by about 0.08). ``scripts/export_fidelity/run.py
--pin-fonts`` makes runs comparable:

* ``pinned_fonts_css(css)`` replaces each Google Fonts ``@import`` line of a
  deck's CSS with the latin faces Google serves for that import, embedded as
  ``data:`` (the slide CSP's ``font-src`` allows it), from the font files
  committed under ``tests/fixtures/export_snapshot/fonts``
  (``PINNED_FONT_IMPORTS``: import URL -> its faces). The in-repo corpus's
  import pins to exactly the faces the snapshot tests pin
  (``pinned_font_css``). The design-system corpus's imports pin to their own
  files, which differ: DM Sans without an optical-size axis, its italic, DM
  Mono 300 and Barlow.
* An import it has no faces for, or any other reference to Google Fonts left
  in the CSS, is refused with a ``ValueError`` naming it: a pinned run never
  loads a live webfont silently.
* ``load_fixture_deck(fixture_dir, pin_fonts=True)`` pins the deck's CSS, and
  refuses a slide that loads Google Fonts itself. Without the option the deck
  loads exactly as before, live fonts and all.
* ``main()`` takes ``--pin-fonts`` and builds every export document from the
  pinned deck.

The browser test needs node, the extracted sidecar ``node_modules`` and a
local Chrome/Chromium (skipped otherwise); the rest needs no browser.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.fixtures.export_snapshot_support import (
    CORPUS_DIR,
    DECK_CSS,
    PINNED_FONT_DIR,
    browser_loaded_faces,
    browser_probes,
    fidelity_harness,
    pinned_font_css,
    requires_huashu_sidecar,
    slide_document,
)

GOOGLE_FONTS_HOST = "fonts.googleapis.com"
# How a Google Fonts import starts in a document (its CSP names the host whatever the CSS).
GOOGLE_FONTS_IMPORT_START = "@import url('https://fonts.googleapis.com/"
WOFF2_SIGNATURE = b"wOF2"
GOOGLE_FONT_FILES_HOST = "fonts.gstatic.com"
UNPINNED_IMPORT = "https://fonts.googleapis.com/css2?family=Inter:wght@400&display=swap"
UNPINNED_FILE = "https://fonts.gstatic.com/s/inter/v13/UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hiA.woff2"  # noqa: E501

# Text set in each face the design-system corpus uses, so the browser loads them all.
DESIGN_SYSTEM_SAMPLE = (
    "<style>"
    ".sans { font-family: 'DM Sans'; } .mono { font-family: 'DM Mono'; }"
    " .display { font-family: 'Barlow'; }"
    "</style>"
    '<div class="slide">'
    '<p class="sans" style="font-weight: 400;">Regular</p>'
    '<p class="sans" style="font-weight: 400; font-style: italic;">Italic source line</p>'
    '<p class="sans" style="font-weight: 600;">Semibold</p>'
    '<p class="mono" style="font-weight: 300;">light mono</p>'
    '<p class="mono" style="font-weight: 500;">medium mono</p>'
    '<p class="display" style="font-weight: 500;">Display</p>'
    "</div>"
)
# A title the optical-size axis sets visibly narrower at 48 px, and the least
# difference in width that counts as narrower.
OPTICAL_SIZE_SAMPLE = "Quarterly revenue and margin"
OPTICAL_SIZE_MIN_PX = 2.0

# A line whose italic advances add up to several px more than the upright's at 48 px.
ITALIC_SAMPLE = "Annual run-rate, source: customer case. Annual run-rate, source: customer case."
ITALIC_MIN_DIFFERENCE_PX = 1.0

# (family, style, weight) of each face the sample uses.
DESIGN_SYSTEM_SAMPLE_FACES = {
    ("DM Sans", "normal", 400),
    ("DM Sans", "italic", 400),
    ("DM Sans", "normal", 600),
    ("DM Mono", "normal", 300),
    ("DM Mono", "normal", 500),
    ("Barlow", "normal", 500),
}


def _import_id(url: str) -> str:
    return url.removeprefix("https://fonts.googleapis.com/css2?")


def _import_line(url: str) -> str:
    return f"@import url('{url}');\n"


def _design_system_css() -> str:
    """A deck CSS written as the design-system corpus's is: two imports, a comment between."""
    harness = fidelity_harness()
    return (
        _import_line(harness.DESIGN_SYSTEM_FONTS_IMPORT)
        + "/* the display face */\n"
        + _import_line(harness.DESIGN_SYSTEM_DISPLAY_FONTS_IMPORT)
        + ":root { --ink: #1B3139; }\n"
    )


class TestPinnedFontsCss:
    def test_the_corpus_deck_pins_to_the_faces_the_snapshot_tests_pin(self) -> None:
        assert fidelity_harness().pinned_fonts_css(DECK_CSS) == pinned_font_css()

    @pytest.mark.parametrize("url", sorted(fidelity_harness().PINNED_FONT_IMPORTS), ids=_import_id)
    def test_each_pinned_import_becomes_its_faces_and_reaches_no_google_fonts(
        self, url: str
    ) -> None:
        faces = fidelity_harness().PINNED_FONT_IMPORTS[url]
        pinned = fidelity_harness().pinned_fonts_css(_import_line(url) + ".x { color: red; }\n")
        assert GOOGLE_FONTS_HOST not in pinned, pinned[:500]
        assert pinned.count("@font-face") == len(faces), pinned[:500]
        assert pinned.count("src: url(data:font/woff2;base64,") == len(faces)
        assert pinned.endswith(".x { color: red; }\n"), "the deck's own rules are kept"
        for family, style, weight, _ in faces:
            assert (
                f"font-family: '{family}'; font-style: {style}; font-weight: {weight};" in pinned
            ), f"{family} {style} {weight} is not declared"

    def test_both_design_system_imports_are_replaced_and_the_rest_kept(self) -> None:
        harness = fidelity_harness()
        css = _design_system_css()
        pinned = harness.pinned_fonts_css(css)
        expected_faces = len(harness.PINNED_FONT_IMPORTS[harness.DESIGN_SYSTEM_FONTS_IMPORT]) + len(
            harness.PINNED_FONT_IMPORTS[harness.DESIGN_SYSTEM_DISPLAY_FONTS_IMPORT]
        )
        assert GOOGLE_FONTS_HOST not in pinned
        assert pinned.count("@font-face") == expected_faces
        assert pinned.endswith("/* the display face */\n:root { --ink: #1B3139; }\n")

    @pytest.mark.parametrize("url", sorted(fidelity_harness().PINNED_FONT_IMPORTS), ids=_import_id)
    def test_every_pinned_face_is_a_committed_woff2_declared_once(self, url: str) -> None:
        faces = fidelity_harness().PINNED_FONT_IMPORTS[url]
        descriptors = [(family, style, weight) for family, style, weight, _ in faces]
        assert len(set(descriptors)) == len(descriptors), f"a face is declared twice: {descriptors}"
        for _, _, _, name in faces:
            path = PINNED_FONT_DIR / name
            assert path.is_file(), f"{path} is not committed"
            assert path.read_bytes()[:4] == WOFF2_SIGNATURE, f"{path} is not a woff2 file"
            assert (path.parent / "OFL.txt").is_file(), f"{path.parent} has no licence text"

    def test_an_import_it_has_no_faces_for_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Inter:wght@400"):
            fidelity_harness().pinned_fonts_css(_import_line(UNPINNED_IMPORT) + DECK_CSS)

    @pytest.mark.parametrize(
        "reference",
        [
            f'@import "{UNPINNED_IMPORT}";\n',
            f'@import url("{UNPINNED_IMPORT}");\n',
            f"  @import url('{UNPINNED_IMPORT}');\n",
        ],
        ids=["bare-string", "double-quoted", "indented"],
    )
    def test_a_google_fonts_import_in_another_form_is_refused(self, reference: str) -> None:
        with pytest.raises(ValueError, match=GOOGLE_FONTS_HOST):
            fidelity_harness().pinned_fonts_css(reference + ".x { color: red; }\n")

    def test_a_face_loaded_from_google_fonts_files_is_refused(self) -> None:
        reference = f"@font-face {{ font-family: 'Inter'; src: url({UNPINNED_FILE}); }}\n"
        with pytest.raises(ValueError, match=GOOGLE_FONT_FILES_HOST):
            fidelity_harness().pinned_fonts_css(DECK_CSS + reference)


class TestLoadFixtureDeck:
    def test_by_default_the_deck_loads_with_its_live_fonts(self) -> None:
        deck, slides = fidelity_harness().load_fixture_deck(CORPUS_DIR)
        assert deck["css"] == DECK_CSS
        assert len(slides) == len(list((CORPUS_DIR / "slides").glob("*.html")))

    def test_pinned_the_deck_loads_with_the_pinned_faces(self) -> None:
        deck, slides = fidelity_harness().load_fixture_deck(CORPUS_DIR, pin_fonts=True)
        assert deck["css"] == pinned_font_css()
        assert [name for name, _ in slides] == [
            name for name, _ in fidelity_harness().load_fixture_deck(CORPUS_DIR)[1]
        ], "pinning changes no slide"

    def test_pinned_a_slide_that_loads_google_fonts_itself_is_refused(self, tmp_path: Path) -> None:
        fixture_dir = _fixture_copy(tmp_path)
        (fixture_dir / "slides" / "02-own-font.html").write_text(
            f'<link rel="stylesheet" href="{UNPINNED_IMPORT}"><div class="slide">Text</div>',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="02-own-font"):
            fidelity_harness().load_fixture_deck(fixture_dir, pin_fonts=True)
        _, slides = fidelity_harness().load_fixture_deck(fixture_dir)
        assert [name for name, _ in slides] == ["01-text", "02-own-font"], (
            "without the option the slide loads as it is"
        )


def _fixture_copy(tmp_path: Path) -> Path:
    """A one-slide fixture deck with the corpus deck's CSS and deck.json."""
    fixture_dir = tmp_path / "fixture"
    slides_dir = fixture_dir / "slides"
    slides_dir.mkdir(parents=True)
    (fixture_dir / "deck.css").write_text(DECK_CSS, encoding="utf-8")
    (fixture_dir / "deck.json").write_text(
        (CORPUS_DIR / "deck.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (slides_dir / "01-text.html").write_text(
        '<div class="slide"><h1>Revenue grew</h1></div>', encoding="utf-8"
    )
    return fixture_dir


class TestMainOption:
    """``main()`` builds the export documents from the deck it loads; later stages are stubbed."""

    def _run_main(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *options: str) -> str:
        """The first export document ``main()`` writes, run with ``options`` and no browser."""
        harness = fidelity_harness()
        fixture_dir = _fixture_copy(tmp_path)
        out_dir = tmp_path / "out"
        pptx_path = out_dir / "export.pptx"
        monkeypatch.setattr(harness, "ui_documents_missing", lambda: None)
        monkeypatch.setattr(harness, "build_ui_documents", lambda deck, slides, out: [])
        monkeypatch.setattr(harness, "render_truth", lambda documents, out: None)
        monkeypatch.setattr(
            harness, "export_pptx", lambda deck, documents, out, target="pptx": pptx_path
        )
        monkeypatch.setattr(harness, "recorded_summaries", lambda out, target="pptx": [None])
        monkeypatch.setattr(harness, "check_text_loss", lambda *arguments, **keywords: {})
        monkeypatch.setattr(harness, "compare", lambda names, out: {})
        monkeypatch.setattr(
            sys, "argv", ["run.py", str(fixture_dir), "--out", str(out_dir), *options]
        )
        assert harness.main() == 0
        return (out_dir / "documents" / "01-text.html").read_text(encoding="utf-8")

    def test_without_the_option_the_documents_load_live_fonts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document = self._run_main(tmp_path, monkeypatch)
        assert GOOGLE_FONTS_IMPORT_START in document
        assert "data:font/woff2;base64," not in document

    def test_with_the_option_the_documents_load_only_the_pinned_faces(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document = self._run_main(tmp_path, monkeypatch, "--pin-fonts")
        assert GOOGLE_FONTS_IMPORT_START not in document
        assert pinned_font_css() in document


@pytest.mark.slow
@requires_huashu_sidecar
class TestPinnedFacesRender:
    def test_the_design_system_faces_load_from_the_pinned_files(self) -> None:
        """Every face the design-system corpus uses loads from its committed file, none live."""
        css = fidelity_harness().pinned_fonts_css(_design_system_css())
        document = slide_document(DESIGN_SYSTEM_SAMPLE, css=css)
        assert GOOGLE_FONTS_IMPORT_START not in document, (
            "fixture drift: the document imports Google Fonts"
        )
        loaded = browser_loaded_faces(document)
        assert DESIGN_SYSTEM_SAMPLE_FACES <= loaded, (
            f"faces not loaded: {sorted(DESIGN_SYSTEM_SAMPLE_FACES - loaded)}; "
            f"loaded: {json.dumps(sorted(loaded))}"
        )
        # The italic face is the italic file: its advances differ from the upright's.
        body = "font-family: 'DM Sans'; font-size: 48px; font-weight: 400;"
        italic, upright = browser_probes(
            document,
            [
                (ITALIC_SAMPLE, body + " font-style: italic;"),
                (ITALIC_SAMPLE, body + " font-style: normal;"),
            ],
        )
        assert abs(italic["w"] - upright["w"]) > ITALIC_MIN_DIFFERENCE_PX, (
            f"the italic sets as wide as the upright: {italic} vs {upright}"
        )

    @pytest.mark.parametrize(
        ("corpus", "optical_sizes"),
        [("design-system", False), ("corpus", True)],
    )
    def test_dm_sans_has_an_optical_size_axis_only_where_its_import_asks_for_one(
        self, corpus: str, optical_sizes: bool
    ) -> None:
        """The two corpora's DM Sans files differ as Google's do.

        The corpus deck asks for the optical-size axis, so a large title is set
        narrower under automatic optical sizing than with it turned off. The
        design-system deck does not, and Google serves a file with a weight axis
        only, so the two widths are equal: pinning it to the corpus's file would
        change how its slides look.
        """
        css = DECK_CSS if corpus == "corpus" else _design_system_css()
        document = slide_document(
            '<div class="slide"><p>fixture</p></div>',
            css=fidelity_harness().pinned_fonts_css(css),
        )
        title = "font-family: 'DM Sans'; font-size: 48px; font-weight: 700;"
        automatic, turned_off = browser_probes(
            document,
            [
                (OPTICAL_SIZE_SAMPLE, title + " font-optical-sizing: auto;"),
                (OPTICAL_SIZE_SAMPLE, title + " font-optical-sizing: none;"),
            ],
        )
        narrower = turned_off["w"] - automatic["w"]
        if optical_sizes:
            assert narrower > OPTICAL_SIZE_MIN_PX, f"{automatic} vs {turned_off}"
        else:
            assert abs(narrower) < OPTICAL_SIZE_MIN_PX, f"{automatic} vs {turned_off}"
