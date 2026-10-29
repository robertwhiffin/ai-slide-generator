"""Task 6 (architect edit operations, spec §9): the eval harness scores an operations answer with
production's own semantics, and the judge sees its composed form. Offline: no model, no network.

Names this file fixes for the implementer (the brief's Interfaces, verbatim where it gives them):

* ``scorers._operations_score(output, expect, current, reference) -> (bool, str)``. ``output`` is
  the architect's structured answer; ``expect`` the case.yaml ``expect``; ``current`` the payload's
  ``current_deck_spec`` dict; ``reference`` the case's reference OUTPUT, which may be
  deck_spec-shaped (every existing case) or operations-shaped (the four new cases). Deck-level
  fields are compared with the reference's COMPOSED deck.
* ``scorers.compose_operations_answer(output: dict, current_deck_spec: dict | None) -> dict``:
  the ONE normalisation both judge paths call (C2), for the candidate AND the reference. An edit
  carrying ``operations``/``deck_changes`` gets ``deck_spec`` = the JSON dump of
  ``compose_edit_spec(...)`` and ``target_positions`` = ``list(rebuild)``; any other answer comes
  back unchanged.
* ``expected_category_score("architect", ...)`` routes an ``edit`` answer whose ``operations`` or
  ``deck_changes`` is not None to ``_operations_score`` on EVERY edit case, with or without
  ``expect.inserted``. Every other answer scores exactly as today (explicit ``None`` keys
  included, which is what the runner's ``model_dump`` produces). The alignment path must still
  read an operations-shaped reference: ``replace_slide_expand``'s should_fail is a full spec, its
  reference is operations, and the row must fail for production's reason (``ambiguous``).
* ``expect.layout`` (optional): ``[int | None, ...]``, persisted positions, ``None`` = a new slide.
* Rationale needles, matched case-insensitively: ``rebuild``, ``layout``, ``inserted``, the
  problem's own code (``unknown_slide``, ``nothing_to_do``, ``invalid_deck_changes`` ...),
  ``untouched``, the deck-level field's name (``design_contract`` for the contract), ``intent``,
  and ``reference`` / ``current`` for a missing input.
* The four new case ids on both splits: ``delete_slide``, ``move_slide``,
  ``replace_slide_expand``, ``mixed_operations``.
"""
import copy
import dataclasses
import json
import re
import sys

import pytest
from mlflow.entities import Feedback

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case, mlflow_run, scorers
from evals.harness import judge as judge_mod
from evals.harness.case import Case
from evals.harness.scorers import expected_category_score
from src.domain import slide_operations
from src.domain.deck_spec import DeckSpec, SlideSpec
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_alignment import AlignmentRefused, align_slides
from src.domain.slide_numbering import architect_slide_payload
from src.domain.slide_operations import (
    OperationsResult,
    SlideContent,
    apply_operations,
    compose_edit_spec,
)
from src.services.template_sections import complete_index_only_bindings, invalid_slide_bindings

AGENT = "architect"
SPLITS = ("train", "heldout")
NEW_CASE_IDS = ("delete_slide", "move_slide", "replace_slide_expand", "mixed_operations")
# The sweeper's re-description: an edit case whose right answer is a full deck_spec and whose
# operations answer must FAIL (tests/unit/evals/test_eval_redescribe_case.py), so it has no
# operations equivalent here.
REDESCRIBE_CASE_IDS = ("redescribe_deck",)
FILES =("case.yaml", "payload.json", "reference.json", "calibration.json")
FIVE_DECK_LEVEL_FIELDS = ("audience", "purpose", "argument", "call_to_action", "narrative_arc")


# --------------------------------------------------------------------------- helpers

def _case(cid: str, split: str = "train") -> Case:
    return case.load_case(AGENT, cid, **case.split_kwargs(split))


def _should_fail(cid: str, split: str = "train") -> dict:
    path = case.cases_dir(AGENT, split=split) / cid / "calibration.json"
    return json.loads(path.read_text())["should_fail"]


def _deck(c: Case) -> dict:
    return c.payload["current_deck_spec"]


def _slides(deck: dict) -> list[dict]:
    """A deck dict's slides in position order (indexable by position on a 0..n-1 deck)."""
    return sorted(deck["slides"], key=lambda s: s["position"])


def _content(slide: dict) -> dict:
    """The ``SlideContent`` of a spec slide dict: every field but ``position``."""
    return SlideContent.from_slide_spec(SlideSpec.model_validate(slide)).model_dump(mode="json")


def _ins(after: int, *slides: dict) -> dict:
    return {"op": "insert", "after_position": after, "slides": [_content(s) for s in slides]}


def _upd(position: int, slide: dict) -> dict:
    return {"op": "update", "position": position, "slides": [_content(slide)]}


def _del(position: int) -> dict:
    return {"op": "delete", "position": position}


def _mov(position: int, after: int) -> dict:
    return {"op": "move", "position": position, "after_position": after}


def _answer(operations, *, deck_changes=None, intent="edit", message="I'll make that edit.",
            targets=(), deck_spec=None) -> dict:
    """An architect answer in the runner's form (``ArchitectOutput.model_dump``)."""
    out = {
        "intent": intent, "message": message, "deck_spec": deck_spec, "data_request": None,
        "target_positions": list(targets), "proposed_design_contract": None,
        "operations": operations, "deck_changes": deck_changes,
    }
    return ArchitectOutput.model_validate(out).model_dump(mode="json")


def _composed(answer: dict, current: dict) -> tuple[DeckSpec, OperationsResult]:
    """What production composes from ``answer`` over ``current`` (fails loudly if it refuses)."""
    out = ArchitectOutput.model_validate(answer)
    prior = DeckSpec.model_validate(current)
    result = apply_operations(prior.slides, out.operations or [])
    assert isinstance(result, OperationsResult), result
    spec = compose_edit_spec(prior, result, out.deck_changes)
    assert isinstance(spec, DeckSpec), spec
    return spec, result


def _both(answer, expect, current, reference) -> list[tuple[str, tuple[bool, str]]]:
    """The answer scored directly and through the harness's role dispatch."""
    return [
        ("_operations_score", scorers._operations_score(answer, expect, current, reference)),
        ("expected_category_score", expected_category_score(
            AGENT, answer, expect, reference=reference, current_deck_spec=current)),
    ]


def _patch_everywhere(monkeypatch, real, replacement) -> None:
    """Rebind every module-level name that holds ``real`` in the harness (or the domain module).

    Robust to how the implementation imports it: ``from ... import f`` (under any alias) in any
    ``evals.*`` module, a module-attribute lookup, or a call-time import from
    ``src.domain.slide_operations``.
    """
    for module in list(sys.modules.values()):
        mod_name = getattr(module, "__name__", "") or ""
        if not (mod_name.startswith("evals") or mod_name == "src.domain.slide_operations"):
            continue
        for attr, value in list(vars(module).items()):
            if value is real:
                monkeypatch.setattr(module, attr, replacement)


# The base case for the failure modes: "Add a slide after slide 8 on offline use and security,
# and add it to the summary on the last slide" on the 10-slide train deck.
BASE = "add_slide_and_revise"
BASE_LAYOUT = [0, 1, 2, 3, 4, 5, 6, 7, None, 8, 9]


def _base():
    c = _case(BASE)
    current = _deck(c)
    ref_slides = _slides(c.reference["deck_spec"])
    new, revised_last = ref_slides[8], ref_slides[10]
    ops = [_ins(7, new), _upd(9, revised_last)]
    return c, current, ops, new, revised_last


def _drifting_apply_operations(real):
    """``apply_operations`` with one slide it did NOT rebuild silently rewritten."""

    def drifting(current, operations):
        result = real(current, operations)
        if not isinstance(result, OperationsResult):
            return result
        keep = next(i for i in range(len(result.slides)) if i not in result.rebuild)
        slides = list(result.slides)
        slides[keep] = slides[keep].model_copy(
            update={"hands_off": slides[keep].hands_off + " (drifted)"})
        return dataclasses.replace(result, slides=tuple(slides))

    return drifting


def _changed(value):
    if isinstance(value, list):
        return [*value, "A new beat nobody asked for"]
    return f"{value} (rewritten)"


ACME = {"design_system_id": 4, "template_id": 7}  # the pack library's second design system


# name -> (passes, needles: any one must appear in the rationale; None = no needle)
SCENARIOS = {
    "pass": (True, None),
    "pass-with-expect-layout": (True, None),
    "pass-model-targets-in-old-numbering-are-ignored": (True, None),
    "pass-reference-given-as-operations": (True, None),
    "pass-matching-operations-reference-deck-changes": (True, None),
    "pass-title-change-is-not-deck-level": (True, None),
    "pass-a-stale-deck-spec-beside-operations-is-ignored": (True, None),
    "wrong-rebuild-revision-forgotten": (False, ("rebuild",)),
    "wrong-rebuild-an-extra-slide-rebuilt": (False, ("rebuild",)),
    "wrong-rebuild-deck-changes-only": (False, ("rebuild",)),
    "wrong-layout-an-unrequested-move": (False, ("layout",)),
    "wrong-layout-inserted-one-place-late": (False, ("rebuild", "inserted")),
    "wrong-layout-insert-beside-the-blank-instead-of-fill": (False, ("inserted",)),
    "problem-unknown_slide": (False, ("unknown_slide",)),
    "problem-slide_targeted_twice": (False, ("slide_targeted_twice",)),
    "problem-missing_slides": (False, ("missing_slides",)),
    "problem-nothing_to_do": (False, ("nothing_to_do",)),
    "problem-invalid-composed-spec": (False, ("invalid_deck_changes",)),
    "changed-untouched-slide": (False, ("untouched",)),
    **{f"deck-level-drift-{f}": (False, (f,)) for f in FIVE_DECK_LEVEL_FIELDS},
    "deck-level-drift-design_contract": (False, ("design_contract",)),
    "deck-level-drift-against-an-operations-reference": (False, ("narrative_arc",)),
    "not-an-edit": (False, ("intent",)),
    "missing-reference": (False, ("reference",)),
    "missing-current-deck": (False, ("current",)),
    "malformed-operations-fail-not-crash": (False, None),
}


def _scenario(name: str, monkeypatch):
    """(answer, expect, current, reference) for ``name``; may patch the domain for one scenario."""
    c, current, ops, new, revised_last = _base()
    expect, reference = dict(c.expect), c.reference
    answer = _answer(ops)

    if name == "pass":
        pass
    elif name == "pass-with-expect-layout":
        expect = {**expect, "layout": BASE_LAYOUT}
    elif name == "pass-model-targets-in-old-numbering-are-ignored":
        answer = _answer(ops, targets=[8, 9])  # production ignores the model's targets here
    elif name == "pass-reference-given-as-operations":
        reference = _answer(ops)
    elif name == "pass-matching-operations-reference-deck-changes":
        changes = {"narrative_arc": _changed(current["narrative_arc"])}
        reference = _answer(ops, deck_changes=changes)
        answer = _answer(ops, deck_changes=changes)
    elif name == "pass-title-change-is-not-deck-level":
        answer = _answer(ops, deck_changes={"title": "A renamed deck"})
    elif name == "pass-a-stale-deck-spec-beside-operations-is-ignored":
        answer = _answer(ops, deck_spec=current)  # the operations path ignores deck_spec
    elif name == "wrong-rebuild-revision-forgotten":
        answer = _answer([_ins(7, new)])
    elif name == "wrong-rebuild-an-extra-slide-rebuilt":
        answer = _answer([*ops, _upd(0, _slides(current)[0])])
    elif name == "wrong-rebuild-deck-changes-only":
        # A case with no ``inserted``: today's path would say "Target positions mismatch".
        c = _case("edit_request")
        current, expect, reference = _deck(c), dict(c.expect), c.reference
        answer = _answer(None, deck_changes={"title": "A renamed deck"})
    elif name == "wrong-layout-an-unrequested-move":
        expect = {**expect, "layout": BASE_LAYOUT}
        answer = _answer([*ops, _mov(0, 1)])  # same rebuild, same new slide, slides 1/2 swapped
    elif name == "wrong-layout-inserted-one-place-late":
        answer = _answer([_ins(8, new), _upd(9, revised_last)])
    elif name == "wrong-layout-insert-beside-the-blank-instead-of-fill":
        c = _case("fill_blank_slide")
        current, expect, reference = _deck(c), dict(c.expect), c.reference
        filled = _slides(c.reference["deck_spec"])[5]
        answer = _answer([_ins(4, filled)])  # rebuild [5] matches; the blank is left beside it
    elif name == "problem-unknown_slide":
        answer = _answer([_ins(7, new), _upd(10, revised_last)])  # the 1-based slip: no slide 10
    elif name == "problem-slide_targeted_twice":
        answer = _answer([*ops, _del(9)])
    elif name == "problem-missing_slides":
        answer = _answer([{"op": "insert", "after_position": 7}, _upd(9, revised_last)])
    elif name == "problem-nothing_to_do":
        answer = _answer([])
    elif name == "problem-invalid-composed-spec":
        answer = _answer(ops, deck_changes={"title": "   "})  # DeckSpec H1: title non-empty
    elif name == "changed-untouched-slide":
        real = slide_operations.apply_operations
        _patch_everywhere(monkeypatch, real, _drifting_apply_operations(real))
    elif name.startswith("deck-level-drift-") and name.removeprefix("deck-level-drift-") in (
            FIVE_DECK_LEVEL_FIELDS):
        field = name.removeprefix("deck-level-drift-")
        answer = _answer(ops, deck_changes={field: _changed(current[field])})
    elif name == "deck-level-drift-design_contract":
        answer = _answer(ops, deck_changes={"design_contract": ACME})
    elif name == "deck-level-drift-against-an-operations-reference":
        reference = _answer(ops, deck_changes={"narrative_arc": _changed(current["narrative_arc"])})
    elif name == "not-an-edit":
        answer = _answer(ops, intent="discuss")
    elif name == "missing-reference":
        reference = None
    elif name == "missing-current-deck":
        current = None
    elif name == "malformed-operations-fail-not-crash":
        answer = {**_answer(ops), "operations": [{"op": "explode", "position": 1}]}
    else:  # pragma: no cover - a typo in SCENARIOS
        raise AssertionError(name)
    return answer, expect, current, reference


# ------------------------------------------------------------------ 1. production semantics

@pytest.mark.parametrize("name", list(SCENARIOS))
def test_operations_answer_scored_by_production_semantics(name, monkeypatch):
    """An operations answer passes only on production's own reading of it.

    Built on the real ``add_slide_and_revise`` train payload (and ``fill_blank_slide`` /
    ``edit_request`` where a scenario needs their expectation). Scored directly by
    ``_operations_score`` and through ``expected_category_score``; both must agree, and every
    failure names its cause.
    """
    passes, needles = SCENARIOS[name]
    answer, expect, current, reference = _scenario(name, monkeypatch)
    for via, (ok, why) in _both(answer, expect, current, reference):
        assert isinstance(ok, bool) and isinstance(why, str) and why.strip(), (via, ok, why)
        want = "pass" if passes else "fail"
        assert ok is passes, f"{name} via {via}: expected {want}, got {why!r}"
        if needles:
            assert any(n.lower() in why.lower() for n in needles), (
                f"{name} via {via}: the rationale must name the cause "
                f"({' or '.join(needles)}): {why!r}")


def test_operations_answer_scored_with_three_positional_args_fails_not_crashes():
    """The old three-argument call has no current deck to compose against, so it fails."""
    _, _, ops, _, _ = _base()
    ok, why = expected_category_score(AGENT, _answer(ops), dict(_case(BASE).expect))
    assert ok is False and why.strip(), why


# --------------------------------------------------------------------------- 2. existing cases

def _u(position, ref_index):
    return ("update", position, [ref_index])


def _i(after, *ref_indices):
    return ("insert", after, list(ref_indices))


# For every existing architect edit case: the operations equivalent of its reference, derived by
# hand from the reference vs the payload's current deck. Positions are the CURRENT deck's; each
# entry's slide content is the reference deck_spec's slide at the given (revised-deck) index.
EXISTING_EDIT_OPERATIONS = {
    "train": {
        "edit_request": [_u(1, 1)],                     # slide 2's bullets -> stat cards
        "edit_polite_ordinal": [_u(1, 1)],              # the second slide, less wordy
        "edit_last_slide": [_u(9, 9)],                  # the last of ten (purpose too)
        "edit_multi_slide": [_u(3, 3), _u(4, 4), _u(5, 5)],  # slides 4-6
        "add_slide_anchor": [_i(2, 3)],                 # after slide 3
        "add_slide_end": [_i(9, 10)],                   # after the last of ten
        "add_slide_as_number": [_i(0, 1)],              # a new slide 2
        "add_slide_and_revise": [_i(7, 8), _u(9, 10)],  # after slide 8 + the summary, now 11
        "fill_blank_slide": [_u(5, 5)],                 # the blank slide 6, filled in place
        "edit_beside_blank": [_u(6, 6)],                # slide 7, beside the blank
    },
    "heldout": {
        "edit_request": [_u(2, 2)],                     # slide 3 as four cards
        "edit_polite_ordinal": [_u(3, 3)],              # the 4th slide
        "edit_last_slide": [_u(5, 5)],                  # the final of six
        "edit_multi_slide": [_u(1, 1), _u(2, 2)],       # slides 2 and 3
        "add_slide_anchor": [_i(3, 4)],                 # before slide 5
        "add_slide_end": [_i(5, 6)],                    # after the last of six
        "add_slide_as_number": [_i(2, 3)],              # a new fourth slide
        "add_slide_and_revise": [_i(2, 3), _u(5, 6)],   # after slide 3 + the checklist, now 7
        "fill_blank_slide": [_u(3, 3)],                 # the blank slide 4, filled in place
        "edit_beside_blank": [_u(4, 4)],                # the fifth slide, beside the blank
    },
}


def _equivalent(entries, ref_slides) -> list[dict]:
    ops = []
    for kind, anchor, indices in entries:
        contents = [_content(ref_slides[i]) for i in indices]
        key = "position" if kind == "update" else "after_position"
        ops.append({"op": kind, key: anchor, "slides": contents})
    return ops


def _edit_case_ids(split: str) -> set[str]:
    return {c.case_id for c in case.load_cases(AGENT, **case.split_kwargs(split))
            if c.expect.get("intent") == "edit"}


@pytest.mark.parametrize("split", SPLITS)
def test_existing_insert_cases_pass_with_operations_answers(split):
    """Every existing edit case, answered in operations form, passes with its own ``expect``.

    The cases are discovered from disk: a new edit case missing from the table fails here
    rather than silently going unscored. ``target_positions`` is left empty on purpose (an
    operations edit needs none), so ``edit_*`` cases without ``inserted`` must be routed to the
    operations scorer too.
    """
    discovered = _edit_case_ids(split) - set(NEW_CASE_IDS) - set(REDESCRIBE_CASE_IDS)
    table = EXISTING_EDIT_OPERATIONS[split]
    assert discovered == set(table), (
        f"{split}: edit cases without an operations equivalent: {sorted(discovered - set(table))}; "
        f"table entries with no case: {sorted(set(table) - discovered)}")

    failures = []
    for cid in sorted(table):
        c = _case(cid, split)
        current = _deck(c)
        reference_spec = DeckSpec.model_validate(c.reference["deck_spec"])
        answer = _answer(_equivalent(table[cid], _slides(c.reference["deck_spec"])),
                         message=c.reference["message"])
        # Guard: the table entry really is the reference, in operations form.
        spec, result = _composed(answer, current)
        assert spec.slides == reference_spec.slides, f"{split}/{cid}: table != reference slides"
        assert list(result.rebuild) == sorted(c.expect["positions"]), (split, cid, result.rebuild)

        for via, (ok, why) in _both(answer, c.expect, current, c.reference):
            if not ok:
                failures.append(f"{split}/{cid} via {via}: {why}")
    assert not failures, "\n".join(failures)


# --------------------------------------------------------------------------- 3. spec answers

# What every existing deck_spec-shaped answer (reference and should_fail) scores TODAY, at 73d00512.
TODAY = {
    ("train", "add_slide_anchor"): (
        (True, "Architect intent and insert alignment match (inserted [3], revised [])"),
        (True, "Architect intent and insert alignment match (inserted [3], revised [])")),
    ("train", "add_slide_and_revise"): (
        (True, "Architect intent and insert alignment match (inserted [8], revised [10])"),
        (False, "Insert: revised [] != [10]")),
    ("train", "add_slide_as_number"): (
        (True, "Architect intent and insert alignment match (inserted [1], revised [])"),
        (False, "Insert: inserted [2] != [1]")),
    ("train", "add_slide_end"): (
        (True, "Architect intent and insert alignment match (inserted [10], revised [])"),
        (False, "Insert: inserted [] != [10]")),
    ("train", "edit_beside_blank"): (
        (True, "Architect intent and insert alignment match (inserted [], revised [6])"),
        (False, "Insert: revised [5, 6] != [6]")),
    ("train", "edit_last_slide"): (
        (True, "Architect intent and positions match"),
        (False, "Target positions mismatch: got {10}, expected {9}")),
    ("train", "edit_multi_slide"): (
        (True, "Architect intent and positions match"),
        (False, "Target positions mismatch: got {4, 5, 6}, expected {3, 4, 5}")),
    ("train", "edit_polite_ordinal"): (
        (True, "Architect intent and positions match"),
        (False, "Intent mismatch: got 'discuss', expected 'edit'")),
    ("train", "edit_request"): (
        (True, "Architect intent and positions match"),
        (False, "Target positions mismatch: got {2}, expected {1}")),
    ("train", "fill_blank_slide"): (
        (True, "Architect intent and insert alignment match (inserted [], revised [5])"),
        (False, "Insert: inserted [5] != []")),
    ("heldout", "add_slide_anchor"): (
        (True, "Architect intent and insert alignment match (inserted [4], revised [])"),
        (True, "Architect intent and insert alignment match (inserted [4], revised [])")),
    ("heldout", "add_slide_and_revise"): (
        (True, "Architect intent and insert alignment match (inserted [3], revised [6])"),
        (False, "Insert: revised [] != [6]")),
    ("heldout", "add_slide_as_number"): (
        (True, "Architect intent and insert alignment match (inserted [3], revised [])"),
        (False, "Insert: inserted [4] != [3]")),
    ("heldout", "add_slide_end"): (
        (True, "Architect intent and insert alignment match (inserted [6], revised [])"),
        (False, "Insert: inserted [] != [6]")),
    ("heldout", "edit_beside_blank"): (
        (True, "Architect intent and insert alignment match (inserted [], revised [4])"),
        (False, "Insert: revised [3, 4] != [4]")),
    ("heldout", "edit_last_slide"): (
        (True, "Architect intent and positions match"),
        (False, "Target positions mismatch: got {6}, expected {5}")),
    ("heldout", "edit_multi_slide"): (
        (True, "Architect intent and positions match"),
        (False, "Target positions mismatch: got {2, 3}, expected {1, 2}")),
    ("heldout", "edit_polite_ordinal"): (
        (True, "Architect intent and positions match"),
        (False, "Intent mismatch: got 'discuss', expected 'edit'")),
    ("heldout", "edit_request"): (
        (True, "Architect intent and positions match"),
        (False, "Target positions mismatch: got {3}, expected {2}")),
    ("heldout", "fill_blank_slide"): (
        (True, "Architect intent and insert alignment match (inserted [], revised [3])"),
        (False, "Insert: inserted [3] != []")),
}


@pytest.mark.parametrize("split", SPLITS)
def test_spec_answers_still_use_alignment_scorer(split):
    """A deck_spec-shaped answer scores exactly as today: same verdict, same rationale.

    Each existing edit case's reference.json and should_fail, as written and with the explicit
    ``operations: None`` / ``deck_changes: None`` keys the runner's ``model_dump`` adds. And a
    ``discuss`` answer carrying operations is still a discuss (production ignores them there).
    """
    wanted = {cid for (s, cid) in TODAY if s == split}
    assert wanted == set(EXISTING_EDIT_OPERATIONS[split])
    for cid in sorted(wanted):
        c = _case(cid, split)
        today_ref, today_bad = TODAY[(split, cid)]
        for label, answer, today in (("reference", c.reference, today_ref),
                                     ("should_fail", _should_fail(cid, split), today_bad)):
            assert "operations" not in answer and "deck_changes" not in answer, (cid, label)
            for form, structured in (("as written", answer),
                                     ("with None keys", {**answer, "operations": None,
                                                         "deck_changes": None})):
                got = expected_category_score(
                    AGENT, structured, c.expect,
                    reference=c.reference, current_deck_spec=_deck(c))
                assert got == today, f"{split}/{cid} {label} {form}: {got} != today's {today}"

    d = _case("discuss", split)
    plain = expected_category_score(AGENT, d.reference, d.expect,
                                    reference=d.reference, current_deck_spec=_deck(d))
    with_ops = expected_category_score(
        AGENT, {**d.reference, "operations": [_del(0)], "deck_changes": None}, d.expect,
        reference=d.reference, current_deck_spec=_deck(d))
    assert with_ops == plain == (True, "Architect intent and positions match")


# --------------------------------------------------------------------------- 4. judge input

def _assert_composed(judged: dict, answer: dict, current: dict, what: str) -> None:
    spec, result = _composed(answer, current)
    assert isinstance(judged, dict), (what, judged)
    assert json.loads(json.dumps(judged)) == judged, f"{what}: not a JSON-native dict"
    assert judged.get("intent") == answer["intent"], what
    assert judged.get("message") == answer["message"], what
    assert judged.get("deck_spec") is not None, f"{what}: the judge saw no composed deck_spec"
    assert DeckSpec.model_validate(judged["deck_spec"]) == spec, (
        f"{what}: deck_spec is not the composed spec")
    rebuild = list(result.rebuild)
    assert judged.get("target_positions") == rebuild, (
        f"{what}: target_positions {judged.get('target_positions')} != rebuild {rebuild}")


class _StubJudge:
    """Records each judge call's ``outputs`` and ``expectations``; always passes."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return Feedback(value="pass", rationale="stub")


def _spy_on_helper(monkeypatch) -> list[tuple[dict, dict | None]]:
    """Record every call of the shared helper (it still does its work)."""
    real = scorers.compose_operations_answer
    calls = []

    def spy(output, current_deck_spec):
        calls.append((copy.deepcopy(output), copy.deepcopy(current_deck_spec)))
        return real(output, current_deck_spec)

    _patch_everywhere(monkeypatch, real, spy)
    return calls


def _with_reference(c: Case, reference: dict) -> Case:
    return dataclasses.replace(c, reference=reference)


@pytest.mark.parametrize("path", ["helper", "judge-scorer", "calibrate"])
def test_judge_input_is_composed(path, monkeypatch):
    """The judge sees an operations answer in its composed full-deck form, on BOTH judge paths,
    through ONE shared helper (C2); a spec answer reaches it unchanged.

    An operations-shaped reference (the new cases' references) is composed too, so the judge
    always compares like with like.
    """
    c, current, ops, new, _ = _base()
    good = _answer(ops, message="OPS-REFERENCE: add slide 9 and revise the summary.")
    forgot = _answer([_ins(7, new)], message="OPS-SHOULD-FAIL: add slide 9 only.")

    if path == "helper":
        helper = scorers.compose_operations_answer
        before = copy.deepcopy(good)
        _assert_composed(helper(good, current), good, current, "operations answer")
        assert good == before, "the helper must not mutate its input"

        e = _case("edit_request")
        changes_only = _answer(None, deck_changes={"title": "A renamed deck"})
        judged = helper(changes_only, _deck(e))
        _assert_composed(judged, changes_only, _deck(e), "deck_changes-only answer")
        assert judged["deck_spec"]["title"] == "A renamed deck" and judged["target_positions"] == []

        spec_answer = c.reference
        assert helper(spec_answer, current) == spec_answer
        explicit_none = {**spec_answer, "operations": None, "deck_changes": None}
        assert helper(explicit_none, current) == explicit_none
        discuss = _answer(ops, intent="discuss")
        assert helper(discuss, current) == discuss, "operations on a non-edit are ignored"
        # An answer that cannot be composed (production refuses it, or there is no deck) must
        # not raise: the deterministic scorer is what fails it.
        assert isinstance(helper(_answer([_upd(10, new)]), current), dict)
        assert isinstance(helper(good, None), dict)
        return

    calls = _spy_on_helper(monkeypatch)
    stub = _StubJudge()
    monkeypatch.setattr(judge_mod, "build_judge", lambda *a, **k: stub)

    if path == "judge-scorer":
        ops_case = _with_reference(c, good)
        by_id = {}
        monkeypatch.setattr(
            mlflow_run, "load_case", lambda agent_key, case_id, **kw: by_id[case_id])
        built = mlflow_run.build_scorers(AGENT, judge_endpoint="stub")
        judge = {s.name: s for s in built}["judge"]

        def run(the_case, structured):
            by_id[the_case.case_id] = the_case
            row = mlflow_run.build_dataset([the_case], 1)[0]
            outputs = {"structured": structured, "raw": None, "render": None, "latency_ms": 1.0,
                       "input_tokens": None, "output_tokens": None, "status": "completed",
                       "infra_error": False}
            fb = judge.run(inputs=row["inputs"], outputs=outputs, expectations=row["expectations"])
            assert fb.value == "pass", fb
            return stub.calls[-1]

        seen = run(ops_case, forgot)
        _assert_composed(seen["outputs"], forgot, current, "judge scorer candidate")
        _assert_composed(seen["expectations"]["reference"], good, current, "judge scorer reference")
        assert (forgot, current) in calls, "the judge scorer must normalise via the shared helper"

        seen = run(c, c.reference)  # a spec answer, a spec reference: both exactly as today
        assert seen["outputs"] == c.reference
        assert seen["expectations"]["reference"] == c.reference
        return

    # calibrate: judges reference.json and should_fail directly.
    ops_case = dataclasses.replace(_with_reference(c, good), case_id="ops_case")
    spec_case = c
    spec_bad = _should_fail(BASE)
    cal = {"ops_case": {"should_fail": forgot}, BASE: {"should_fail": spec_bad}}
    monkeypatch.setattr(judge_mod, "load_cases", lambda agent_key, **kw: [ops_case, spec_case])
    monkeypatch.setattr(
        judge_mod, "load_calibration", lambda agent_key, case_id, **kw: cal[case_id])
    rows = judge_mod.calibrate(AGENT)
    assert [r["case_id"] for r in rows] == ["ops_case", BASE]
    assert len(stub.calls) == 4
    by_message = {call["outputs"].get("message"): call for call in stub.calls[:2]}
    assert set(by_message) == {good["message"], forgot["message"]}, by_message.keys()
    for answer in (good, forgot):
        seen = by_message[answer["message"]]
        _assert_composed(seen["outputs"], answer, current, f"calibrate {answer['message']}")
        _assert_composed(seen["expectations"]["reference"], good, current, "calibrate reference")
        assert (answer, current) in calls, "calibrate must normalise through the shared helper"
    spec_outputs = [call["outputs"] for call in stub.calls[2:]]
    assert spec_outputs == [c.reference, spec_bad], "spec answers reach the judge unchanged"
    assert all(call["expectations"]["reference"] == c.reference for call in stub.calls[2:])


# --------------------------------------------------------------------------- 5. the new cases

def _op_kinds(answer: dict) -> list[str]:
    return [op["op"] for op in answer["operations"]]


def _referenced_positions(payload: dict) -> set[int]:
    return {p for ref in payload["slide_references"] for p in ref["positions"]}


@pytest.mark.parametrize("cid", NEW_CASE_IDS)
@pytest.mark.parametrize("split", SPLITS)
def test_new_case_references_pass_and_calibrations_fail(split, cid):
    d = case.cases_dir(AGENT, split=split) / cid
    assert d.is_dir(), f"missing case directory {d}"
    assert sorted(p.name for p in d.iterdir()) == sorted(FILES)

    c = _case(cid, split)
    base = _case(BASE, split)
    assert c.kind == "mutation" and c.fault.strip() and c.design_system_active is True
    assert c.expect["intent"] == "edit"

    # The payload is add_slide_and_revise's, on the split's own fixture deck, with a new message.
    p, bp = c.payload, base.payload
    assert list(p) == list(bp), "the payload keys, in architect_node's order"
    assert p["current_deck_spec"] == case.gold_deck_spec(split) == bp["current_deck_spec"]
    for key in ("committed_slide_count", "previous_deck_review", "available_design_contract",
                "template_sections", "resolved_style", "design_system_library"):
        assert p[key] == bp[key], key
    assert p["conversation"][:2] == bp["conversation"][:2]
    assert p["conversation"][2:] == [{"role": "user", "content": p["message"]}]
    others = {o.payload["message"] for o in case.load_cases(AGENT, **case.split_kwargs(split))
              if o.case_id != cid}
    assert p["message"] not in others
    positions = [s["position"] for s in p["current_deck_spec"]["slides"]]
    assert {k: p[k] for k in ("slide_numbering", "slide_references")} == architect_slide_payload(
        p["conversation"], p["message"], positions)

    # reference.json: an ArchitectOutput carrying operations, passing production's own reading.
    current = _deck(c)
    ref = c.reference
    out = ArchitectOutput.model_validate(ref)
    assert out.intent == "edit" and out.operations, "the reference must carry operations"
    assert out.deck_spec is None, "an operations edit no longer returns the whole deck_spec (§8)"
    assert out.message.strip()
    spec, result = _composed(ref, current)
    bound = spec.model_copy(deep=True)
    complete_index_only_bindings(bound, p["template_sections"])
    assert invalid_slide_bindings(bound, p["template_sections"]) == [], "production would refuse"
    for via, (ok, why) in _both(ref, c.expect, current, ref):
        assert ok, f"{split}/{cid} reference fails via {via}: {why}"

    # calibration.json: a plausible wrong answer that the deterministic scorer fails.
    bad = _should_fail(cid, split)
    bad_out = ArchitectOutput.model_validate(bad)
    assert bad != ref
    ok, why = expected_category_score(
        AGENT, bad, c.expect, reference=ref, current_deck_spec=current)
    assert not ok, f"{split}/{cid} should_fail passes the deterministic scorer: {why}"

    n = len(current["slides"])
    expect = c.expect
    if cid == "replace_slide_expand":
        # The production shape: "Replace slide N with these M slides" = rewrite N, add M-1 after it.
        assert _op_kinds(ref) == ["replace"]
        replaced = ref["operations"][0]["position"]
        want = expect["positions"]
        k = want[0]
        assert len(want) >= 3 and want == list(range(k, k + len(want))), want
        assert expect["inserted"] == want[1:], "one slide rewritten, the rest new directly after it"
        assert len(ref["operations"][0]["slides"]) == len(want)
        assert result.layout[k] == replaced == k, "the first replacement keeps the old slide's row"
        assert all(result.layout[i] is None for i in want[1:])
        assert replaced in _referenced_positions(p), "the message names the replaced slide"
        # Its should_fail is the production failure: the grown deck as a full spec, which
        # align_slides refuses as ambiguous.
        assert bad_out.operations is None and bad_out.deck_changes is None
        assert bad_out.deck_spec is not None and len(bad_out.deck_spec.slides) > n
        with pytest.raises(AlignmentRefused) as refused:
            align_slides(DeckSpec.model_validate(current).slides, bad_out.deck_spec.slides)
        assert refused.value.code == "ambiguous"
        assert "ambiguous" in why, why
        return

    # delete / move / mixed: only the layout says WHICH slide went where, so it is expected.
    assert "layout" in expect, f"{cid}: expect must carry layout (rebuild alone cannot tell)"
    assert expect["layout"] == list(result.layout)
    assert bad_out.intent == "edit" and bad_out.operations, (
        "a plausible wrong answer in the same form: a wrong anchor or a dropped slide")
    if cid == "delete_slide":
        assert _op_kinds(ref) == ["delete"]
        gone = ref["operations"][0]["position"]
        assert expect.get("positions", []) == [] and expect.get("inserted", []) == []
        assert len(expect["layout"]) == n - 1 and None not in expect["layout"]
        assert gone not in expect["layout"]
        # §7: a deleted slide is named by the number it had.
        assert re.search(rf"\bslide {gone + 1}\b", out.message, re.IGNORECASE), out.message
    elif cid == "move_slide":
        assert _op_kinds(ref) == ["move"]
        assert expect.get("positions", []) == [] and expect.get("inserted", []) == []
        assert sorted(expect["layout"]) == list(range(n)) and expect["layout"] != list(range(n))
    else:  # mixed_operations: delete a, retitle b, expand c into three slides
        assert sorted(_op_kinds(ref)) == ["delete", "replace", "update"]
        replace = next(op for op in ref["operations"] if op["op"] == "replace")
        assert len(replace["slides"]) == 3
        assert len(expect["inserted"]) == 2 and len(expect["positions"]) == 4
        assert len(expect["layout"]) == n - 1 + 2
