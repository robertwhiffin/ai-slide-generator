"""An export leaves nothing in the temporary directory, however it ends (I2).

``emit_deck.mjs`` writes each slide's HTML into a ``huashu-deck-*`` directory of its own,
since the browser loads a slide from a file, and used never to remove it: every export's
slides stayed on disk (54,111 such directories were found on one laptop), and with them
every deck's content. Now:

* ``emit_deck.mjs`` removes it in a ``finally``, however its deck ends (written, partly,
  or with every slide failed);
* the wrapper (``pptx_from_html_huashu._export_deck``) runs the sidecar with a ``TMPDIR``
  of its own, the ``TemporaryDirectory`` it writes the deck to, made inside the
  ``TMPDIR`` the sidecar is given: whatever the sidecar and its browsers leave there (a
  sidecar ended at its timeout, whose ``finally`` never runs, and the browsers'
  profiles) goes with it.

Each export here is given a ``TMPDIR`` of the test's own, which holds nothing once the
export has ended: a deck, a deck with a failed slide, and a sidecar ended at its timeout.
The sidecar run on its own, without the wrapper, leaves nothing either.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu
from src.services.pptx_from_html_huashu import HuashuExportError
from tests.fixtures.export_snapshot_support import (
    export_documents,
    requires_huashu_sidecar,
    run_node,
    slide_document,
)

# A sidecar timeout short enough for a test, long enough for the browser to launch and
# load the slide, and well short of the slide's own deadline (render_slide.cjs).
SHORT_SIDECAR_TIMEOUT_SECONDS = 8
SIDECAR_RUN_TIMEOUT_SECONDS = 120

ORDINARY = '<div class="slide"><h1>Quarterly results</h1><p>Revenue grew 12%.</p></div>'
# A slide that fails: its page navigates away from it (request_guard.cjs).
LEAVING = '<div class="slide"><h1>Leaving</h1><script>location.href = "about:blank#gone";</script></div>'
# A slide whose page blocks its main thread once it has loaded, for good.
BLOCKED = (
    '<div class="slide"><h1>Blocked</h1><script>addEventListener("load", () => '
    "setTimeout(() => { for (;;) {} }, 0));</script></div>"
)


def _left_behind(directory: Path) -> list[str]:
    return sorted(str(path.relative_to(directory)) for path in directory.rglob("*"))


@pytest.fixture
def own_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The TMPDIR the export is given (sidecar_subprocess_env passes it on), empty."""
    directory = tmp_path / "tmpdir"
    directory.mkdir()
    monkeypatch.setenv("TMPDIR", str(directory))
    return directory


@pytest.mark.slow
@requires_huashu_sidecar
class TestAnExportLeavesNothing:
    def test_a_deck(self, own_tmpdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pptx, failures = export_documents([slide_document(ORDINARY)], monkeypatch=monkeypatch)

        assert pptx and failures == [], failures
        assert _left_behind(own_tmpdir) == []

    def test_a_deck_with_a_failed_slide(
        self, own_tmpdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        documents = [slide_document(ORDINARY, slide_id="kept"), slide_document(LEAVING, slide_id="gone")]

        pptx, failures = export_documents(documents, monkeypatch=monkeypatch)

        assert pptx and [failure["slide_index"] for failure in failures] == [1], failures
        assert _left_behind(own_tmpdir) == []

    def test_a_sidecar_ended_at_its_timeout(
        self, own_tmpdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", SHORT_SIDECAR_TIMEOUT_SECONDS
        )
        with pytest.raises(HuashuExportError, match="timed out"):
            export_documents([slide_document(BLOCKED)], monkeypatch=monkeypatch)

        assert _left_behind(own_tmpdir) == []


def test_the_sidecars_tmpdir_is_the_decks_own_directory_inside_the_one_it_is_given(
    own_tmpdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where an operator's TMPDIR says, and the directory the deck is written to."""
    runs: list[tuple[list[str], dict[str, str]]] = []

    def run(command: list[str], *, env: dict[str, str], **_: object) -> subprocess.CompletedProcess:
        runs.append((command, dict(env)))
        Path(command[-1]).write_bytes(b"deck")
        return subprocess.CompletedProcess(command, 0, b"", b'__HUASHU_RESULT__ {"failed": []}\n')

    monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
    monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", run)

    assert pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}]) == (b"deck", [])

    ((command, env),) = runs
    sidecar_tmpdir = Path(env["TMPDIR"])
    assert sidecar_tmpdir.parent == own_tmpdir, env["TMPDIR"]
    assert Path(command[-1]).parent == sidecar_tmpdir, command
    assert _left_behind(own_tmpdir) == []


def _run_sidecar(tmpdir: Path, out: Path, slides: list[dict]) -> subprocess.CompletedProcess:
    env = {**pptx_from_html_huashu.sidecar_subprocess_env(), "TMPDIR": str(tmpdir)}
    payload = json.dumps({"title": "deck", "slides": slides, "bypassValidation": True})
    return run_node(
        [str(pptx_from_html_huashu.SIDECAR_SCRIPT), str(out)],
        input=payload.encode("utf-8"),
        env=env,
        timeout=SIDECAR_RUN_TIMEOUT_SECONDS,
        cwd=None,
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheSidecarRemovesItsOwnDirectory:
    """emit_deck.mjs run without the wrapper: its slides' directory goes, however the deck ends."""

    @pytest.mark.parametrize(
        ("bodies", "written"),
        [((ORDINARY,), True), ((LEAVING,), False)],
        ids=["written", "every-slide-failed"],
    )
    def test_its_slides_directory_is_removed(
        self, tmp_path: Path, bodies: tuple[str, ...], written: bool
    ) -> None:
        tmpdir = tmp_path / "tmpdir"
        tmpdir.mkdir()
        out = tmp_path / "out.pptx"
        slides = [{"html": slide_document(body)} for body in bodies]

        process = _run_sidecar(tmpdir, out, slides)

        assert out.exists() is written, process.stderr[-2000:]
        leftovers = [name for name in os.listdir(tmpdir) if name.startswith("huashu-deck-")]
        assert leftovers == [], leftovers
