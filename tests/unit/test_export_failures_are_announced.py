"""Two reads that used to fail silently say so on an ``[html2pptx]`` line, with no deck text.

* The canvas wait (``render_slide.cjs`` waitForCanvases): a canvas that never gets a
  drawing buffer ends the wait at its timeout, and the slide is read with its
  canvases as they are. The line, the sidecar's own, says how many canvases the
  slide has and how long it waited; a read that fails says its message by its
  length alone (log_line.cjs pageText). The wait used to be page.waitForFunction,
  whose predicate the slide CSP refused at once: it waited for nothing, and said
  nothing.
* A background gradient's middle colour (``snapshot.mjs`` gradientMiddle), the
  layer text over it is blended with: a gradient whose reading throws leaves the
  layer out, and the page-side line says so once a slide, which, as everything
  the page logs, is quoted with the debug text on and counted without it.
"""

from __future__ import annotations

import pytest

from tests.fixtures.export_snapshot_support import (
    export_logged,
    requires_huashu_sidecar,
    slide_document,
)

pytestmark = [pytest.mark.slow, requires_huashu_sidecar]

CANVAS_LINE = "[html2pptx] canvases: 1 canvas(es)"
UNREADY_CANVAS_BODY = (
    '<div class="slide"><h1>Unready canvas</h1><canvas width="0" height="0"></canvas></div>'
)

GRADIENT_LINE = "[html2pptx] a background gradient could not be read"
GRADIENT_WORD = "Zyqgradientword"
# Slide script that makes every reading of a linear-gradient value throw (its
# String.prototype.match, which the gradient parser calls), and two boxes of text over
# gradients: the line is said once.
THROWING_GRADIENT_BODY = (
    '<div class="slide"><script>(function () {'
    "  const match = String.prototype.match;"
    "  String.prototype.match = function (pattern) {"
    "    if (String(this).indexOf('linear-gradient(') >= 0) throw new Error('" + GRADIENT_WORD + "');"
    "    return match.call(this, pattern);"
    "  };"
    "})();</script>"
    '<p style="background: linear-gradient(90deg, #FF3621, #FFB347); font-size: 24px;">'
    "Over a gradient</p>"
    '<p style="background: linear-gradient(180deg, #1B3139, #618794); color: #fff; font-size: 24px;">'
    "Over another</p></div>"
)


def test_a_canvas_that_never_draws_is_said_on_the_sidecars_own_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged = export_logged([slide_document(UNREADY_CANVAS_BODY)], monkeypatch=monkeypatch)
    assert logged.failures == [], logged.failures

    lines = [line for line in logged.stderr.splitlines() if CANVAS_LINE in line]
    assert len(lines) == 1 and "5000 ms" in lines[0], lines


# Slide script whose canvases cannot be read: their width throws, its message the slide's.
CANVAS_WORD = "Zyqcanvasword"
THROWING_CANVAS_BODY = (
    '<div class="slide"><h1>Throwing canvas</h1><canvas></canvas><script>'
    "Object.defineProperty(HTMLCanvasElement.prototype, 'width', {"
    "  get() { throw new Error('" + CANVAS_WORD + "'); }, configurable: true });"
    "</script></div>"
)
CANVAS_FAILED_LINE = "[html2pptx] the canvas wait failed: "


def test_a_canvas_wait_that_waits_its_timeout_takes_it_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unready canvas is waited for: the slide's export takes the wait's 5 s and the
    2 s settle at least, where a wait that ends at once takes the settle alone."""
    import time

    started = time.monotonic()
    logged = export_logged([slide_document(UNREADY_CANVAS_BODY)], monkeypatch=monkeypatch)
    elapsed = time.monotonic() - started
    assert logged.failures == [], logged.failures
    assert elapsed >= 7, f"the export took {elapsed:.1f} s"


def test_a_canvas_that_cannot_be_read_is_said_by_its_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged = export_logged([slide_document(THROWING_CANVAS_BODY)], monkeypatch=monkeypatch)
    assert logged.failures == [], logged.failures

    lines = [line for line in logged.stderr.splitlines() if CANVAS_FAILED_LINE in line]
    assert len(lines) == 1 and "characters, not logged" in lines[0], lines
    assert CANVAS_WORD not in logged.stderr


def test_a_gradient_that_cannot_be_read_is_said_once_without_its_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged = export_logged(
        [slide_document(THROWING_GRADIENT_BODY)], monkeypatch=monkeypatch, debug_text=True
    )
    assert logged.failures == [], logged.failures

    lines = [line for line in logged.stderr.splitlines() if GRADIENT_LINE in line]
    assert len(lines) == 1, lines
    assert GRADIENT_WORD not in lines[0], lines[0]
