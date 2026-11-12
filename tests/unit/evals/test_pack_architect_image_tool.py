"""Self-tests for the architect's image-tool case set (chat image generation, Task 9).

Behavioural and offline; no model, no network. The set lives apart from the architect's train and
held-out cases (``evals/packs/architect/cases_image_tool/``, ``case.case_set_dir``), is generated
by ``evals/packs/architect/image_tool.py`` and carries the same four files per case. Its decks are
a small seeded deck (``image_tool.seeded_deck()``, four slides) or none.

Each case's ``expect`` holds the intent (and, for an edit, ``positions``), scored by
``expected_category``, and ``image_tool`` (``called``, then ``count``, ``kinds`` and, for an exact
ask, the 1-based ``slide``), scored by ``scorers.image_tool_score``. A reference answer passes
both, given a record of the call it implies (its token is ``image_tool.reference_token(cid)``); a
``should_fail`` fails one of them and differs from the reference in what the judge sees.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case
from evals.harness.scorers import expected_category_score, image_tool_score
from evals.packs.architect import image_tool as gen
from src.domain.deck_spec import DeckSpec
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_numbering import architect_slide_payload
from src.services.agent_model_payload import model_payload_for
from src.utils.image_refs import refs_in

AGENT = "architect"
CASE_IDS = {
    "picture_options", "icon_options", "exact_icon", "exact_background",
    "build_no_image", "concise_no_image", "empty_deck_picture", "image_question",
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
ROOT = case.case_set_dir(AGENT, "image_tool")
OPTIONS = {"picture_options", "icon_options", "empty_deck_picture"}
EXACT = {"exact_icon": 2, "exact_background": 1}
NO_CALL = {"build_no_image", "concise_no_image", "image_question"}


def _cases():
    return {c.case_id: c for c in case.load_cases(AGENT, root=ROOT)}


def _record(c, *, extra_tokens: int | None = None):
    """The record of the one call a case's reference implies: the reference token first."""
    want = c.expect["image_tool"]
    if not want["called"]:
        return ()
    n = want["count"] if extra_tokens is None else extra_tokens
    tokens = [gen.reference_token(c.case_id)] + [
        hashlib.sha256(f"{c.case_id}-{i}".encode()).hexdigest()[:43] for i in range(1, n)]
    return ({"name": "generate_image", "args": {"kind": want["kinds"][0], "count": want["count"]},
             "saved": [{"token": t, "prompt": "p", "category": "content", "tags": []}
                       for t in tokens]},)


def _tree(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# =========================================================================== the set

def test_the_set_lives_apart_from_train_and_held_out():
    assert gen.CASES_DIR == ROOT == case.PACKS_DIR / AGENT / "cases_image_tool"
    assert ROOT not in (case.cases_dir(AGENT), case.cases_dir(AGENT, split="heldout"))
    for split in case.SPLITS:
        ids = {c.case_id for c in case.load_cases(AGENT, split=split)}
        # 22 plus the six Stage Slide cases (plan Task 4).
        assert len(ids) == 28 and not ids & CASE_IDS, split
        assert not any(
            "image_tool" in (c.expect or {}) for c in case.load_cases(AGENT, split=split))


def test_the_case_ids_are_pinned():
    assert set(gen.CASE_IDS) == CASE_IDS
    assert set(_cases()) == CASE_IDS
    assert {d.name for d in ROOT.iterdir() if d.is_dir()} == CASE_IDS


def test_every_case_has_the_four_files_and_a_design_system():
    for c in _cases().values():
        assert sorted(p.name for p in (ROOT / c.case_id).iterdir()) == sorted(FILES), c.case_id
        assert c.design_system_active is True
        assert c.agent_key == AGENT


def test_the_behaviours_are_the_brief_s():
    cases = _cases()
    for cid in OPTIONS:
        want = cases[cid].expect
        assert want["intent"] == "discuss", cid
        assert want["image_tool"]["called"] is True and want["image_tool"]["count"] == 3, cid
        assert "slide" not in want["image_tool"], cid
    for cid, slide in EXACT.items():
        want = cases[cid].expect
        assert want["intent"] == "edit" and want["positions"] == [slide - 1], cid
        assert want["image_tool"] == {**want["image_tool"], "called": True, "count": 1,
                                      "slide": slide}, cid
    for cid in NO_CALL:
        assert cases[cid].expect["image_tool"] == {"called": False}, cid
    assert set(cases["icon_options"].expect["image_tool"]["kinds"]) == {"icon", "vector_icon"}
    assert set(cases["exact_icon"].expect["image_tool"]["kinds"]) == {"icon", "vector_icon"}
    assert cases["exact_background"].expect["image_tool"]["kinds"] == ["background"]
    assert cases["picture_options"].expect["image_tool"]["kinds"] == ["illustration"]
    assert cases["build_no_image"].expect["intent"] == "build"
    assert cases["concise_no_image"].expect == {"intent": "edit", "positions": [3],
                                                "image_tool": {"called": False}}


def test_the_messages_are_the_brief_s():
    msgs = {cid: c.payload["message"] for cid, c in _cases().items()}
    assert msgs["picture_options"] == "Make me a picture to get slide 2's message across"
    assert msgs["exact_icon"] == "Add a shield icon to slide 2"
    assert msgs["concise_no_image"] == "Make slide 4 more concise"
    assert msgs["build_no_image"].startswith("Build me a deck on ")
    assert msgs["empty_deck_picture"].startswith("Make me a picture")
    assert "icon options for slide 3" in msgs["icon_options"]
    assert len(set(msgs.values())) == len(msgs)


# =========================================================================== payloads

def test_the_seeded_deck_is_small_valid_and_image_free():
    deck = gen.seeded_deck()
    DeckSpec.model_validate(deck)
    assert [s["position"] for s in deck["slides"]] == [0, 1, 2, 3]
    assert not refs_in(deck)
    assert gen.seeded_deck() == deck and gen.seeded_deck() is not deck


def test_payloads_are_production_shaped():
    for cid, c in _cases().items():
        p = c.payload
        assert model_payload_for(AGENT, p) == p, cid
        deck = p["current_deck_spec"]
        conversation = p["conversation"]
        assert conversation[-1] == {"role": "user", "content": p["message"]}, cid
        if cid in ("build_no_image", "empty_deck_picture"):
            assert deck is None and p["committed_slide_count"] == 0, cid
            assert len(conversation) == 1, cid
        else:
            assert deck == gen.seeded_deck(), cid
            assert p["committed_slide_count"] == 4, cid
            assert len(conversation) == 3, cid
        positions = [s["position"] for s in deck["slides"]] if deck else []
        assert {k: p[k] for k in ("slide_numbering", "slide_references")} == \
            architect_slide_payload(conversation, p["message"], positions), cid
        assert p["deck_style_context"] == case.meridian_deck_style_context(), cid
        assert p["resolved_style"] == case.meridian_resolved_style(), cid
        assert not refs_in(p), cid


def test_the_slide_references_resolve_the_named_slides():
    cases = _cases()
    for cid, positions in (("picture_options", [1]), ("icon_options", [2]), ("exact_icon", [1]),
                           ("exact_background", [0]), ("concise_no_image", [3])):
        (ref,) = cases[cid].payload["slide_references"]
        assert ref["positions"] == positions, cid


# =========================================================================== references

def test_reference_tokens_are_token_shaped_and_distinct():
    tokens = {cid: gen.reference_token(cid) for cid in CASE_IDS}
    assert all(TOKEN_RE.match(t) for t in tokens.values())
    assert len(set(tokens.values())) == len(tokens)


@pytest.mark.parametrize("cid", sorted(CASE_IDS))
def test_the_reference_passes_both_deterministic_scorers(cid):
    c = _cases()[cid]
    ArchitectOutput.model_validate(c.reference)
    deck = c.payload["current_deck_spec"]
    ok, why = expected_category_score(AGENT, c.reference, c.expect, reference=c.reference,
                                      current_deck_spec=deck, design_system_active=True)
    assert ok, why
    ok, why = image_tool_score(c.reference, c.expect, tool_calls=_record(c), current_deck_spec=deck)
    assert ok, why


@pytest.mark.parametrize("cid", sorted(EXACT))
def test_an_exact_reference_places_its_token_in_the_named_slide_s_brief(cid):
    c = _cases()[cid]
    token = gen.reference_token(cid)
    (op,) = c.reference["operations"]
    assert op["op"] == "update" and op["position"] == EXACT[cid] - 1
    assert "{{image:" + token + "}}" in op["slides"][0]["content_brief"]
    assert token not in c.reference["message"]


@pytest.mark.parametrize("cid", sorted(OPTIONS | NO_CALL))
def test_a_reference_that_places_nothing_references_no_image(cid):
    c = _cases()[cid]
    assert not refs_in(c.reference), cid
    assert gen.reference_token(cid) not in json.dumps(c.reference)


@pytest.mark.parametrize("cid", sorted(CASE_IDS))
def test_the_should_fail_fails_a_deterministic_scorer_and_reads_differently(cid):
    c = _cases()[cid]
    cal = json.loads((ROOT / cid / "calibration.json").read_text())
    bad = cal["should_fail"]
    ArchitectOutput.model_validate(bad)
    deck = c.payload["current_deck_spec"]
    cat_ok, _ = expected_category_score(AGENT, bad, c.expect, reference=c.reference,
                                        current_deck_spec=deck, design_system_active=True)
    img_ok, _ = image_tool_score(bad, c.expect, tool_calls=_record(c), current_deck_spec=deck)
    assert not (cat_ok and img_ok), cid
    # The judge sees outputs, never the tool record: the trap must show in the answer itself.
    assert (bad["intent"], bad.get("target_positions")) != (
        c.reference["intent"], c.reference.get("target_positions")), cid


# =========================================================================== generation

def test_generation_is_idempotent(tmp_path):
    out = tmp_path / "cases_image_tool"
    gen.generate(out_dir=out)
    assert _tree(out) == _tree(ROOT)


def test_generate_into_out_dir_leaves_every_committed_tree_untouched(tmp_path):
    trees = [ROOT, case.cases_dir(AGENT), case.cases_dir(AGENT, split="heldout")]
    before = [_tree(t) for t in trees]
    gen.generate(out_dir=tmp_path / "x")
    assert [_tree(t) for t in trees] == before


def test_generate_default_targets_the_committed_set():
    import inspect

    assert inspect.signature(gen.generate).parameters["out_dir"].default is None
    assert gen.CASE_SET == "image_tool"


def test_a_generated_case_loads_like_the_committed_one(tmp_path):
    out = tmp_path / "cases_image_tool"
    gen.generate(out_dir=out)
    for cid in CASE_IDS:
        a, b = case.load_case(AGENT, cid, root=out), case.load_case(AGENT, cid, root=ROOT)
        assert a == b, cid
        assert copy.deepcopy(a.payload) == b.payload


# =========================================================================== production-key parity

#: The production architect payload keys, in architect_node's order (whole-branch review I1):
#: architect_node always sends ``stage_slide`` (null with no slide on stage), so an eval payload
#: without it tests a prompt shape the architect never sees.  ``data_sources`` (agent-mode Task 7)
#: is always last.
PAYLOAD_KEYS = [
    "conversation", "message", "current_deck_spec", "committed_slide_count",
    "slide_numbering", "slide_references", "stage_slide",
    "previous_deck_review", "available_design_contract", "template_sections",
    "resolved_style", "design_system_library", "deck_style_context", "data_sources",
]


def test_payload_keys_are_every_production_key():
    from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

    assert set(PAYLOAD_KEYS) == set(MODEL_PAYLOAD_KEYS[AGENT]) - {"rejected_edit"}
    assert len(PAYLOAD_KEYS) == len(set(PAYLOAD_KEYS)) == 14


@pytest.mark.parametrize("cid", sorted(CASE_IDS))
def test_the_committed_payload_has_every_production_key_in_order(cid):
    p = _cases()[cid].payload
    assert list(p) == PAYLOAD_KEYS, cid


@pytest.mark.parametrize("cid", sorted(CASE_IDS))
def test_the_committed_payload_has_no_stage(cid):
    """No image-tool case is sent with a slide on stage: ``stage_slide`` is present and null."""
    p = _cases()[cid].payload
    assert "stage_slide" in p and p["stage_slide"] is None, cid


def test_the_generator_writes_the_production_keys(tmp_path):
    out = tmp_path / "cases_image_tool"
    gen.generate(out_dir=out)
    for cid in sorted(CASE_IDS):
        p = case.load_case(AGENT, cid, root=out).payload
        assert list(p) == PAYLOAD_KEYS, cid
        assert p["stage_slide"] is None, cid
