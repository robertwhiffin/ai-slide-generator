"""A slide whose script blocks its page fails alone, at the per-slide deadline (I1).

``render_slide.cjs`` gives each slide ``SLIDE_DEADLINE_MS``, from its browser's launch to
its last read. A slide whose script blocks its page's main thread (a busy loop) used to
hang every read after it, and with them the whole deck, until the sidecar's own timeout
(``SIDECAR_TIMEOUT_SECONDS``, 180 s) ended the export with no deck at all. Now that slide
is stopped at its deadline, its browser closed, and it fails with the failure entry the
routes report (``X-Huashu-Failures``); the deck goes on and is written with every other
slide.

The deadline is above every wait the engine bounds itself: a slide that those waits let
through, slow and exported as far as it settled, is not failed by the deadline instead.
"""

from __future__ import annotations

import json
import time

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    export_documents,
    node_json,
    requires_huashu_sidecar,
    requires_node,
    slide_document,
    slide_xml,
)

RENDER_SLIDE = pptx_from_html_huashu.SIDECAR_DIR / "render_slide.cjs"
CAPTURE = pptx_from_html_huashu.SIDECAR_DIR / "capture.cjs"

# The message a slide past its deadline fails with (render_slide.cjs).
PAST_ITS_DEADLINE = "did not finish within"
# A deck timeout of half the real one: a deck the deadline does not save ends at it, so a
# red run ends in a minute and a half, and a green one is well inside even this.
DECK_TIMEOUT_SECONDS = 90
# The share of its deadline a slide that finishes inside it spends blocked.
INSIDE_THE_DEADLINE = 0.75


def _deadline_ms() -> int:
    return node_json(
        f"console.log(JSON.stringify(require({json.dumps(str(RENDER_SLIDE))}).SLIDE_DEADLINE_MS));"
    )


def _blocked_after_load(milliseconds: int | None) -> str:
    """Script that blocks the page's main thread once it has loaded: for good, or for a while."""
    loop = (
        "for (;;) {}"
        if milliseconds is None
        else f"const until = Date.now() + {milliseconds}; while (Date.now() < until) {{}}"
    )
    return f"<script>addEventListener('load', () => setTimeout(() => {{ {loop} }}, 0));</script>"


def _slide(heading: str, script: str = "") -> str:
    return f'<div class="slide"><h1>{heading}</h1><p>Revenue grew 12%.</p>{script}</div>'


def _deck_texts(pptx: bytes, count: int) -> list[str]:
    return ["".join(slide_xml(pptx, index).itertext()) for index in range(count)]


@pytest.mark.slow
@requires_huashu_sidecar
class TestABlockedSlideFailsAlone:
    def test_a_slide_blocked_for_good_between_two_others_fails_at_its_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", DECK_TIMEOUT_SECONDS)
        deadline_seconds = _deadline_ms() / 1000
        documents = [
            slide_document(_slide("First slide"), slide_id="deadline-1"),
            slide_document(_slide("Blocked slide", _blocked_after_load(None)), slide_id="deadline-2"),
            slide_document(_slide("Third slide"), slide_id="deadline-3"),
        ]

        started = time.monotonic()
        pptx, failures = export_documents(documents, monkeypatch=monkeypatch)
        elapsed = time.monotonic() - started

        assert [failure["slide_index"] for failure in failures] == [1], failures
        assert PAST_ITS_DEADLINE in failures[0]["error"], failures
        texts = _deck_texts(pptx, 2)
        assert "First slide" in texts[0] and "Third slide" in texts[1], texts
        assert elapsed < deadline_seconds + 30, (
            f"the deck took {elapsed:.1f}s with a {deadline_seconds:g}s deadline"
        )

    def test_a_slide_that_finishes_just_inside_its_deadline_is_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", DECK_TIMEOUT_SECONDS)
        deadline_ms = _deadline_ms()
        blocked_ms = int(deadline_ms * INSIDE_THE_DEADLINE)
        document = slide_document(
            _slide("Slow slide", _blocked_after_load(blocked_ms)), slide_id="deadline-slow"
        )

        started = time.monotonic()
        pptx, failures = export_documents([document], monkeypatch=monkeypatch)
        elapsed = time.monotonic() - started

        assert failures == [], failures
        assert "Slow slide" in _deck_texts(pptx, 1)[0]
        assert elapsed > blocked_ms / 1000, (
            f"fixture drift: the slide took {elapsed:.1f}s, not the {blocked_ms / 1000:g}s it blocks"
        )


# The waits render_slide.cjs and capture.cjs bound themselves, each read from its module:
# network idle, the fonts (before and after the animations finish), the canvases' buffers
# and their settle, and one capture (a slide's captures stop at the first that times out).
_BOUNDED_WAITS = (
    ("render_slide", "NETWORK_IDLE_TIMEOUT_MS", 1),
    ("render_slide", "FONTS_READY_TIMEOUT_MS", 2),
    ("render_slide", "CANVAS_READY_TIMEOUT_MS", 1),
    ("render_slide", "CANVAS_SETTLE_MS", 1),
    ("capture", "CAPTURE_TIMEOUT_MS", 1),
)


@requires_node
def test_the_deadline_is_above_every_wait_the_engine_bounds_itself() -> None:
    modules = {"render_slide": RENDER_SLIDE, "capture": CAPTURE}
    names = {(module, name) for module, name, _ in _BOUNDED_WAITS}
    read = node_json(
        "const read = {};"
        + "".join(
            f"read[{json.dumps(module + '.' + name)}] = require({json.dumps(str(modules[module]))})"
            f".{name};"
            for module, name in sorted(names)
        )
        + f"read.deadline = require({json.dumps(str(RENDER_SLIDE))}).SLIDE_DEADLINE_MS;"
        + "console.log(JSON.stringify(read));"
    )
    waits = [read[f"{module}.{name}"] * times for module, name, times in _BOUNDED_WAITS]
    assert all(isinstance(wait, int) and wait > 0 for wait in waits), read
    assert read["deadline"] > sum(waits), (
        f"the {read['deadline']} ms deadline would fail a slide the engine's own waits "
        f"({sum(waits)} ms) let through"
    )
