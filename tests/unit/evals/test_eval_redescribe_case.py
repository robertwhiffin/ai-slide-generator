"""The arc-review sweeper's re-description: the ``redescribe_deck`` case on both splits, and the
scorer rule it is routed to. Offline: no model, no network.

``spec_sync.run_arc_review`` invokes the graph with ``{"architect_message": ARC_REVIEW_MESSAGE}``
and ``describe_only=True``. On that turn ``architect_node`` applies no operations: it ignores
``operations``/``deck_changes``, persists the answer's ``deck_spec`` (``_plan_answer``) and keeps
the persisted spec whole instead when the answer's slide positions differ from it
(``_description_keeps_what_it_cannot_see``). An answer with no ``deck_spec`` is refused and a
describe-only turn is never retried, so an operations-shaped re-description is silently dropped
while the sweeper clears its marker.

Names this file fixes:

* ``scorers._redescription_score(output, expect, current) -> (bool, str)``; every rationale starts
  ``Re-description:``.
* ``expect.full_deck_spec: true`` routes an architect row to it, ahead of the intent check and the
  operations routing (``expected_category_score``). No other case carries the key.
* Intent: ``edit`` (what the case expects and the prompt asks for) and ``build`` both pass. On a
  describe-only turn the node handles the two alike: both persist the answer's ``deck_spec``
  through ``_description_keeps_what_it_cannot_see`` and the same deck-level write, and
  ``architect_router`` ends both turns before the foreman, so neither builds a slide.
* The judge sees this case's answers as given: an operations answer is NOT composed for it, because
  production composes nothing on a describe-only turn (``judge._judged``).
"""
import copy
import types

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case, judge, scorers
from evals.harness.case import Case
from evals.harness.scorers import expected_category_score
from src.domain.deck_spec import DeckSpec, SlideSpec
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_numbering import architect_slide_payload, slide_numbering
from src.domain.slide_operations import DeckChanges, SlideContent
from src.services.spec_sync import ARC_REVIEW_MESSAGE

AGENT = "architect"
CID = "redescribe_deck"
SPLITS = ("train", "heldout")
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
EXPECT = {"intent": "edit", "full_deck_spec": True}
DECK_SLIDES = {"train": 10, "heldout": 6}
# The payload keys a describe-only turn shares with an ordinary edit turn on the same deck.
SHARED_KEYS = (
    "current_deck_spec", "committed_slide_count", "previous_deck_review",
    "available_design_contract", "template_sections", "resolved_style", "design_system_library",
)


# --------------------------------------------------------------------------- helpers

def _case(split: str) -> Case:
    return case.load_case(AGENT, CID, **case.split_kwargs(split))


def _should_fail(split: str) -> dict:
    return judge.load_calibration(AGENT, CID, **case.split_kwargs(split))["should_fail"]


def _deck(c: Case) -> dict:
    return c.payload["current_deck_spec"]


def _positions(deck: dict) -> list[int]:
    return sorted(s["position"] for s in deck["slides"])


def _content(slide: dict) -> dict:
    return SlideContent.from_slide_spec(SlideSpec.model_validate(slide)).model_dump(mode="json")


def _answer(intent="edit", *, deck_spec=None, targets=(), operations=None, deck_changes=None,
            message="I've re-described the deck as it stands.") -> dict:
    """An architect answer in the runner's form (``ArchitectOutput.model_dump``)."""
    return ArchitectOutput.model_validate({
        "intent": intent, "message": message, "deck_spec": deck_spec, "data_request": None,
        "target_positions": list(targets), "proposed_design_contract": None,
        "operations": operations, "deck_changes": deck_changes,
    }).model_dump(mode="json")


def _full(current: dict, intent="edit", **kw) -> dict:
    """The right answer's shape: the whole current deck as deck_spec, every position targeted."""
    targets = _positions(current) if intent == "edit" else ()
    return _answer(intent, deck_spec=copy.deepcopy(current), targets=targets, **kw)


def _arc(current: dict) -> list[str]:
    return [f"Re-described: {beat}" for beat in current["narrative_arc"]]


def _both(answer: dict, c: Case) -> list[tuple[str, tuple[bool, str]]]:
    """The answer scored directly and through the harness's role dispatch (with the case inputs)."""
    current = _deck(c)
    return [
        ("_redescription_score", scorers._redescription_score(answer, c.expect, current)),
        ("expected_category_score", expected_category_score(
            AGENT, answer, c.expect, reference=c.reference, current_deck_spec=current)),
    ]


# --------------------------------------------------------------------------- 1. the case

@pytest.mark.parametrize("split", SPLITS)
def test_case_exists_with_the_four_files(split):
    d = case.cases_dir(AGENT, split=split) / CID
    assert d.is_dir(), f"missing case directory {d}"
    assert sorted(p.name for p in d.iterdir()) == sorted(FILES)
    assert CID in {c.case_id for c in case.load_cases(AGENT, **case.split_kwargs(split))}


@pytest.mark.parametrize("split", SPLITS)
def test_case_contract(split):
    c = _case(split)
    assert c.expect == EXPECT
    assert c.kind == "mutation" and c.fault.strip() and c.design_system_active is True
    assert "describe-only" in c.fault and "deck_changes" in c.fault, c.fault


@pytest.mark.parametrize("split", SPLITS)
def test_payload_is_the_sweepers_describe_only_payload(split):
    """What architect_node sends on ``run_arc_review``'s turn: ARC_REVIEW_MESSAGE as ``message``,
    no user row for it in ``conversation`` (the sweeper persists none), and no slide references
    (``architect_slide_payload(..., describe_only=True)``); everything else as on the same deck."""
    p = _case(split).payload
    edit = case.load_case(AGENT, "edit_request", **case.split_kwargs(split)).payload
    assert list(p) == list(edit), "the payload keys, in architect_node's order"
    assert p["message"] == ARC_REVIEW_MESSAGE
    assert p["current_deck_spec"] == case.gold_deck_spec(split)
    for key in SHARED_KEYS:
        assert p[key] == edit[key], key
    # The conversation is the prior exchange alone: the sweeper's message is never a user turn.
    assert p["conversation"] == edit["conversation"][:2]
    assert [t["role"] for t in p["conversation"]] == ["user", "assistant"]
    assert all(t["content"] != ARC_REVIEW_MESSAGE for t in p["conversation"])
    positions = _positions(p["current_deck_spec"])
    assert len(positions) == DECK_SLIDES[split] == p["committed_slide_count"]
    assert p["slide_references"] == []
    assert p["slide_numbering"] == slide_numbering(positions)
    assert {k: p[k] for k in ("slide_numbering", "slide_references")} == architect_slide_payload(
        p["conversation"], p["message"], positions, describe_only=True)


@pytest.mark.parametrize("split", SPLITS)
def test_reference_is_the_deck_re_described_as_it_stands(split):
    c = _case(split)
    ref = c.reference
    out = ArchitectOutput.model_validate(ref)
    assert out.intent == "edit" and out.message.strip()
    assert out.operations is None and out.deck_changes is None
    assert ref["operations"] is None and ref["deck_changes"] is None
    assert ref["deck_spec"] == _deck(c), "the current spec, re-described as it stands"
    assert ref["target_positions"] == _positions(_deck(c)), "every position, as the prompt asks"
    for via, (ok, why) in _both(ref, c):
        assert ok, f"{split} reference fails via {via}: {why}"
        assert why.startswith("Re-description:"), why


@pytest.mark.parametrize("split", SPLITS)
def test_should_fail_is_the_silent_drop_shape(split):
    """An edit re-describing the arc as ``deck_changes`` with no deck_spec: production drops it."""
    c = _case(split)
    bad = _should_fail(split)
    out = ArchitectOutput.model_validate(bad)
    assert bad != c.reference
    assert out.intent == "edit" and out.deck_spec is None and out.operations is None
    assert out.deck_changes is not None
    assert bad["deck_changes"] == DeckChanges.model_validate(bad["deck_changes"]).model_dump(
        mode="json"), "deck_changes in the runner's dump form"
    arc = out.deck_changes.narrative_arc
    assert arc and arc != _deck(c)["narrative_arc"], "it re-describes the narrative arc"
    assert len(arc) == len(_deck(c)["narrative_arc"])
    assert {k for k, v in bad["deck_changes"].items() if v is not None} == {"narrative_arc"}
    for via, (ok, why) in _both(bad, c):
        assert not ok, f"{split} should_fail passes via {via}: {why}"
        assert why.startswith("Re-description:"), why
        assert "deck_spec" in why and "deck_changes" in why, why


# --------------------------------------------------------------------------- 2. the scorer rule

@pytest.mark.parametrize("split", SPLITS)
def test_a_full_deck_spec_edit_passes(split):
    c = _case(split)
    current = _deck(c)
    for name, answer in (
        ("the deck as it stands", _full(current)),
        ("a re-described arc inside the full spec",
         _answer(deck_spec={**copy.deepcopy(current), "narrative_arc": _arc(current)},
                 targets=_positions(current))),
        ("targets naming one slide", _answer(deck_spec=copy.deepcopy(current), targets=[0])),
    ):
        for via, (ok, why) in _both(answer, c):
            assert ok, f"{split} {name} fails via {via}: {why}"
            assert why.startswith("Re-description:"), why


@pytest.mark.parametrize("split", SPLITS)
def test_a_full_deck_spec_build_also_passes(split):
    """The intent decision: a describe-only build persists its deck_spec exactly as an edit does."""
    c = _case(split)
    for via, (ok, why) in _both(_full(_deck(c), intent="build"), c):
        assert ok, f"{split} build fails via {via}: {why}"
        assert "build" in why, why


def _missing_one(current: dict) -> dict:
    deck = copy.deepcopy(current)
    gone = _positions(current)[len(current["slides"]) // 2]
    deck["slides"] = [s for s in deck["slides"] if s["position"] != gone]
    return deck


def _extra_one(current: dict) -> dict:
    deck = copy.deepcopy(current)
    last = deck["slides"][-1]
    deck["slides"].append({**copy.deepcopy(last), "position": last["position"] + 1})
    return deck


def _failing_answers(current: dict) -> dict[str, tuple[dict, tuple[str, ...]]]:
    """Each wrong answer, and the words its rationale must carry (case-insensitive)."""
    positions = _positions(current)
    gone = _positions(current)[len(current["slides"]) // 2]
    first = current["slides"][0]
    update = [{"op": "update", "position": first["position"], "slides": [_content(first)]}]
    arc = DeckChanges(narrative_arc=_arc(current)).model_dump(mode="json")
    return {
        "operations-only": (
            _answer(operations=update), ("no deck_spec", "operations")),
        "deck_changes-only": (
            _answer(deck_changes=arc), ("no deck_spec", "deck_changes")),
        "deck_spec missing a slide": (
            _answer(deck_spec=_missing_one(current), targets=positions[:-1]),
            ("positions", f"missing [{gone}]")),
        "deck_spec with an extra slide": (
            _answer(deck_spec=_extra_one(current), targets=positions),
            ("positions", f"added [{positions[-1] + 1}]")),
        "operations with the deck_spec": (
            _full(current, operations=update), ("operations",)),
        "deck_changes with the deck_spec": (
            _full(current, deck_changes=arc), ("deck_changes",)),
        "discuss": (
            _answer("discuss", message="The deck still reads as described."), ("intent",)),
        "confirm_design_contract": (
            ArchitectOutput.model_validate({
                "intent": "confirm_design_contract", "message": "Switch to Acme?",
                "proposed_design_contract": {"design_system_id": 4, "template_id": 7},
            }).model_dump(mode="json"), ("intent",)),
    }


@pytest.mark.parametrize("name", list(_failing_answers(case.gold_deck_spec("train"))))
@pytest.mark.parametrize("split", SPLITS)
def test_a_wrong_re_description_fails_and_says_why(split, name):
    c = _case(split)
    answer, needles = _failing_answers(_deck(c))[name]
    for via, (ok, why) in _both(answer, c):
        assert not ok, f"{split} {name} passes via {via}: {why}"
        assert why.startswith("Re-description:"), f"{name} via {via} not routed here: {why}"
        for needle in needles:
            assert needle.lower() in why.lower(), f"{name} via {via}: {needle!r} not in {why!r}"


def test_a_missing_or_invalid_current_deck_fails_explicitly():
    c = _case("train")
    answer = _full(_deck(c))
    ok, why = scorers._redescription_score(answer, c.expect, None)
    assert not ok and why.startswith("Re-description:") and "current_deck_spec" in why, why
    ok, why = expected_category_score(AGENT, answer, c.expect, reference=c.reference)
    assert not ok and "current_deck_spec" in why, why
    broken = {**_deck(c), "slides": "not a list"}
    ok, why = scorers._redescription_score(answer, c.expect, broken)
    assert not ok and "current_deck_spec" in why and "valid DeckSpec" in why, why


def test_an_invalid_deck_spec_fails_explicitly():
    c = _case("train")
    answer = {**_full(_deck(c)), "deck_spec": {"title": "no slides"}}
    ok, why = scorers._redescription_score(answer, c.expect, _deck(c))
    assert not ok and why.startswith("Re-description:") and "valid DeckSpec" in why, why


def test_only_full_deck_spec_routes_to_the_rule():
    """Without the key, the same answers score exactly as before: an operations answer on the
    operations path and a deck_spec edit by its target positions."""
    c = _case("train")
    current = _deck(c)
    plain = {"intent": "edit"}
    first = current["slides"][0]
    update = [{"op": "update", "position": first["position"], "slides": [_content(first)]}]
    ok, why = expected_category_score(
        AGENT, _answer(operations=update), plain, reference=c.reference, current_deck_spec=current)
    assert why.startswith("Operations:"), why
    ok, why = expected_category_score(
        AGENT, _full(current, intent="build"), plain, reference=c.reference,
        current_deck_spec=current)
    assert (ok, why) == (False, "Intent mismatch: got 'build', expected 'edit'")
    falsy = {**c.expect, "full_deck_spec": False}
    ok, why = expected_category_score(
        AGENT, _full(current), falsy, reference=c.reference, current_deck_spec=current)
    assert not why.startswith("Re-description:"), why


# --------------------------------------------------------------------------- 3. the judge's view

@pytest.mark.parametrize("split", SPLITS)
def test_the_judge_sees_this_cases_answers_as_given(split):
    """No composition on this case: production composes no operations on a describe-only turn,
    so the judge must not be shown a composed full deck_spec for a deck_changes-only answer."""
    c = _case(split)
    bad = _should_fail(split)
    seen = judge.judge_payload(c, types.SimpleNamespace(structured=bad), None)
    assert seen["candidate"] == bad
    assert seen["candidate"]["deck_spec"] is None
    assert seen["reference"] == c.reference
    assert seen["brief_or_finding"] == {
        "message": ARC_REVIEW_MESSAGE, "current_deck_spec": _deck(c)}
    ok_answer = _full(_deck(c))
    assert judge.judge_payload(c, types.SimpleNamespace(structured=ok_answer), None)[
        "candidate"] == ok_answer


def test_the_judge_still_composes_an_operations_answer_on_other_cases():
    """The guard is keyed on this case's expect only: an ordinary edit case still composes (C2)."""
    c = case.load_case(AGENT, "edit_request")
    arc = DeckChanges(narrative_arc=_arc(_deck(c))).model_dump(mode="json")
    seen = judge.judge_payload(c, types.SimpleNamespace(structured=_answer(deck_changes=arc)), None)
    assert seen["candidate"]["deck_spec"] is not None
    assert DeckSpec.model_validate(seen["candidate"]["deck_spec"]).narrative_arc == _arc(_deck(c))
