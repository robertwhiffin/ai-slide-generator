"""Wrapper-chain depth: the sidecar's slide-root walk must not cap out.

5a6de59 made the huashu sidecar promote the slide root through EVERY consecutive
sole-element-child semantic wrapper, matching the backend's
``_promote_through_slide_wrapper`` (``src/utils/html_utils.py``). The backend's
walk is a plain ``while True`` — unbounded. The sidecar's was a
``for depth < MAX_WRAPPER_DEPTH`` with ``MAX_WRAPPER_DEPTH = 16``.

That reintroduced, at a new boundary, exactly the defect 5a6de59 fixed at depth
one: the two surfaces disagree about a deck. The backend promotes a 17-level
chain to its outermost wrapper and serialises THAT as the slide's HTML
(``slide_deck.py`` ``str(slide_element)``), so the sidecar is handed a
``<section>`` as body's direct child, fails to recognise it, takes the
``'no-root'`` branch and exports the slide WHITE while the app renders it
correctly.

The cap could never buy safety it was needed for: a DOM parent → child chain is
finite and acyclic, so descending it terminates on its own. The walk now ends at
the real structural invariant — *there is no sole element child* — and carries no
depth number at all.

Why these tests are artifact-level: a DOM assertion can only show the locator
matched, not that the ground reached the file, and a rootless deck and a broken
locator both end up white. So the background fill is read back out of
``ppt/slides/slide1.xml`` after a real emitter run. The branch actually taken
(and the walk's cost per depth) comes from the sidecar's own
``probe_bg_transfer.mjs``.

The reviewed gap this module closes: the existing suite
(``test_export_slide_root_background.py``) covers one- and two-level chains only,
and no sibling, ``<style>``/``<script>`` or cap-boundary case at all.

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json
import re
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.api.routes.export import build_slide_html
from src.domain.slide_deck import SlideDeck
from src.services import pptx_from_html_huashu
from src.utils.html_utils import find_slide_roots
from tests.unit.test_export_slide_root_background import (
    FIXTURE_DIR,
    GROUND,
    LOST,
    PROBE_SCRIPT,
    requires_huashu_sidecar,
)

# Depths exercised end to end. 16 and 17 straddle the removed cap: 16 was the
# last depth that worked and 17 was the first that exported white, so 17 is the
# case that must go from RED to green. 400 stands for "arbitrarily deep" —
# imported template HTML is arbitrary and a pinned-template generation retains
# whatever structure it was given. 508 and 509 sit just under Chromium's own parser
# ceiling (see TestChromiumParserNestingLimit): 509 is the deepest chain that exists
# in the DOM at all, and therefore the real end of the range this walk is
# responsible for.
DEPTHS = (1, 2, 3, 16, 17, 32, 400, 508, 509)

# Chromium caps a PARSED document's tree depth at 512 (measured: a 520-wrapper
# chain arrives 512 deep). With html > body above them, 509 wrapper levels is the
# deepest chain that survives parsing intact; at 510 the parser stops nesting and
# reparents the overflow. Both numbers are measured, not derived.
LAST_NESTED_DEPTH = 509
REPARSED_DEPTH = 510

# Ceiling for the preprocess pass on ONE slide, per depth. Generous on purpose:
# this is a "does the walk blow up" tripwire (a quadratic or re-entrant walk
# would run away at depth 400), not a benchmark. Real numbers are single-digit
# milliseconds at every depth and are reported by the timing test below.
PREPROCESS_MS_CEILING = 2000


SLIDE_BODY = (
    '<div class="slide">'
    "<h1>Acme Depth Chain</h1>"
    "<p>Synthetic fixture slide.</p>"
    "</div>"
)


def _document(markup: str, *, extra_css: str = "") -> str:
    """Wrap slide markup in a standalone 1280×720 document.

    ONLY a direct-child ``<section>`` of body carries a ground: every inner
    wrapper level and the ``.slide`` itself is transparent. That is what makes
    these tests discriminating rather than colour-blind — resolving to any inner
    level, or failing to resolve at all, reads no background and emits white.

    ``extra_css`` is appended after the base rules, so a fixture that adds a
    sibling next to the ``.slide`` can keep the slide within 1280×720 and stay
    clear of huashu's own design-rule validation (overflow, text near the bottom
    edge). Those rules are about layout quality and would otherwise reject the
    fixture before the locator under test ever mattered.
    """
    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      body {{ width: 1280px; height: 720px; }}
      body > section {{
        background: #{GROUND};
        color: #ffffff;
        font-family: Arial, sans-serif;
      }}
      .slide {{ width: 1280px; height: 720px; padding: 72px 88px; }}
      h1 {{ font-size: 64px; }}
      p {{ font-size: 24px; }}
      {extra_css}
    </style>
  </head>
  <body>{markup}</body>
</html>
"""


def _chain_document(depth: int, *, inner_sibling: str = "", extra_css: str = "") -> str:
    """A model-style slide document with ``depth`` promotable wrapper levels.

    Wrappers alternate ``<section>``/``<article>`` so the chain exercises both
    promotable tags rather than repeating one, and the outermost level is always
    a ``<section>`` so a single ``body > section`` rule can paint it.

    ``inner_sibling`` is markup placed next to the ``.slide`` inside the
    innermost wrapper, used to pin what does and does not block the walk.
    """
    tags = ["section" if index % 2 == 0 else "article" for index in range(depth)]
    markup = SLIDE_BODY + inner_sibling
    for tag in reversed(tags):
        markup = f"<{tag}>{markup}</{tag}>"
    return _document(markup, extra_css=extra_css)


def _build_html(monkeypatch: pytest.MonkeyPatch, html: str) -> bytes:
    """Export one in-memory slide document through the real huashu pipeline."""
    monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
    pptx, failures = pptx_from_html_huashu.build_pptx_huashu(
        "slide root depth", [{"html": html}]
    )
    assert failures == [], f"huashu rejected the deck: {failures}"
    assert pptx, "huashu produced no pptx bytes"
    return pptx


def _slide_background(pptx: bytes) -> str:
    """The slide's background fill, read out of the emitted pptx."""
    with zipfile.ZipFile(BytesIO(pptx)) as zf:
        xml = zf.read("ppt/slides/slide1.xml").decode("utf-8")
    bg = re.search(r"<p:bg>.*?</p:bg>", xml, re.S)
    assert bg is not None, "slide carries no <p:bg> element at all"
    fills = re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', bg.group(0))
    assert len(fills) == 1, f"expected one background fill, got {fills}"
    return fills[0].upper()


def _probe(tmp_path: Path, documents: dict[str, str]) -> dict[str, dict]:
    """Run the real PREPROCESS_SOURCE over named documents; keyed by name."""
    paths = []
    for name, html in documents.items():
        path = tmp_path / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        paths.append(path)
    proc = subprocess.run(
        ["node", str(PROBE_SCRIPT), *[str(path) for path in paths]],
        cwd=pptx_from_html_huashu.SIDECAR_DIR,
        env=pptx_from_html_huashu.sidecar_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=pptx_from_html_huashu.SIDECAR_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stderr}"
    results = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return {Path(result["file"]).stem: result for result in results}


@requires_huashu_sidecar
class TestWrapperChainDepth:
    """A promotable chain must resolve at EVERY depth, with no cap."""

    @pytest.mark.parametrize("depth", DEPTHS)
    def test_chain_of_any_depth_exports_the_wrapper_ground(
        self, monkeypatch: pytest.MonkeyPatch, depth: int
    ) -> None:
        """The ground reaches the artifact however deep the chain is.

        RED before the fix at depth 17 and beyond: the walk gave up after 16
        levels, no root resolved, and ``<p:bg>`` came out ``FFFFFF``.
        """
        pptx = _build_html(monkeypatch, _chain_document(depth))
        assert _slide_background(pptx) == GROUND, (
            f"depth={depth} lost the slide-root ground"
        )

    def test_the_removed_cap_boundary_is_no_longer_a_cliff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Depth 16 and 17 must be indistinguishable in the artifact.

        The two documents differ by exactly one wrapper level, so any difference
        between the two exports is attributable to that level alone. This is the
        cap boundary stated as an invariant instead of a number: the 16→17 step
        must be as uneventful as the 2→3 step.
        """
        at_cap = _build_html(monkeypatch, _chain_document(16))
        past_cap = _build_html(monkeypatch, _chain_document(17))

        assert _slide_background(at_cap) == GROUND
        assert _slide_background(past_cap) == GROUND
        assert _slide_background(past_cap) == _slide_background(at_cap)


@requires_huashu_sidecar
class TestBackendSidecarDepthParity:
    """The backend is the specification; the sidecar has to agree with it.

    These run the PRODUCTION path — the real deck parser picks the slide root and
    the real per-slide document builder places it as body's direct child — so
    they reproduce the deployed defect rather than a synthetic stand-in.
    """

    @pytest.mark.parametrize("depth", DEPTHS)
    def test_backend_promotes_to_the_outermost_wrapper_at_any_depth(
        self, depth: int
    ) -> None:
        """Pins the spec side: promotion is unbounded, so the root is level 0."""
        soup = BeautifulSoup(_chain_document(depth), "html.parser")
        roots = find_slide_roots(soup)

        assert len(roots) == 1, f"depth={depth}: expected one slide root"
        assert roots[0].name == "section", (
            f"depth={depth}: backend promoted to <{roots[0].name}>, not the "
            "outermost <section>"
        )
        assert roots[0].parent is not None and roots[0].parent.name == "body", (
            f"depth={depth}: promoted root is not body's direct child"
        )

    @pytest.mark.parametrize("depth", DEPTHS)
    def test_production_path_keeps_the_ground_at_any_depth(
        self, monkeypatch: pytest.MonkeyPatch, depth: int
    ) -> None:
        """Backend-chosen root → real slide document → real emitter → artifact.

        This is the reviewer's reachability argument made executable: whatever
        the backend promotes to arrives here as body's direct child, so a
        sidecar that stops earlier than the backend exports white.
        """
        deck = SlideDeck.from_html_string(_chain_document(depth)).to_dict()
        assert len(deck["slides"]) == 1, f"depth={depth}: expected one slide"
        slide_html = build_slide_html(deck["slides"][0], deck)
        pptx = _build_html(monkeypatch, slide_html)
        assert _slide_background(pptx) == GROUND, (
            f"depth={depth}: production path lost the slide-root ground"
        )


@requires_huashu_sidecar
class TestPromotionBlockers:
    """What must STILL stop the walk, now that no depth number does.

    Each case is fed to the sidecar as-is, so the assertion is about
    ``wrapsSlideRoot``'s own decision. A blocked shape resolves to no root and
    exports ``FFFFFF``; over-promoting would paint the wrapper ground instead.
    These pin the semantics the cap removal must not change.
    """

    def test_an_element_sibling_blocks_promotion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two element children means the wrapper is not a sole-child wrapper.

        Matches the backend's ``len(element_children) != 1``. The aside is taken
        out of flow so the slide still lays out legally; the block is structural
        (an element is an element), not a consequence of where it renders.
        """
        html = _chain_document(
            2,
            inner_sibling='<h2 class="aside">Acme aside</h2>',
            extra_css=".aside { position: absolute; top: 0; left: 0; font-size: 24px; }",
        )
        assert _slide_background(_build_html(monkeypatch, html)) == LOST

    def test_a_style_sibling_blocks_promotion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``<style>`` is an element child and so blocks, as it does server-side.

        Filtering ``<style>``/``<script>`` out of the count would promote a
        wrapper the backend refuses to promote — an over-promotion the previous
        round removed. This keeps it removed.
        """
        html = _chain_document(2, inner_sibling="<style>.x{color:#ffffff}</style>")
        assert _slide_background(_build_html(monkeypatch, html)) == LOST

    def test_a_script_sibling_blocks_promotion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same for ``<script>``: counted, therefore blocking."""
        html = _chain_document(2, inner_sibling="<script>var acme=1;</script>")
        assert _slide_background(_build_html(monkeypatch, html)) == LOST

    def test_comments_whitespace_and_text_stay_transparent_at_depth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-element nodes never block, at any depth.

        ``.children`` is element-only, which is what makes this true; the test
        exists so a future rewrite that reaches for ``childNodes`` fails here.
        """
        html = _chain_document(
            17, inner_sibling="<!-- Acme note -->\n  bare text\n  "
        )
        assert _slide_background(_build_html(monkeypatch, html)) == GROUND

    def test_a_div_is_never_promoted_however_deep_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``<div>`` is neither a candidate wrapper nor a link in the chain.

        The document's ground sits on the outer ``body > section``; the
        interposed ``<div>`` breaks the semantic chain, so the walk must stop and
        the export must NOT pick the wrapper ground up.
        """
        html = _document(f"<section><div><article>{SLIDE_BODY}</article></div></section>")
        assert _slide_background(_build_html(monkeypatch, html)) == LOST

    def test_a_wrapper_holding_several_slides_stays_a_container(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A multi-slide wrapper is a deck-level container, not a slide root.

        Both slides are halved so the pair fits the 1280×720 body and huashu's
        overflow rule does not reject the fixture before the locator matters.
        """
        html = _chain_document(
            2,
            inner_sibling=(
                '<div class="slide"><h1>Acme Second</h1>'
                "<p>Synthetic fixture slide.</p></div>"
            ),
            extra_css=".slide { height: 360px; padding: 36px 88px; }",
        )
        assert _slide_background(_build_html(monkeypatch, html)) == LOST


@requires_huashu_sidecar
class TestChromiumParserNestingLimit:
    """Where the walk stops being able to help, and why that is not a bug here.

    Past 509 wrapper levels the two surfaces stop being handed the same tree.
    BeautifulSoup has no nesting limit, so the backend promotes a 510-level chain
    to its outermost wrapper and serialises THAT as the slide's HTML — but
    Chromium's parser caps tree depth at 512, so when the sidecar loads that HTML
    the overflow is REPARENTED: the innermost wrapper ends up holding the
    remaining wrappers AND the ``.slide`` as siblings. The sole-child chain the
    backend walked simply is not in the DOM any more.

    This is deliberately not chased. Resolving the reparsed shape would mean
    promoting a wrapper with several element children, which is exactly what the
    backend refuses and what ``TestPromotionBlockers`` pins as must-block — so
    "fixing" it would contradict the spec the sidecar exists to conform to. A
    510-deep chain of sole-child semantic wrappers is also a shape no real bundle
    produces; the deepest observed in a real bundle is two.

    What these tests DO require is that the limit is measured, pinned, and
    ATTRIBUTABLE — a rootless deck and a broken locator both export white, so the
    log has to be able to tell them apart.
    """

    def test_the_deepest_chain_chromium_nests_still_resolves(
        self, tmp_path: Path
    ) -> None:
        """509 is not a cliff we chose — it is the last depth that reaches us."""
        results = _probe(
            tmp_path, {f"depth_{LAST_NESTED_DEPTH}": _chain_document(LAST_NESTED_DEPTH)}
        )
        assert results[f"depth_{LAST_NESTED_DEPTH}"]["bgTransferred"] == "solid"

    def test_one_level_deeper_resolves_to_no_root(self, tmp_path: Path) -> None:
        """The honest outcome for a tree that no longer holds the chain."""
        results = _probe(
            tmp_path, {f"depth_{REPARSED_DEPTH}": _chain_document(REPARSED_DEPTH)}
        )
        assert results[f"depth_{REPARSED_DEPTH}"]["bgTransferred"] == "no-root"

    def test_the_backend_still_promotes_at_that_depth(self) -> None:
        """Pins that the divergence is the BROWSER's, not a sidecar regression.

        The spec side is unaffected — which is precisely why the sidecar cannot
        follow it here, and why the log has to say so.
        """
        roots = find_slide_roots(
            BeautifulSoup(_chain_document(REPARSED_DEPTH), "html.parser")
        )

        assert len(roots) == 1
        assert roots[0].name == "section"
        assert roots[0].parent is not None and roots[0].parent.name == "body"

    def test_the_reparsed_shape_is_reported_and_names_what_it_saw(
        self, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """The diagnostic must distinguish "pathological deck" from "we regressed".

        ``several element children`` is the reparse signature: the walk found a
        wrapper level holding more than one element child, which is the shape
        Chromium reparenting produces and the shape the backend refuses to
        promote. Reading it back out of the emitter's own stderr is what makes it
        attributable — that is the stream ``pptx_from_html_huashu`` echoes into the
        app log.

        huashu's layout validation rejects this fixture (the reparented wrappers
        overflow the body), so the export is allowed to fail here; the diagnostic
        is emitted by the preprocess pass, which runs first either way.
        """
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        pptx_from_html_huashu.build_pptx_huashu(
            "slide root depth", [{"html": _chain_document(REPARSED_DEPTH)}]
        )
        stderr = capfd.readouterr().err

        assert "[preprocess] no slide root:" in stderr, (
            f"no attributable diagnostic in the emitter output:\n{stderr[-2000:]}"
        )
        assert "several element children" in stderr
        # …and the node-side line that says what it COST, in the same stream.
        assert "resolved NO root" in stderr

    def test_a_genuinely_rootless_deck_is_reported_the_same_way(
        self, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """Attribution is not special-cased to deep chains.

        ``rootless.html`` has no wrapper candidates at all, so this pins the other
        end of the diagnostic: it still names body's children and still says the
        slide will export white, with no candidate list to show.
        """
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        html = (FIXTURE_DIR / "rootless.html").read_text(encoding="utf-8")
        pptx_from_html_huashu.build_pptx_huashu("slide root depth", [{"html": html}])
        stderr = capfd.readouterr().err

        assert "[preprocess] no slide root:" in stderr
        assert "wrapper candidates (none)" in stderr
        assert "resolved NO root" in stderr


@requires_huashu_sidecar
class TestWalkCost:
    """Removing the cap must not make deep input expensive."""

    def test_preprocess_cost_does_not_blow_up_with_depth(
        self, tmp_path: Path, record_property
    ) -> None:
        """Report ms per depth and hold every one under the tripwire.

        One browser, one page per document, timing the preprocess pass only, so
        the number reflects the walk rather than Chromium startup.
        """
        documents = {f"depth_{depth}": _chain_document(depth) for depth in DEPTHS}
        results = _probe(tmp_path, documents)

        timings = {depth: results[f"depth_{depth}"]["ms"] for depth in DEPTHS}
        report = " | ".join(f"depth_{d} {timings[d]}ms" for d in DEPTHS)
        record_property("preprocess_ms_by_depth", report)
        print(f"\npreprocess cost by wrapper depth: {report}")

        for depth in DEPTHS:
            assert results[f"depth_{depth}"]["bgTransferred"] == "solid", (
                f"depth={depth} did not take the solid-ground branch"
            )
            assert timings[depth] < PREPROCESS_MS_CEILING, (
                f"depth={depth} took {timings[depth]}ms, over the "
                f"{PREPROCESS_MS_CEILING}ms tripwire: {report}"
            )
