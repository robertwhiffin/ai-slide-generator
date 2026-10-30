"""Task 7a (architect deck style): the offline eval harness scores deck styles, and the builder and
build_reviewer packs gain deck-style cases. Offline: no model, no network, no browser.

Names this file fixes for the implementer (the brief, read through C19-C24):

* ``scorers._deck_style_score(structured, expect, design_system_active) -> (bool, str)`` scores an
  architect build answer's ``deck_spec.deck_style``. It passes only when:
  the style is present and ``sanitise_deck_style`` returns it unchanged with ``()`` notes; it has
  1-12 components; its CSS is at most ``DECK_STYLE_MAX_CHARS``; every slide has a non-blank
  ``look``; and, with a design system active, the CSS holds no hex colour literal.
  A failure's rationale names its cause. The needles, matched case-insensitively:
  ``deck_style`` (no style); ``sanitis`` plus the dropped selector (a sanitiser note);
  ``component`` (too few or too many); the ``DECK_STYLE_MAX_CHARS`` number (too long);
  ``look`` (a blank or missing look); the hex literal itself (a raw hex under a design system).
* ``scorers.expected_category_score(..., design_system_active=...)``: an architect case whose
  ``expect`` has ``deck_style: true`` ANDs ``_deck_style_score`` after the intent check. Without the
  key the deck style is not checked. ``mlflow_run``'s ``expected_category`` scorer passes
  ``design_system_active=expectations.get("design_system_active")``.
* ``scorers.deck_style_use_score(html, payload, expect) -> (bool, str)``, for a builder case whose
  ``expect`` has ``deck_style_classes``. Needles: the inline property's name, the undefined class,
  the listed class that is not used.
* ``mlflow_run``'s ``render_measures`` scorer loads the row's case (as ``judge`` does, split
  included) and ANDs ``deck_style_use_score`` when ``expect`` has ``deck_style_classes``. Every other
  case scores exactly as ``render_measures_score`` alone, rationale included.
* Render CSS (C21): ``meridian_section_css() + "\\n\\n" + payload["deck_style"]["css"]`` when the
  case payload has a deck style, else ``meridian_section_css()``, in ``predict_fn`` and in
  ``run_eval._calibration_render_fn``.
* ``judge._brief_or_finding`` for builder and build_reviewer adds ``deck_style`` when the payload
  has one, and only then.
* ``evals/fixtures/deck_style_technical.json`` is a ``DeckStyle.model_dump()``.
* New case ids on both splits: builder ``deck_style_code`` and ``deck_style_table``;
  build_reviewer ``deck_style_inline_paint`` and ``deck_style_clean``. Each ``calibration.json`` is
  ``{"should_fail": <role output>}`` (C23), and the deterministic scorer fails that output.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import re
from types import SimpleNamespace

import pytest
import tinycss2
from mlflow.entities import Feedback

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals import run_eval as cli
from evals.harness import case, mlflow_run, scorers
from evals.harness import judge as judge_mod
from evals.harness import render as render_mod
from evals.harness.case import Case, split_kwargs
from evals.harness.render import RenderMeasures
from evals.harness.runner import RunResult
from evals.harness.scorers import expected_category_score
from src.domain.deck_spec import DeckStyle
from src.domain.deck_style import (
    DECK_STYLE_MAX_CHARS,
    DECK_STYLE_MAX_COMPONENTS,
    DECK_STYLE_TARGET_CHARS,
    css_class_names,
    html_class_names,
    sanitise_deck_style,
)

FIXTURE = case.EVALS_DIR / "fixtures" / "deck_style_technical.json"
SPLITS = ("train", "heldout")
BUILDER_CASES = ("deck_style_code", "deck_style_table")
REVIEWER_CASES = ("deck_style_inline_paint", "deck_style_clean")
NEW_CASES = [("builder", cid) for cid in BUILDER_CASES] + [("build_reviewer", cid) for cid in REVIEWER_CASES]
TECHNICAL_PIECES = {
    "dk-code", "dk-table", "dk-badge", "dk-badge--measured", "dk-badge--untested",
    "dk-steps", "dk-callout", "dk-note",
}
TOKEN_SPANS = {"kw", "fn", "str", "cm"}
JUDGE_EP = "stub-judge-endpoint"
CLEAN = RenderMeasures(overflow_px=0.0, min_contrast=21.0, rendered=True)
OVERFLOW = RenderMeasures(overflow_px=40.0, min_contrast=21.0, rendered=True)

# A live-looking deck style: comments, indentation, a quoted font name. The sanitiser returns it
# as the same object with () notes (asserted below, so the scorer tests stand on a clean base).
STYLE_CSS = """/* The deck's code block, with its token spans. */
.dk-code {
  background: var(--brand-core-surface);
  color: var(--brand-core-text);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: var(--fs-caption);
}
.dk-code .kw { color: var(--brand-core-primary); }

.dk-note { color: var(--brand-core-muted); font-size: var(--fs-caption); }
"""
COMPONENTS = [
    {"name": "code block", "class_names": ["dk-code"], "use": "Any SQL or shell listing.",
     "example_html": '<pre class="dk-code"><span class="kw">SELECT</span> 1;</pre>'},
    {"name": "note", "class_names": ["dk-note"], "use": "A one-line caveat under an exhibit.",
     "example_html": '<p class="dk-note">Measured on one cluster.</p>'},
]
HEX_RULE = ".dk-code .str { color: #ff0000; }\n"
UNSCOPED_RULE = ".slide { color: var(--brand-core-primary); }\n"
BUILD_EXPECT = {"intent": "build", "deck_style": True}
LOOK = "Two columns: the claim and three points on the left, a dk-code listing on the right."

GOOD_HTML = """<section class="slide">
  <p class="eyebrow">Replication</p>
  <h2 class="slide-title">One statement publishes every table to the lakehouse</h2>
  <div class="content" style="display:flex;gap:var(--space-md);margin-top:var(--space-sm)">
    <pre class="dk-code"><span class="kw">CREATE PUBLICATION</span> lakehouse FOR ALL TABLES;</pre>
    <p class="dk-note">Measured on a four-node cluster.</p>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>4</span></div>
</section>
"""
USE_EXPECT = {"deck_style_classes": ["dk-code", "dk-note"]}
PAINT = {
    "color": "#1e293b",
    "background": "#1e293b",
    "background-color": "var(--brand-core-surface)",
    "font-size": "13px",
    "font-family": "monospace",
    "border-color": "var(--brand-core-border)",
}


# --------------------------------------------------------------------------- helpers

def _style(css=STYLE_CSS, components=None) -> dict:
    return {"css": css, "components": copy.deepcopy(COMPONENTS if components is None else components)}


def _spec(style, *, look=LOOK) -> dict:
    """The gold Meridian deck, every slide given ``look``, carrying ``style`` (None: no deck style)."""
    spec = copy.deepcopy(case.gold_deck_spec())
    for slide in spec["slides"]:
        slide["look"] = look
    spec["deck_style"] = copy.deepcopy(style)
    return spec


def _build(spec) -> dict:
    return {
        "intent": "build", "message": "Here is the deck.", "deck_spec": spec,
        "data_request": None, "target_positions": [], "proposed_design_contract": None,
    }


def _fixture_raw() -> dict:
    return json.loads(FIXTURE.read_text())


def _painted(prop: str, value: str) -> str:
    """GOOD_HTML with ``prop: value`` added to the layout div's inline style."""
    old = 'style="display:flex;gap:var(--space-md);margin-top:var(--space-sm)"'
    assert old in GOOD_HTML
    return GOOD_HTML.replace(old, f'style="display:flex;gap:var(--space-md);{prop}: {value};margin-top:var(--space-sm)"')


def _use_payload() -> dict:
    return {"section_css": case.meridian_section_css(), "deck_style": _style()}


def _builder_case(cid="styled", *, agent_key="builder", deck_style=None, expect=None) -> Case:
    payload = {
        "position": 4,
        "slide_spec": {"position": 4, "purpose": "p", "content_brief": "b", "look": LOOK},
        "section_css": case.meridian_section_css(),
    }
    if deck_style is not None:
        payload["deck_style"] = deck_style
    return Case(cid, agent_key, "positive", True, "", payload=payload,
                reference={"position": 4, "html": GOOD_HTML, "scripts": ""}, expect=expect or {})


class _FakeRunner:
    def __init__(self, html="<section class='slide'>x</section>"):
        self.html = html

    def run(self, config, payload, *, design_system_active):
        return RunResult(
            status="completed", structured={"position": 4, "html": self.html, "scripts": ""},
            raw=None, prompt=None, latency_ms=1.0, input_tokens=None, output_tokens=None,
            error_detail=None, infra_error=False)


class _RenderSpy:
    def __init__(self, measures=CLEAN):
        self.measures = measures
        self.calls = []

    def __call__(self, html, scripts="", **kwargs):
        self.calls.append({"html": html, "scripts": scripts, **kwargs})
        return self.measures


def _patch_judge(monkeypatch):
    monkeypatch.setattr(judge_mod, "build_judge",
                        lambda *a, **k: (lambda **kw: Feedback(value="pass", rationale="stub")))


def _scorer(agent_key, name):
    by_name = {s.name: s for s in mlflow_run.build_scorers(agent_key, judge_endpoint=JUDGE_EP)}
    assert name in by_name, f"no scorer named {name!r}; got {sorted(by_name)}"
    return by_name[name]


def _outputs(structured, *, render=None) -> dict:
    return {
        "structured": structured, "raw": None,
        "render": dataclasses.asdict(render) if render is not None else None,
        "latency_ms": 1.0, "input_tokens": None, "output_tokens": None,
        "status": "completed", "infra_error": False, "error_detail": None,
    }


def _row(c: Case, split="train") -> dict:
    return mlflow_run.build_dataset([c], repeats=1, split=split)[0]


def _run(scorer, c: Case, structured, *, render=None, split="train"):
    row = _row(c, split)
    return scorer.run(inputs=row["inputs"], outputs=_outputs(structured, render=render),
                      expectations=row["expectations"])


def _slide(html) -> dict:
    return {"position": 4, "html": html, "scripts": ""}


# --------------------------------------------------------------------------- the test style is clean

def test_the_test_style_is_one_the_sanitiser_returns_unchanged():
    style = DeckStyle.model_validate(_style())
    cleaned, notes = sanitise_deck_style(style, design_system_active=True)
    assert notes == () and cleaned is style
    # and the two failure rules below do what their tests say
    hexed = DeckStyle.model_validate(_style(STYLE_CSS + HEX_RULE))
    assert sanitise_deck_style(hexed, design_system_active=True) == (hexed, ())
    unscoped = DeckStyle.model_validate(_style(STYLE_CSS + UNSCOPED_RULE))
    assert sanitise_deck_style(unscoped, design_system_active=True)[1]


# --------------------------------------------------------------------------- the fixture (C20, C24)

def test_fixture_is_a_deck_style_the_sanitiser_returns_unchanged():
    raw = _fixture_raw()
    style = DeckStyle.model_validate(raw)
    assert style.model_dump() == raw, "the fixture is a DeckStyle dump, no other keys"
    cleaned, notes = sanitise_deck_style(style, design_system_active=True)
    assert notes == ()
    assert cleaned is style
    assert cleaned.css == raw["css"]


def test_fixture_has_the_technical_pieces():
    raw = _fixture_raw()
    css = raw["css"]
    assert TECHNICAL_PIECES | TOKEN_SPANS <= css_class_names(css)
    assert len(css) <= DECK_STYLE_TARGET_CHARS
    # The token spans are the code block's: every selector naming one is under .dk-code.
    for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True):
        if rule.type != "qualified-rule":
            continue
        for selector in tinycss2.serialize(rule.prelude).split(","):
            names = css_class_names(selector + "{}")
            if names & TOKEN_SPANS:
                assert "dk-code" in names, selector
    components = raw["components"]
    assert 1 <= len(components) <= DECK_STYLE_MAX_COMPONENTS
    assert TECHNICAL_PIECES <= {n for comp in components for n in comp["class_names"]}
    for comp in components:
        assert comp["use"].strip() and comp["name"].strip()
        assert set(comp["class_names"]) <= html_class_names(comp["example_html"]), comp["name"]


def test_fixture_paints_with_meridian_tokens_only():
    css = _fixture_raw()["css"]
    section_css = case.meridian_section_css()
    used = set(re.findall(r"var\(\s*(--[\w-]+)", css))
    assert any(t.startswith("--brand-") for t in used), "the fixture's colours are not Meridian tokens"
    undefined = sorted(t for t in used if not re.search(rf"{re.escape(t)}\s*:", section_css))
    assert not undefined, f"tokens Meridian does not define: {undefined}"
    assert "--db-" not in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\b(rgba?|hsla?)\(", css, re.I)


def test_fixture_passes_the_deck_style_score():
    ok, why = scorers._deck_style_score(_build(_spec(_fixture_raw())), BUILD_EXPECT, design_system_active=True)
    assert ok, why


# --------------------------------------------------------------------------- _deck_style_score

def test_deck_style_score_passes_a_clean_style():
    ok, why = scorers._deck_style_score(_build(_spec(_style())), BUILD_EXPECT, design_system_active=True)
    assert ok, why


def _no_look(look):
    spec = _spec(_style())
    if look is None:
        del spec["slides"][3]["look"]
    else:
        spec["slides"][3]["look"] = look
    return spec


def _components(n):
    return [{"name": f"code {i}", "class_names": ["dk-code"], "use": "A listing.",
             "example_html": '<pre class="dk-code">x</pre>'} for i in range(n)]


_LONG_CSS = STYLE_CSS + "".join(f".dk-pad-{i} {{ margin: 0; }}\n" for i in range(600))

DECK_STYLE_FAILURES = {
    "missing": (lambda: _spec(None), ["deck_style"]),
    "sanitiser_note": (lambda: _spec(_style(STYLE_CSS + UNSCOPED_RULE)), ["sanitis", ".slide"]),
    "no_components": (lambda: _spec(_style(components=[])), ["component"]),
    "thirteen_components": (lambda: _spec(_style(components=_components(13))), ["component"]),
    "over_max_chars": (lambda: _spec(_style(_LONG_CSS)), [str(DECK_STYLE_MAX_CHARS)]),
    "blank_look": (lambda: _no_look("   "), ["look"]),
    "missing_look": (lambda: _no_look(None), ["look"]),
    "raw_hex_with_a_design_system": (lambda: _spec(_style(STYLE_CSS + HEX_RULE)), ["#ff0000"]),
}


@pytest.mark.parametrize("failure", list(DECK_STYLE_FAILURES))
def test_deck_style_score_pass_and_each_failure(failure):
    assert len(_LONG_CSS) > DECK_STYLE_MAX_CHARS
    make, needles = DECK_STYLE_FAILURES[failure]
    ok, why = scorers._deck_style_score(_build(make()), BUILD_EXPECT, design_system_active=True)
    assert not ok, f"{failure} passed: {why}"
    for needle in needles:
        assert needle.lower() in why.lower(), f"{failure}: rationale does not name {needle!r}: {why}"


def test_raw_hex_passes_without_a_design_system():
    ok, why = scorers._deck_style_score(
        _build(_spec(_style(STYLE_CSS + HEX_RULE))), BUILD_EXPECT, design_system_active=False)
    assert ok, why


# --------------------------------------------------------------------------- expected_category_score

def test_expected_category_ands_the_deck_style_after_the_intent_check():
    hexed = _build(_spec(_style(STYLE_CSS + HEX_RULE)))

    ok, why = expected_category_score("architect", _build(_spec(_style())), BUILD_EXPECT, design_system_active=True)
    assert ok, why
    ok, why = expected_category_score("architect", hexed, BUILD_EXPECT, design_system_active=True)
    assert not ok and "#ff0000" in why.lower(), why
    ok, why = expected_category_score("architect", hexed, BUILD_EXPECT, design_system_active=False)
    assert ok, why
    ok, why = expected_category_score("architect", _build(_spec(None)), BUILD_EXPECT, design_system_active=True)
    assert not ok and "deck_style" in why.lower(), why

    # The intent is checked first: a wrong intent fails on the intent, whatever its deck style.
    wrong = {**_build(_spec(None)), "intent": "discuss"}
    ok, why = expected_category_score("architect", wrong, BUILD_EXPECT, design_system_active=True)
    assert not ok and "intent" in why.lower() and "deck_style" not in why.lower(), why


def test_expected_category_without_the_deck_style_key_does_not_check_it():
    for answer in (_build(_spec(None)), _build(_spec(_style(STYLE_CSS + HEX_RULE)))):
        ok, why = expected_category_score("architect", answer, {"intent": "build"}, design_system_active=True)
        assert ok, why


@pytest.mark.parametrize("design_system_active,expected", [(True, "fail"), (False, "pass")])
def test_expected_category_scorer_threads_design_system_active(monkeypatch, design_system_active, expected):
    _patch_judge(monkeypatch)
    c = Case("styled_build", "architect", "positive", design_system_active, "",
             payload={"message": "Build a technical deck", "current_deck_spec": None},
             reference=_build(_spec(_style())), expect=BUILD_EXPECT)
    fb = _run(_scorer("architect", "expected_category"), c, _build(_spec(_style(STYLE_CSS + HEX_RULE))))
    assert fb.value == expected, fb.rationale


# --------------------------------------------------------------------------- deck_style_use_score

def test_deck_style_use_score_passes_a_slide_built_from_the_pieces():
    # Layout-only inline style is allowed; classes come from the template CSS and the deck style.
    ok, why = scorers.deck_style_use_score(GOOD_HTML, _use_payload(), USE_EXPECT)
    assert ok, why


@pytest.mark.parametrize("prop", list(PAINT))
def test_deck_style_use_score_fails_inline_paint(prop):
    ok, why = scorers.deck_style_use_score(_painted(prop, PAINT[prop]), _use_payload(), USE_EXPECT)
    assert not ok, f"inline {prop} passed: {why}"
    assert prop in why.lower(), why


@pytest.mark.parametrize("cls", ["dk-chip", "fancy-box"])
def test_deck_style_use_score_fails_an_undefined_class(cls):
    html = GOOD_HTML.replace("Measured on", f'<span class="{cls}">Measured</span> on')
    ok, why = scorers.deck_style_use_score(html, _use_payload(), USE_EXPECT)
    assert not ok, why
    assert cls in why, why


def test_deck_style_use_score_fails_a_listed_class_not_used():
    html = GOOD_HTML.replace('    <p class="dk-note">Measured on a four-node cluster.</p>\n', "")
    assert "dk-note" not in html
    ok, why = scorers.deck_style_use_score(html, _use_payload(), USE_EXPECT)
    assert not ok, why
    assert "dk-note" in why, why


def test_deck_style_use_score_pass_and_each_failure():
    """The brief's three named failures in one place: an inline background, an undefined class, a
    listed class missing; the clean slide passes."""
    payload = _use_payload()
    assert scorers.deck_style_use_score(GOOD_HTML, payload, USE_EXPECT)[0]
    for html, needle in (
        (_painted("background", "#1e293b"), "background"),
        (GOOD_HTML.replace('class="dk-note"', 'class="dk-note dk-chip"'), "dk-chip"),
        (GOOD_HTML.replace('<pre class="dk-code">', "<pre>"), "dk-code"),
    ):
        ok, why = scorers.deck_style_use_score(html, payload, USE_EXPECT)
        assert not ok and needle in why.lower(), (needle, why)


# --------------------------------------------------------------------------- C21 wiring: the render

@pytest.mark.parametrize("role", ["builder", "fixer"])
@pytest.mark.parametrize("styled", [True, False], ids=["deck-style", "no-deck-style"])
def test_predict_renders_with_the_deck_style_css_after_the_template(monkeypatch, role, styled):
    c = _builder_case(agent_key=role, deck_style=_style() if styled else None)
    monkeypatch.setattr(mlflow_run, "load_case", lambda agent_key, case_id, **kw: c)
    spy = _RenderSpy()
    monkeypatch.setattr(mlflow_run, "render_slide", spy)
    pf = mlflow_run.make_predict_fn(SimpleNamespace(name="cfg"), _FakeRunner(), render_enabled=True)
    out = pf(agent_key=role, case_id=c.case_id, repeat=0)
    assert out["render"] is not None
    want = case.meridian_section_css() + ("\n\n" + STYLE_CSS if styled else "")
    assert [call["section_css"] for call in spy.calls] == [want]


@pytest.mark.parametrize("styled", [True, False], ids=["deck-style", "no-deck-style"])
def test_calibration_render_fn_renders_with_the_deck_style_css_after_the_template(monkeypatch, styled):
    spy = _RenderSpy(RenderMeasures(overflow_px=3.0, min_contrast=8.0, rendered=True))
    monkeypatch.setattr(render_mod, "render_slide", spy)
    monkeypatch.setattr(cli, "render_slide", spy, raising=False)
    c = _builder_case(deck_style=_style() if styled else None)
    out = cli._calibration_render_fn(c, {"html": "<section class='slide'>H-77</section>", "scripts": "draw77()"})
    assert out == spy.measures
    want = case.meridian_section_css() + ("\n\n" + STYLE_CSS if styled else "")
    (call,) = spy.calls
    assert call["html"] == "<section class='slide'>H-77</section>"
    assert call["scripts"] == "draw77()"
    assert call["section_css"] == want


# --------------------------------------------------------------------------- C21 wiring: render_measures

def test_render_measures_scorer_ands_the_deck_style_use(monkeypatch):
    _patch_judge(monkeypatch)
    c = _builder_case(deck_style=_style(), expect=USE_EXPECT)
    monkeypatch.setattr(mlflow_run, "load_case", lambda agent_key, case_id, **kw: c)
    s = _scorer("builder", "render_measures")

    good = _run(s, c, _slide(GOOD_HTML), render=CLEAN)
    assert good.value == "pass", good.rationale
    painted = _run(s, c, _slide(_painted("background", "#1e293b")), render=CLEAN)
    assert painted.value == "fail" and "background" in painted.rationale.lower(), painted.rationale
    unused = _run(s, c, _slide(GOOD_HTML.replace('<pre class="dk-code">', "<pre>")), render=CLEAN)
    assert unused.value == "fail" and "dk-code" in unused.rationale, unused.rationale
    # AND, not OR: a slide that uses the pieces still fails on its render.
    overflowing = _run(s, c, _slide(GOOD_HTML), render=OVERFLOW)
    assert overflowing.value == "fail" and "overflow" in overflowing.rationale.lower(), overflowing.rationale


def test_render_measures_scorer_reads_the_rows_own_case(monkeypatch):
    _patch_judge(monkeypatch)
    plain = _builder_case("plain")
    styled = _builder_case("styled", deck_style=_style(), expect=USE_EXPECT)
    by_id = {c.case_id: c for c in (plain, styled)}
    monkeypatch.setattr(mlflow_run, "load_case", lambda agent_key, case_id, **kw: by_id[case_id])
    s = _scorer("builder", "render_measures")
    html = _painted("color", "#1e293b")
    # A case without deck_style_classes scores exactly as render_measures_score alone.
    fb = _run(s, plain, _slide(html), render=CLEAN)
    assert (fb.value, fb.rationale) == ("pass", scorers.render_measures_score(CLEAN, html)[1])
    assert _run(s, styled, _slide(html), render=CLEAN).value == "fail"


# --------------------------------------------------------------------------- C21 wiring: the judge

@pytest.mark.parametrize("role", ["builder", "build_reviewer"])
def test_judge_brief_carries_the_deck_style_only_when_the_payload_has_one(role):
    spec = {"position": 4, "look": LOOK}
    rd = {"synthesis": "S", "figures": [], "gaps": []}
    base = {"slide_spec": spec, "resolved_data": rd, "html": "H", "section_css": ".slide{}"}
    styled = Case("s", role, "positive", True, "", payload={**base, "deck_style": _style()},
                  reference={}, expect={})
    plain = Case("p", role, "positive", True, "", payload=base, reference={}, expect={})
    result = SimpleNamespace(structured={})
    assert judge_mod.judge_payload(styled, result, None)["brief_or_finding"] == {
        "slide_spec": spec, "resolved_data": rd, "deck_style": _style()}
    assert judge_mod.judge_payload(plain, result, None)["brief_or_finding"] == {
        "slide_spec": spec, "resolved_data": rd}


# --------------------------------------------------------------------------- existing cases unaffected

@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("agent", ["builder", "fixer", "build_reviewer"])
def test_existing_cases_unaffected(monkeypatch, agent, split):
    """Every committed case without the new keys scores as before, through the real scorer that
    loads the real case: the reference (and, for a reviewer, the should_fail) gets the very verdict
    and rationale the old scorer gives it."""
    _patch_judge(monkeypatch)
    cases = [c for c in case.load_cases(agent, split=split) if "deck_style_classes" not in c.expect]
    assert cases
    if agent == "build_reviewer":
        s = _scorer(agent, "expected_category")
        for c in cases:
            cal = judge_mod.load_calibration(agent, c.case_id, **split_kwargs(split))
            for out, should_pass in ((c.reference, True), (cal["should_fail"], False)):
                fb = _run(s, c, out, split=split)
                ok, why = expected_category_score(agent, out, c.expect)
                assert ok is should_pass, (c.case_id, why)
                assert (fb.value, fb.rationale) == ("pass" if ok else "fail", why), c.case_id
        return
    s = _scorer(agent, "render_measures")
    for c in cases:
        for measures in (CLEAN, OVERFLOW):
            fb = _run(s, c, c.reference, render=measures, split=split)
            ok, why = scorers.render_measures_score(measures, c.reference["html"])
            assert (fb.value, fb.rationale) == ("pass" if ok else "fail", why), (c.case_id, fb.rationale)


# --------------------------------------------------------------------------- the new cases (C23)

@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("agent,cid", NEW_CASES)
def test_new_case_references_pass_and_calibrations_fail(monkeypatch, agent, cid, split):
    _patch_judge(monkeypatch)
    c = case.load_case(agent, cid, **split_kwargs(split))
    cal = judge_mod.load_calibration(agent, cid, **split_kwargs(split))
    assert cal is not None and set(cal) == {"should_fail"}
    bad = cal["should_fail"]
    assert "deck_style" in c.payload

    if agent == "builder":
        assert c.expect.get("deck_style_classes")
        ok, why = scorers.deck_style_use_score(c.reference["html"], c.payload, c.expect)
        assert ok, why
        ok, why = scorers.deck_style_use_score(bad["html"], c.payload, c.expect)
        assert not ok, f"should_fail passes deck_style_use_score: {why}"
        # The same verdicts through the harness's own scorer, which loads this case.
        s = _scorer(agent, "render_measures")
        assert _run(s, c, c.reference, render=CLEAN, split=split).value == "pass"
        assert _run(s, c, bad, render=CLEAN, split=split).value == "fail"
    else:
        ok, why = expected_category_score(agent, c.reference, c.expect)
        assert ok, why
        ok, why = expected_category_score(agent, bad, c.expect)
        assert not ok, f"should_fail passes expected_category: {why}"
        s = _scorer(agent, "expected_category")
        assert _run(s, c, c.reference, split=split).value == "pass"
        assert _run(s, c, bad, split=split).value == "fail"

    # The judge sees the deck style the role was given.
    brief = judge_mod.judge_payload(c, SimpleNamespace(structured=c.reference), None)["brief_or_finding"]
    assert brief["deck_style"] == c.payload["deck_style"]


@pytest.mark.parametrize("split", SPLITS)
def test_reviewer_cases_differ_by_inline_paint_of_the_code_block(split):
    """deck_style_clean is built from the pieces; deck_style_inline_paint paints the code block
    inline instead of using dk-code (judged with the builder's own use rule)."""
    def load(cid):
        return case.load_case("build_reviewer", cid, **split_kwargs(split))

    clean, painted = load("deck_style_clean"), load("deck_style_inline_paint")
    use = {"deck_style_classes": ["dk-code"]}
    ok, why = scorers.deck_style_use_score(clean.payload["html"], clean.payload, use)
    assert ok, why
    ok, why = scorers.deck_style_use_score(painted.payload["html"], painted.payload, use)
    assert not ok, why
    # With no class required, what is left to fail the painted slide is its inline paint.
    ok, why = scorers.deck_style_use_score(painted.payload["html"], painted.payload, {"deck_style_classes": []})
    assert not ok and any(p in why.lower() for p in PAINT), f"the inline paint is not what fails: {why}"
