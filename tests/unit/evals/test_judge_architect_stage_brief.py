"""The architect judge sees the Stage Slide when, and only when, the case has one (plan Task 4).

``judge._brief_or_finding`` gives the architect judge the user's ``message`` and the
``current_deck_spec``. A Stage Slide case's right answer depends on the slide on stage ("change
the title" means the stage slide's), so without ``stage_slide`` the judge cannot tell a correct
edit from one on the wrong slide. The same rule as the builder's ``deck_style``: added only when
the payload carries a non-null value, so every existing case's brief is byte-for-byte what it was.

This adds an input the judge was missing; it changes no judge instruction, criterion, reference or
calibration. Offline; no model.
"""
from __future__ import annotations

import types

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case, judge
from evals.harness.case import Case

AGENT = "architect"
STAGE = {"slide_number": 6, "position": 5}
DECK = {"title": "DECK-SENTINEL", "slides": []}


def _case(payload: dict) -> Case:
    return Case(
        case_id="c", agent_key=AGENT, kind="mutation", design_system_active=True, fault="f",
        payload=payload, reference={"intent": "discuss", "message": "m"}, expect={},
    )


def _brief(payload: dict):
    return judge.judge_payload(
        _case(payload), types.SimpleNamespace(structured={"intent": "discuss"}), None,
    )["brief_or_finding"]


def test_a_stage_reaches_the_judge():
    brief = _brief({"message": "Change the title", "current_deck_spec": DECK, "stage_slide": STAGE})
    assert brief == {"message": "Change the title", "current_deck_spec": DECK, "stage_slide": STAGE}


def test_the_stage_is_the_model_facing_value_as_given():
    stage = {"slide_number": 2, "position": 8}
    brief = _brief({"message": "m", "current_deck_spec": DECK, "stage_slide": stage})
    assert brief["stage_slide"] == stage


@pytest.mark.parametrize("payload", [
    {"message": "m", "current_deck_spec": DECK, "stage_slide": None},
    {"message": "m", "current_deck_spec": DECK},
], ids=["null", "absent"])
def test_no_stage_leaves_the_brief_exactly_as_it_was(payload):
    assert _brief(payload) == {"message": "m", "current_deck_spec": DECK}


@pytest.mark.parametrize("split", ["train", "heldout"])
def test_every_committed_case_without_a_stage_keeps_its_brief(split):
    """Every committed architect case with a null stage: the brief is exactly the old two keys."""
    cases = [c for c in case.load_cases(AGENT, **case.split_kwargs(split))
             if c.payload.get("stage_slide") is None]
    assert cases
    for c in cases:
        brief = judge._brief_or_finding(c)
        assert brief == {
            "message": c.payload.get("message"),
            "current_deck_spec": c.payload.get("current_deck_spec"),
        }, c.case_id


@pytest.mark.parametrize("split", ["train", "heldout"])
def test_every_committed_stage_case_shows_its_stage_to_the_judge(split):
    from evals.packs.architect import stage_cases

    by_id = {c.case_id: c for c in case.load_cases(AGENT, **case.split_kwargs(split))}
    for cid in stage_cases.STAGE_CASE_IDS:
        assert cid in by_id, f"{split}: {cid} is not committed"
        c = by_id[cid]
        assert c.payload["stage_slide"] is not None, cid
        assert judge._brief_or_finding(c)["stage_slide"] == c.payload["stage_slide"], cid
