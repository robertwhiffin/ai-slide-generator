"""The export document gives a slide's inherited text what the UI's document gives it (Task 15, N2).

THE DEFECT. ``build_slide_html``'s first sheet set ``html, body { font-family:
'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif }``, and the UI's
document (``buildSlideDocument`` with ``SLIDE_PREVIEW_RESET_STYLE``,
``frontend/src/services/slideDocument.ts``) sets no font. So text that takes
its font from ``body`` was drawn in the browser's default face in the UI (Times
on the Mac) and in SF or the container's fallback in the export, and broke its
lines elsewhere: long-on 05's "So what" paragraph was 4 lines in the UI and 5
in the export (the real-deck matrix).

WHAT IS PINNED.
* **Parity of the shells, from source.** Every inherited property either
  shell declares, on any selector, the other declares the same way: the
  export's shell sheets read from the document ``build_slide_html`` writes, the
  UI's from the ``SLIDE_PREVIEW_RESET_STYLE`` literal of the TS source. Today
  neither declares one.
* **The frontend's capture shells, from source** (Task 15 B7, fix round 1).
  ``pdf_client.ts``, ``pptx_client.ts`` and ``screenshotCapture.ts`` each
  build a slide document of their own around the deck's CSS (the PDF
  download, the client-side PPTX's chart captures, the chat's screenshots).
  Each one's sheet, read from its template literal with the deck's CSS taken
  out, declares the inherited properties the UI's does: none today. Their
  other ``<head>`` interpolation, ``trustedExportRuntimeMarkup()``, writes
  scripts only; its opt-in font shim is a deliberate substitution, not a shell
  default.
* **Through the real engine.** A slide with no font of its own is drawn in the
  same face in the export document as in the UI's (the DevTools protocol's
  faces), and the exported text item holds the lines the UI's document breaks
  it into. The fixture is checked to tell the old shell font from the UI's.

Only what inherited text is given is in scope. The typeface the deck then
writes for such text (the stack's first family) is a separate question.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.api.routes.export import build_slide_html
from tests.fixtures.export_snapshot_support import (
    browser_faces,
    browser_lines,
    export_slides,
    requires_huashu_sidecar,
    requires_ui_documents,
    slide_document,
    slide_shapes,
    ui_document,
)
from tests.unit.test_export_csp import _frontend_preview_reset, _frontend_slide_root_reset

# The properties CSS marks "Inherited: yes" (CSS 2.1, Fonts 4, Text 3 and 4,
# Text Decoration 4, Writing Modes 4, Color 4, UI 4, Lists 3, Tables), plus
# `all`, which resets them, and custom properties (any `--name`), which inherit.
INHERITED_PROPERTIES = frozenset(
    {
        "all",
        "border-collapse",
        "border-spacing",
        "caption-side",
        "caret-color",
        "color",
        "color-scheme",
        "cursor",
        "direction",
        "empty-cells",
        "font",
        "font-family",
        "font-feature-settings",
        "font-kerning",
        "font-language-override",
        "font-optical-sizing",
        "font-palette",
        "font-size",
        "font-size-adjust",
        "font-stretch",
        "font-style",
        "font-synthesis",
        "font-synthesis-small-caps",
        "font-synthesis-style",
        "font-synthesis-weight",
        "font-variant",
        "font-variant-alternates",
        "font-variant-caps",
        "font-variant-east-asian",
        "font-variant-emoji",
        "font-variant-ligatures",
        "font-variant-numeric",
        "font-variant-position",
        "font-variation-settings",
        "font-weight",
        "font-width",
        "hyphenate-character",
        "hyphens",
        "image-rendering",
        "letter-spacing",
        "line-break",
        "line-height",
        "list-style",
        "list-style-image",
        "list-style-position",
        "list-style-type",
        "orphans",
        "overflow-wrap",
        "paint-order",
        "pointer-events",
        "quotes",
        "tab-size",
        "text-align",
        "text-align-last",
        "text-decoration-skip-ink",
        "text-emphasis",
        "text-emphasis-color",
        "text-emphasis-position",
        "text-emphasis-style",
        "text-indent",
        "text-justify",
        "text-orientation",
        "text-rendering",
        "text-shadow",
        "text-size-adjust",
        "text-transform",
        "text-underline-offset",
        "text-underline-position",
        "text-wrap",
        "visibility",
        "white-space",
        "white-space-collapse",
        "widows",
        "word-break",
        "word-spacing",
        "word-wrap",
        "writing-mode",
        "-webkit-font-smoothing",
        "-webkit-text-fill-color",
        "-webkit-text-stroke",
        "-webkit-text-stroke-color",
        "-webkit-text-stroke-width",
    }
)
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_STYLE = re.compile(r"<style>(.*?)</style>", re.DOTALL)
# The deck sheet build_slide_html writes verbatim, told apart from its own sheets.
_DECK_SENTINEL = "/* the deck's own sheet */"


def _declarations(css: str) -> list[tuple[str, str, str]]:
    """Every (selector, property, value) of ``css``'s rules, white space collapsed."""
    found = []
    for selector, body in _RULE.findall(_COMMENT.sub("", css)):
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            name, value = declaration.split(":", 1)
            found.append(
                (" ".join(selector.split()), name.strip().lower(), " ".join(value.split()))
            )
    return found


def _inherited(css: str) -> set[tuple[str, str, str]]:
    return {
        declaration
        for declaration in _declarations(css)
        if declaration[1] in INHERITED_PROPERTIES or declaration[1].startswith("--")
    }


def _export_shell() -> str:
    """The sheets the export document wraps a deck's CSS in, as build_slide_html writes them."""
    document = build_slide_html(
        {"slide_id": "s1", "html": '<div class="slide">x</div>'},
        {"title": "T", "css": _DECK_SENTINEL, "scripts": "", "external_scripts": []},
    )
    sheets = _STYLE.findall(document)
    assert sheets.count(_DECK_SENTINEL) == 1, f"the deck's own sheet is not one of {len(sheets)}"
    return "\n".join(sheet for sheet in sheets if sheet != _DECK_SENTINEL)


class TestShellParity:
    def test_the_export_shell_gives_inherited_text_what_the_ui_shell_gives_it(self) -> None:
        """No inherited property is declared by one shell and not the other, on any selector.

        A shell's inherited declaration reaches every slide's text that does not
        set the property itself, so a difference is a difference in the text
        the user sees: the font the export's shell once gave ``body`` is the case.
        """
        export_inherited = _inherited(_export_shell())
        ui_inherited = _inherited(_frontend_preview_reset())
        assert export_inherited == ui_inherited, (
            "the shells give inherited text different values: the export's alone "
            f"{sorted(export_inherited - ui_inherited)}, the UI's alone "
            f"{sorted(ui_inherited - export_inherited)}"
        )

    def test_the_shell_readers_read_both_shells(self) -> None:
        """Non-vacuity: each shell's known declarations are read, so an empty set means none."""
        export_names = {name for _, name, _ in _declarations(_export_shell())}
        ui_names = {name for _, name, _ in _declarations(_frontend_preview_reset())}
        assert {"width", "height", "margin", "padding", "overflow"} <= export_names, export_names
        assert {"position", "inset", "box-sizing", "margin", "overflow"} <= ui_names, ui_names
        assert _inherited("body { font-family: Inter; color: red; --brand: x; width: 1px }") == {
            ("body", "font-family", "Inter"),
            ("body", "color", "red"),
            ("body", "--brand", "x"),
        }


_FRONTEND_SERVICES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "services"
# The frontend's capture shells: each file's builder, and how its template
# names the deck's CSS, which is the deck's sheet and not the shell's.
CAPTURE_SHELLS = {
    "pdf_client.ts": ("buildSlideHTML", "${slideDeck.css}"),
    "pptx_client.ts": ("buildSlideHTML", "${slideDeck.css}"),
    "screenshotCapture.ts": ("buildSlideHtml", "${css}"),
}
_INTERPOLATION = re.compile(r"\$\{[^}]*\}")


def _builder_source(file: str, function: str) -> str:
    """The source of ``export function <function>(`` in ``file``, to its closing brace."""
    source = (_FRONTEND_SERVICES / file).read_text(encoding="utf-8")
    start = source.index(f"export function {function}(")
    return source[start : source.index("\n}\n", start)]


def _capture_shell(file: str) -> str:
    """The sheet ``file``'s slide document wraps the deck's CSS in, read from the TS source.

    The builder's one ``<style>`` template literal, the deck's CSS taken out,
    the root reset filled in from slideDocument.ts and the slide size from the
    file's own constants. An interpolation this does not fill in fails, so a
    new one is read before the parity is trusted.
    """
    function, deck_css = CAPTURE_SHELLS[file]
    builder = _builder_source(file, function)
    sheets = re.findall(r"<style>(.*?)</style>", builder, re.DOTALL)
    assert len(sheets) == 1, f"{file} {function} writes {len(sheets)} <style> sheets, not one"
    source = (_FRONTEND_SERVICES / file).read_text(encoding="utf-8")
    sizes = {
        name: re.search(rf"^const {name} = (\d+);$", source, re.MULTILINE)
        for name in ("SLIDE_WIDTH", "SLIDE_HEIGHT")
    }
    assert all(sizes.values()), f"{file} no longer declares the slide size it interpolates"
    sheet = sheets[0].replace(deck_css, "")
    sheet = sheet.replace("${SLIDE_ROOT_RESET_STYLE}", _frontend_slide_root_reset())
    for name, found in sizes.items():
        sheet = sheet.replace("${" + name + "}", found.group(1))
    unread = _INTERPOLATION.findall(sheet)
    assert not unread, f"{file} {function}'s sheet interpolates what this does not read: {unread}"
    return sheet


class TestCaptureShellParity:
    @pytest.mark.parametrize("file", tuple(CAPTURE_SHELLS))
    def test_a_capture_shell_gives_inherited_text_what_the_ui_shell_gives_it(
        self, file: str
    ) -> None:
        """The PDF download's, the client PPTX's and the screenshots' documents give a slide's
        inherited text what the UI's document gives it, on any selector."""
        capture_inherited = _inherited(_capture_shell(file))
        ui_inherited = _inherited(_frontend_preview_reset())
        assert capture_inherited == ui_inherited, (
            f"{file}'s shell gives inherited text other values than the UI's: its own "
            f"{sorted(capture_inherited - ui_inherited)}, the UI's alone "
            f"{sorted(ui_inherited - capture_inherited)}"
        )

    @pytest.mark.parametrize("file", tuple(CAPTURE_SHELLS))
    def test_the_capture_shell_reader_reads_each_shell(self, file: str) -> None:
        """Non-vacuity: each shell's known declarations are read, so an empty set means none."""
        names = {name for _, name, _ in _declarations(_capture_shell(file))}
        assert {"width", "height", "margin", "padding", "overflow", "box-sizing"} <= names, names

    @pytest.mark.parametrize("file", tuple(CAPTURE_SHELLS))
    def test_a_capture_shells_runtime_markup_writes_no_sheet(self, file: str) -> None:
        """GUARD: the shell's one sheet is the one read. Its builder writes no other, and the
        trusted runtime it writes into <head> (trustedExportRuntimeMarkup()) is scripts alone."""
        function, _ = CAPTURE_SHELLS[file]
        builder = _builder_source(file, function)
        assert "${trustedExportRuntimeMarkup()}" in builder, f"{file} no longer writes the runtime"
        assert builder.count("<style") == 1, f"{file} {function} writes another sheet"
        markup = _builder_source("exportFrameRuntime.ts", "trustedExportRuntimeMarkup")
        assert "<script>" in markup and "<style" not in markup, markup


# A slide whose text has no font of its own anywhere: the deck has no CSS.
NO_FONT_PARAGRAPH = (
    "So what: route density is the lever. The two depots that consolidated their "
    "routes in the spring cut cost per drop by nine percent while on-time delivery "
    "held, and the same playbook applies to four more depots next quarter."
)
NO_FONT_SLIDE = (
    '<div class="slide" style="position:relative; width:1280px; height:720px; '
    'background:#FFFFFF">'
    '<p id="so-what" style="position:absolute; left:88px; top:120px; width:560px; '
    f'margin:0; font-size:24px; line-height:1.4; color:#1B3139">{NO_FONT_PARAGRAPH}</p>'
    "</div>"
)
# The font the export's shell gave body before Task 15 B7.
OLD_SHELL_FONT = "font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif"


def _normalised(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.slow
@requires_huashu_sidecar
@requires_ui_documents
class TestInheritedTextThroughTheEngine:
    def test_text_with_no_font_exports_in_the_face_and_lines_the_ui_draws(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The export document draws a fontless paragraph as the UI's does, and the deck keeps it.

        * The fixture tells the shells apart: the UI's document with the old
          shell font added draws other faces and breaks other lines.
        * The export document's faces for the paragraph are the UI document's.
        * The exported text item holds the UI document's lines, in order.
        """
        ui = ui_document(NO_FONT_SLIDE, css="")
        ui_faces = browser_faces(ui, "#so-what")
        ui_lines = [_normalised(line) for line in browser_lines(ui, "#so-what")]
        old_shell = ui.replace(
            "</head>", f"<style>html, body {{ {OLD_SHELL_FONT}; }}</style></head>"
        )
        assert (
            browser_faces(old_shell, "#so-what") != ui_faces
            and [_normalised(line) for line in browser_lines(old_shell, "#so-what")] != ui_lines
        ), (
            "fixture drift: the old shell font draws the paragraph as the UI does; the fixture "
            "no longer tells the shells apart"
        )

        export = slide_document(NO_FONT_SLIDE, css="", slide_id="snapshot-1")
        assert browser_faces(export, "#so-what") == ui_faces, (
            f"the export document draws the paragraph in {browser_faces(export, '#so-what')}, the "
            f"UI's document in {ui_faces}"
        )
        pptx, _ = export_slides([NO_FONT_SLIDE], css="", monkeypatch=monkeypatch)
        items = [
            shape
            for shape in slide_shapes(pptx)
            if shape.kind == "text" and "So what" in shape.text
        ]
        assert len(items) == 1, f"expected one text item holding the paragraph, got {len(items)}"
        # Every paragraph end and <a:br/> ends a line (slide_shapes writes each as "\n").
        exported_lines = [_normalised(line) for line in items[0].text.split("\n")]
        assert exported_lines == ui_lines, (
            f"the exported paragraph's lines are {exported_lines}; the UI's document breaks it "
            f"into {ui_lines}"
        )
