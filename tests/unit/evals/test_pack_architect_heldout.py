"""Self-tests for the architect HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import copy
import hashlib
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckSpec
from src.domain.deck_spec_slides import (
    BLANK_DECK_SPEC_ENTRY,
    is_blank_slide_spec,
    spec_json_with_blank_entry,
)
from src.domain.skill_io import ArchitectOutput, DataRequest
from src.domain.slide_alignment import align_slides
from src.domain.slide_numbering import architect_slide_payload
from src.domain.slide_operations import OperationsResult, apply_operations, compose_edit_spec
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS
from src.services.template_sections import section_inventory

from evals.harness import case
from evals.harness.scorers import expected_category_score

AGENT = "architect"
DECK = "heldout"
EXISTING_CASE_IDS = ["build_request", "edit_request", "ask_data", "confirm_design", "discuss"]
# #313: intent and slide-reference cases on deck 2 (plan Appendix H).
CASES_313 = ["edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question"]
# #314: add-a-slide cases on deck 2 (plan Appendix H). They are folded into NEW_CASE_IDS, so
# MUTATIONS, HAS_DECK, CASE_IDS and EDIT_CASES all carry them (C19).
INSERT_CASES = ["add_slide_anchor", "add_slide_end", "add_slide_as_number", "add_slide_and_revise"]
# #314 follow-up (manual insert, plan Task 11): deck 2 with a manually inserted blank slide
# spliced into its spec at BLANK_AT. Folded into NEW_CASE_IDS like the insert cases.
BLANK_CASES = ["fill_blank_slide", "edit_beside_blank"]
# Architect edit operations (spec §9): delete, move, replace and mixed edits on deck 2, whose
# references answer in operations (no deck_spec). Folded into NEW_CASE_IDS like the insert cases;
# tests/unit/evals/test_eval_operations_scorer.py checks their content and scoring.
OPERATIONS_CASES = ["delete_slide", "move_slide", "replace_slide_expand", "mixed_operations"]
NEW_CASE_IDS = CASES_313 + INSERT_CASES + BLANK_CASES + OPERATIONS_CASES
CASE_IDS = EXISTING_CASE_IDS + NEW_CASE_IDS
MUTATIONS = ["edit_request", "ask_data", "confirm_design"] + NEW_CASE_IDS
EXPECT = {
    "build_request": {"intent": "build"},
    "edit_request": {"intent": "edit", "positions": [2]},
    "ask_data": {"intent": "ask_data"},
    "confirm_design": {"intent": "confirm_design_contract"},
    "discuss": {"intent": "discuss"},
    "edit_polite_ordinal": {"intent": "edit", "positions": [3]},
    "edit_last_slide": {"intent": "edit", "positions": [5]},
    "edit_multi_slide": {"intent": "edit", "positions": [1, 2]},
    "discuss_slide_question": {"intent": "discuss"},
    # #314: positions and inserted are in the revised deck's numbering (D10).
    "add_slide_anchor": {"intent": "edit", "positions": [4], "inserted": [4]},
    "add_slide_end": {"intent": "edit", "positions": [6], "inserted": [6]},
    "add_slide_as_number": {"intent": "edit", "positions": [3], "inserted": [3]},
    "add_slide_and_revise": {"intent": "edit", "positions": [3, 6], "inserted": [3]},
    # #314 follow-up: positions in the blank deck's numbering. ``inserted: []`` routes scoring
    # through production's alignment, so a new slide beside the blank fails (D10).
    "fill_blank_slide": {"intent": "edit", "positions": [3], "inserted": []},
    "edit_beside_blank": {"intent": "edit", "positions": [4], "inserted": []},
    # Edit operations: positions is the rebuild set and inserted the new slides, both in the
    # edited deck's numbering; layout is each index's persisted position (None = a new slide).
    "delete_slide": {"intent": "edit", "positions": [], "inserted": [], "layout": [0, 1, 2, 4, 5]},
    "move_slide": {
        "intent": "edit", "positions": [], "inserted": [], "layout": [0, 1, 2, 4, 3, 5],
    },
    "replace_slide_expand": {"intent": "edit", "positions": [2, 3, 4], "inserted": [3, 4]},
    "mixed_operations": {
        "intent": "edit", "positions": [0, 1, 2, 3], "inserted": [1, 2],
        "layout": [1, None, None, 2, 3, 4, 5],
    },
}
HAS_DECK = {"edit_request", "confirm_design", "discuss"} | set(NEW_CASE_IDS)
EDIT_CASES = [c for c in CASE_IDS if EXPECT[c]["intent"] == "edit"]
# #314 (D11, finding 11): this case's should_fail is right place and right targets with an
# off-request new slide. The deterministic scorer passes it; only the judge separates it.
JUDGE_ONLY_CALIBRATION = {"add_slide_anchor"}
# Position cases whose calibration is the reference with every target slipped by +1 (D7).
SLIPPED = ["edit_last_slide", "edit_multi_slide"]
# D7: adding the #313 cases leaves the five existing cases byte-identical. Digests of the files at
# 679d2f21. Task 7 adds the two SLIDE_KEYS to every payload.json on purpose and re-pins nothing: a
# payload.json digest is checked on that payload with the two keys stripped (D11).
EXISTING_CASE_SHA256 = {
    "ask_data/calibration.json": "0761dfd021fbf5f9abaa73c0fe33735f16f0d3afce5be5bc46a0d9252f7fd086",
    "ask_data/case.yaml": "507b1f55e8479b02535af8ba1363b7a76bc3ef2d3310849f9af3aca51c17abe6",
    "ask_data/payload.json": "75ffca76ebf5258295ecc8a0eef920955efa6d0e1e809dbfd25bf0e4b75c3c96",
    "ask_data/reference.json": "ac10a07cfa840c55f0b001da058fcfe69788e952eb3fe9fd4b334ecb929e7f9d",
    "build_request/calibration.json": "cdb0f35e3df90091bdff95ab7abbac7648396d6cb2b3aaaa148a8c35b38a4f33",
    "build_request/case.yaml": "02e9256188dad0c24a724a740f8acfa2fe033d9ff87ba3bc8bd0c0a2af47eece",
    "build_request/payload.json": "32cca43ea663ff1b1ded2d261a17b7d2c1e4730529e80d18404d40c085d2d020",
    "build_request/reference.json": "0654e2384ebf821758a19de285f93835cd8671ec22c7d0e43f06a61e55478353",
    "confirm_design/calibration.json": "5ea6b080af5b98f76ee31f9b643e48c4b2f240cc22a293d633fc84e34b75797e",
    "confirm_design/case.yaml": "d927b9058811d5f15b1527bdc02317f051b9386454b5c69e3c0603bea11b643c",
    "confirm_design/payload.json": "ff4ddcc32df99616d17eb4b8b6067e45d5c28a2a7b997eff25ac2fe18b955bf8",
    "confirm_design/reference.json": "1122933fdd9c1de6730cc223afb2e2433707c44142f096292569142430a6b561",
    "discuss/calibration.json": "e01f882c09c3384f9b4565ab26cb72142cfe4a58e1e38eb38ff8f8fe93cfe55d",
    "discuss/case.yaml": "b9ad94d1a9ae20949f243b129567a851d2fee203060316c484e4da3b90fa11ad",
    "discuss/payload.json": "485ed0068396fba19c377fc90f079add1ef23b4c8811df1773e902ad99233777",
    "discuss/reference.json": "5ef4db19eed1ad91be6f450adf2ae4ec98b9718c6549508e32c24f5afcf83d1b",
    "edit_request/calibration.json": "fd4e02823ed246c61f282241df69db24d66d4d4a5bf55bfa7eb7b82fb96517e2",
    "edit_request/case.yaml": "9c7e0a4e6b67b67b46139d1780b4fd0b4fbeddafa574bae1a9c3720cf686c798",
    "edit_request/payload.json": "b6c0c8629eb88e01fed8d07b5baffe68670b5534da20390e36af3aff05db82af",
    "edit_request/reference.json": "0bc3d02b7cd26ed26aadabb564099fac6665e31d2be8ce7d4bae4b05f90d3112",
}
# #314 (Task 9): adding the insert cases leaves the four #313 cases byte-identical. Digests of the
# whole files at b2a97b42 (their payloads already carry the two SLIDE_KEYS).
CASES_313_SHA256 = {
    "edit_polite_ordinal/calibration.json":
        "eae629d3b5656fa0558bf5d53bdefe6067d854228a850a09cdebccff1343f665",
    "edit_polite_ordinal/case.yaml":
        "e6da3d33b85bdb0f1a0b0db0e46c43a0307de1e31703d8b6ec8874cbb1e381a9",
    "edit_polite_ordinal/payload.json":
        "a1950f828b06e4cee43dde042b6cd59787ba6ed6e82c9bfdcf14aad5604cd9fc",
    "edit_polite_ordinal/reference.json":
        "c31c6470837a8873d1d948da6696771b59a115ae9553b566db26490526bebd9d",
    "edit_last_slide/calibration.json":
        "25d28a8efb29e79a7fdc6bc5c9da0b550efd9536c92189eeff3578d33bc2baeb",
    "edit_last_slide/case.yaml":
        "90c4d073f77ddf57a48a675b324df49b9267e3a5fc7dc1c6846ee29535ed529f",
    "edit_last_slide/payload.json":
        "8f7767e74e9b8fa11f3e47b7e3ed3e0d4ab87ea1ca9616a4ead1640137aefc6a",
    "edit_last_slide/reference.json":
        "a5b1e6b88963c327c752695adcaec659997c56eb715470e6f1c3c7797b5bf1ef",
    "edit_multi_slide/calibration.json":
        "41e7e911ea6ce75d877101765159ae549bfef0519fe9586cb61e9ca6d1ddb5d9",
    "edit_multi_slide/case.yaml":
        "ee0327f615dc9e169c991a895dd105d3615242820da9d8929fe705587e76ef48",
    "edit_multi_slide/payload.json":
        "84f1e1d83d24e7463ec51c1e37d0fcf99a84df413c84ad7f3a5e400c6b147844",
    "edit_multi_slide/reference.json":
        "c2ce126b4eb79eaa12fb86da27e497c85b68cbaf7b25e0cdac2a5b85fa472abc",
    "discuss_slide_question/calibration.json":
        "cdac9441500d1e67de089a346f619ccf766f60438d722f5f71c2b9084f87b598",
    "discuss_slide_question/case.yaml":
        "50267a0a10f3e92e5963581b109d02ac7740bc3e1836778880beacd8bdf994ec",
    "discuss_slide_question/payload.json":
        "023577f9cb78f8102ececf08c7554393bf5999142fe62cbb4822c3b8d45690fa",
    "discuss_slide_question/reference.json":
        "374f8c4f8a8a3f7ccfb6d214b9c6f52d67d6f9d6481031d3f6ecd747b06d0c3d",
}
# #314 follow-up (Task 11): adding the blank cases rewrites none of the four insert cases. Digests
# of the whole files at ca7f9508 (unchanged at df1ec985).
INSERT_CASES_SHA256 = {
    "add_slide_anchor/calibration.json":
        "fd1b26f0c1249178a2325c5457eb2b3e92f4b8714e80be6e28415d45d857a8ef",
    "add_slide_anchor/case.yaml":
        "f4b06495679b5112d904f5cea3e7be730a3ebcff0cd0ecac02c8ad435e7d1359",
    "add_slide_anchor/payload.json":
        "db4c23f719e6afa88029c2d2cedf3449e2f71ce92e1cceb13acfacdf269c8e4e",
    "add_slide_anchor/reference.json":
        "55c9cb5683ee7cad3d931ea5968b82f21da34229788709b52823aa05616f3241",
    "add_slide_end/calibration.json":
        "41a6a5a7bf6a0874606cc187b1e5d6a76b32292118a6b9d68f8bda2ef8eb7454",
    "add_slide_end/case.yaml":
        "b58e0cb0a36a58e14bc484e6fcbc125ef185edd1c1d4f1cc6544d48d79ac9ffe",
    "add_slide_end/payload.json":
        "f3cf7e8992b095d10195bea420368da91d780c759b8e1ebd6310952fafdf2bcf",
    "add_slide_end/reference.json":
        "df8fad3750213b56033740fcf22654ff495109b5c1ffb7646ec21306b1f04ae8",
    "add_slide_as_number/calibration.json":
        "9686a0c05c25a313554dbf8eb1d390c3b2e6b581e44e45ba40710dc09b28d6d8",
    "add_slide_as_number/case.yaml":
        "2f9b2c0319000fdea1e82dd007c33e602eed6cee97d34b9f36ab63b67dd78604",
    "add_slide_as_number/payload.json":
        "0bd9b45da2a652b3863dfa6cd46ef4ade257f48cf5455ad0845ca25e0e5155d8",
    "add_slide_as_number/reference.json":
        "b3441b939e15a961720c5c49beb05e577dddea0b8456f44a11581c665db6bf24",
    "add_slide_and_revise/calibration.json":
        "d46f9a9fd9827e1950f9043b3f93befaa4aad90a96187d80641c16b38046adde",
    "add_slide_and_revise/case.yaml":
        "5786ff54caff1fd9a9c9f2411ea6848bb6085f504269494800ce1aa72232b538",
    "add_slide_and_revise/payload.json":
        "9fc7d624031c6be867922391fdd69a783632e3f8c7c81c12f3c421fa57aaf0ac",
    "add_slide_and_revise/reference.json":
        "f4e48d4176487df3e0063d7bb64630c596c97be952c7e606fa5abc37ba384af3",
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
# The production architect payload keys, in architect_node's order (src/services/graph/nodes.py).
PAYLOAD_KEYS = [
    "conversation", "message", "current_deck_spec", "committed_slide_count",
    "slide_numbering", "slide_references",
    "previous_deck_review", "available_design_contract", "template_sections",
    "resolved_style", "design_system_library",
]
# #313 (plan Task 7): the two keys src/domain/slide_numbering.architect_slide_payload builds.
SLIDE_KEYS = ("slide_numbering", "slide_references")
DECK_SLIDES = 6
# #313 (plan Task 7, Appendix H): every slide reference resolved in each case's message, pinned.
SLIDE_REFERENCES = {
    "build_request": [],
    "edit_request": [
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []},
    ],
    "ask_data": [],
    "confirm_design": [],
    "discuss": [],
    "edit_polite_ordinal": [
        {"text": "4th slide", "slide_numbers": [4], "positions": [3], "out_of_range": []},
    ],
    "edit_last_slide": [
        {"text": "final slide", "slide_numbers": [6], "positions": [5], "out_of_range": []},
    ],
    "edit_multi_slide": [
        {
            "text": "Slides 2 and 3", "slide_numbers": [2, 3], "positions": [1, 2],
            "out_of_range": [],
        },
    ],
    "discuss_slide_question": [
        {"text": "slide 2", "slide_numbers": [2], "positions": [1], "out_of_range": []},
    ],
    # #314 (Appendix H): references resolve in the CURRENT deck's numbering.
    "add_slide_anchor": [
        {"text": "slide 5", "slide_numbers": [5], "positions": [4], "out_of_range": []},
    ],
    "add_slide_end": [],
    "add_slide_as_number": [],  # an indefinite ordinal names no current slide
    "add_slide_and_revise": [
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []},
        {"text": "final slide", "slide_numbers": [6], "positions": [5], "out_of_range": []},
    ],
    # #314 follow-up: numbered over the blank deck, so the blank is slide 4 and gold slide 4 is 5.
    "fill_blank_slide": [
        {"text": "slide 4", "slide_numbers": [4], "positions": [3], "out_of_range": []},
    ],
    "edit_beside_blank": [
        {"text": "fifth slide", "slide_numbers": [5], "positions": [4], "out_of_range": []},
    ],
    # Edit operations: references name current slides (the one deleted, moved or replaced, and an
    # anchor), never the edited deck's numbers.
    "delete_slide": [
        {"text": "slide 4", "slide_numbers": [4], "positions": [3], "out_of_range": []},
    ],
    "move_slide": [
        {"text": "slide 5", "slide_numbers": [5], "positions": [4], "out_of_range": []},
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []},
    ],
    "replace_slide_expand": [
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []},
    ],
    "mixed_operations": [
        {"text": "slide 1", "slide_numbers": [1], "positions": [0], "out_of_range": []},
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []},
        {"text": "slide 2", "slide_numbers": [2], "positions": [1], "out_of_range": []},
    ],
}
LAYOUT = case.EVALS_DIR / "fixtures/meridian/bundle/templates/standard/index.html"

# ---- #314 (Appendix H): the insert cases' content, pinned literally ----
INSERT_MESSAGES = {
    "add_slide_anchor": (
        "Could you add a slide before slide 5 with a worked before-and-after prompt example?"
    ),
    "add_slide_end": "Add one more slide at the end with a glossary of the prompt terms",
    "add_slide_as_number": "Add a new fourth slide on common prompt anti-patterns",
    "add_slide_and_revise": (
        "Add a slide after slide 3 on versioning prompts, and add it to the checklist on the "
        "final slide"
    ),
}
INSERT_REFERENCE_MESSAGES = {
    "add_slide_anchor": (
        "I'll add a new slide 5 with a worked before-and-after prompt example, just before the "
        "workflow slide."
    ),
    "add_slide_end": "I'll add a glossary of the prompt terms as a new final slide, slide 7.",
    "add_slide_as_number": (
        "I'll add a new slide 4 on common prompt anti-patterns; the impact slide moves to slide 5."
    ),
    "add_slide_and_revise": (
        "I'll add slide 4 on versioning prompts after slide 3, and add versioning to the checklist "
        "on the final slide, now slide 7."
    ),
}
# The new slide's text fields, by the case and its FINAL position in the revised deck.
INSERTED_SLIDES = {
    "add_slide_anchor": {4: {
        "purpose": "Make the techniques concrete with one worked example",
        "content_brief": (
            "Two-column slide with an ad-hoc prompt on the left and its optimised version on the "
            "right, labelling where system-prompt framing, a few-shot example and a structured "
            "output format were applied"
        ),
        "assumes": (
            "Audience has seen the measured gains and wants to see what a better prompt looks like"
        ),
        "hands_off": "Applying the patterns to one real prompt is quick and visibly improves it",
    }},
    "add_slide_end": {6: {
        "purpose": "Appendix — a glossary of the prompt terms used in the deck",
        "content_brief": (
            "Two-column glossary defining system prompt, few-shot example, chain-of-thought, "
            "structured output, eval criteria and test suite in one line each"
        ),
        "assumes": "Audience has heard each term during the talk",
        "hands_off": "Everyone leaves with the same vocabulary for prompt work",
    }},
    "add_slide_as_number": {3: {
        "purpose": "Warn against the habits that undo prompt optimisation",
        "content_brief": (
            "Bullet slide listing four common prompt anti-patterns — vague instructions, "
            "contradictory constraints, examples that leak the answer, and unbounded output — "
            "each with a one-line fix"
        ),
        "assumes": "Audience knows the four core patterns from the previous slide",
        "hands_off": "Most bad outputs come from a handful of avoidable prompt habits",
    }},
    "add_slide_and_revise": {3: {
        "purpose": "Show how to keep prompts under version control",
        "content_brief": (
            "Bullet slide explaining that every prompt change gets a version, a change note and a "
            "link to its eval results, so a regression can be traced and rolled back"
        ),
        "assumes": "Audience knows the four core patterns and that prompts change often",
        "hands_off": "A versioned prompt can be compared, reviewed and rolled back like code",
    }},
}
# Every new slide carries no data and no slide type or template section (Appendix H).
NEW_SLIDE_DEFAULTS = {"data_references": [], "slide_type": None, "template_section_index": None}
# The one revision, by FINAL position: the gold brief with one substring replaced (gold 5 -> 6).
INSERT_REVISIONS = {
    "add_slide_and_revise": {6: (
        "five-item prompt optimisation checklist (define task scope, choose patterns, write eval "
        "criteria,",
        "six-item prompt optimisation checklist (define task scope, choose patterns, version every "
        "prompt, write eval criteria,",
    )},
}
# The judge-only should_fail's off-request new slide: only purpose and brief differ from the
# reference's new slide.
OFF_REQUEST_SLIDE = {
    "purpose": "Point the team at upcoming AI conferences",
    "content_brief": (
        "Bullet slide listing three upcoming AI conferences the team could attend, with dates and "
        "locations"
    ),
}

# ---- #314 follow-up (manual insert, plan Task 11): the blank-slide cases on deck 2, pinned ----
# The payload deck is the deck-2 gold spec with a manually inserted blank at BLANK_AT, exactly as
# production persists it (``spec_json_with_blank_entry``): gold positions 3..5 shift to 4..6.
BLANK_AT = 3
BLANK_DECK_SLIDES = DECK_SLIDES + 1
# The slide edit_beside_blank names: just after the blank (gold position 3, the impact stats).
BESIDE_POS = 4
BLANK_MESSAGES = {
    "fill_blank_slide": (
        "Please make slide 4 a quick guide to which of the four patterns fits which kind of task"
    ),
    "edit_beside_blank": "Can you add a one-line takeaway beneath the stats on the fifth slide?",
}
BLANK_REFERENCE_MESSAGES = {
    "fill_blank_slide": (
        "I'll make the blank slide 4 a quick guide to which pattern fits which kind of task."
    ),
    "edit_beside_blank": (
        "I'll add a one-line takeaway beneath the three stats on the fifth slide."
    ),
}
# fill_blank_slide's reference: the blank at BLANK_AT filled in place with these text fields.
FILLED_SLIDE = {
    "purpose": "Help the audience choose the right pattern for a task",
    "content_brief": (
        "Table mapping four common task types — extraction, classification, multi-step reasoning "
        "and open-ended writing — to the pattern that fits each best, with one line on why"
    ),
    "assumes": "Audience has just met the four core patterns",
    "hands_off": "Each kind of task has a pattern that fits it best",
}
# edit_beside_blank's one revision: BESIDE_POS's brief with this substring replaced.
BESIDE_REVISION = (
    "typical iteration cycles to production quality (3-5 rounds)",
    "typical iteration cycles to production quality (3-5 rounds), with a one-line takeaway "
    "beneath the stats: structured prompting pays for itself in fewer tokens and fewer rounds",
)
# edit_beside_blank's should_fail: the edit, plus the untouched blank filled with invented text.
INVENTED_FILL = {
    "purpose": "Bridge from the techniques to the evidence",
    "content_brief": (
        "Transition slide with one line asking whether the four patterns really pay off, setting "
        "up the numbers that follow"
    ),
    "assumes": "Audience has just met the four core patterns",
    "hands_off": "The patterns are only worth adopting if the gains are real",
}
COMMITTED = PACK_DIR / "cases_heldout"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module
CONFIRM_DESIGN_MESSAGE = "Can you re-theme this deck with the Acme design system instead?"
EDIT_POS = 2  # spec "Slide 3" = the four-patterns bullet slide


def _snapshot(root):
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module", autouse=True)
def generated(tmp_path_factory):
    """Generate the pack once into a tmp tree; tests read from it, never rewriting the committed tree."""
    global CASES
    from evals.packs.architect import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def _msg(cid):
    return _load(cid).payload["message"]


def test_exactly_the_pinned_cases():
    cases = case.load_cases(AGENT, root=CASES)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    assert sorted(d.name for d in CASES.iterdir() if d.is_dir()) == sorted(CASE_IDS)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    assert sorted(p.name for p in (CASES / cid).iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = _load(cid)
    assert c.design_system_active is True
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert list(c.payload) == PAYLOAD_KEYS  # the keys, in architect_node's order
    assert c.kind == ("mutation" if cid in MUTATIONS else "positive")
    assert (c.fault == "") == (c.kind == "positive")
    assert c.expect == EXPECT[cid]


def test_payload_keys_are_every_production_key():
    """An eval payload carries every key the architect model sees in production on
    its first call, no fewer.  ``rejected_edit`` is the retry call's alone (as the
    builder's ``corrective_instruction`` is), so no case carries it."""
    assert "rejected_edit" in MODEL_PAYLOAD_KEYS[AGENT]
    assert set(PAYLOAD_KEYS) == set(MODEL_PAYLOAD_KEYS[AGENT]) - {"rejected_edit"}
    assert len(PAYLOAD_KEYS) == len(set(PAYLOAD_KEYS)) == 11


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    p = _load(cid).payload
    gold = case.gold_deck_spec(DECK)
    assert isinstance(p["message"], str) and p["message"]
    assert p["previous_deck_review"] is None
    assert p["available_design_contract"] == {
        "design_system_id": 3, "template_id": 5, "slide_style_id": None,
    }
    assert p["resolved_style"] == case.meridian_resolved_style()
    assert p["template_sections"] == section_inventory(LAYOUT.read_text())
    assert len(p["template_sections"]) == 4
    if cid in HAS_DECK:
        DeckSpec.model_validate(p["current_deck_spec"])
        if cid in BLANK_CASES:
            # #314 follow-up: the gold deck plus the blank (test_blank_payload_splices_the_blank).
            assert p["current_deck_spec"] == _blank_deck(gold)
            assert p["committed_slide_count"] == BLANK_DECK_SLIDES == 7
        else:
            assert p["current_deck_spec"] == gold
            assert p["committed_slide_count"] == 6
        assert len(p["conversation"]) == 3
        assert p["conversation"][0]["role"] == "user"
        assert p["conversation"][1]["role"] == "assistant"
    else:
        assert p["current_deck_spec"] is None
        assert p["committed_slide_count"] == 0
        assert len(p["conversation"]) == 1
    assert isinstance(p["committed_slide_count"], int)
    for turn in p["conversation"]:
        assert set(turn) == {"role", "content"}
        assert isinstance(turn["content"], str) and turn["content"]
    assert p["conversation"][-1] == {"role": "user", "content": p["message"]}


@pytest.mark.parametrize("cid", sorted(HAS_DECK))
def test_prior_exchange_is_about_the_prompt_deck_and_not_the_train_text(cid):
    from evals.packs.architect import mutations

    conv = _load(cid).payload["conversation"]
    assert "prompt" in conv[0]["content"].lower()
    assert "prompt" in conv[1]["content"].lower()
    assert conv[0]["content"] != mutations.PRIOR_USER
    assert conv[1]["content"] != mutations.PRIOR_ASSISTANT


@pytest.mark.parametrize("cid", CASE_IDS)
def test_design_system_library(cid):
    lib = _load(cid).payload["design_system_library"]
    assert len(lib) == 2
    by_id = {s["design_system_id"]: s for s in lib}
    assert set(by_id) == {3, 4}
    for s in lib:
        assert {"design_system_id", "name", "description", "is_default", "templates"} <= set(s)
        for t in s["templates"]:
            assert {"template_id", "name", "description"} <= set(t)
    assert by_id[3]["name"] == "Meridian Test Design System"
    assert [t["template_id"] for t in by_id[3]["templates"]] == [5]
    assert by_id[3]["templates"][0]["name"] == "Meridian Standard"
    assert by_id[4]["name"] == "Acme Test Design System"
    assert [t["template_id"] for t in by_id[4]["templates"]] == [7]
    assert by_id[4]["templates"][0]["name"] == "Acme Standard"


def test_messages():
    assert _msg("edit_request") == "On slide 3, show the four patterns as four cards instead of a bullet list"
    assert _msg("confirm_design") == CONFIRM_DESIGN_MESSAGE
    assert "Acme" in CONFIRM_DESIGN_MESSAGE and "design system" in CONFIRM_DESIGN_MESSAGE
    b = _msg("build_request").lower()
    assert "prompt" in b and "optimi" in b
    assert "engineer" in b and "product" in b
    a = _msg("ask_data").lower()
    assert "success rate" in a and "model" in a and "quarter" in a
    assert not re.search(r"\d", a), "ask_data must supply no figures"
    d = _msg("discuss").lower()
    assert "few-shot" in d and "chain-of-thought" in d
    assert d.rstrip().endswith("?")
    assert _msg("edit_polite_ordinal") == (
        "Would you mind making the 4th slide lead with the 3-5 iteration rounds?"
    )
    assert _msg("edit_last_slide") == (
        "The final slide should open with the call to action, before the checklist"
    )
    assert _msg("edit_multi_slide") == "Slides 2 and 3 are too dense — drop the callouts on both"
    assert _msg("discuss_slide_question") == "Why does slide 2 come before the techniques?"
    # #314: the four insert messages, exactly.
    assert _msg("add_slide_anchor") == (
        "Could you add a slide before slide 5 with a worked before-and-after prompt example?"
    )
    assert _msg("add_slide_end") == (
        "Add one more slide at the end with a glossary of the prompt terms"
    )
    assert _msg("add_slide_as_number") == "Add a new fourth slide on common prompt anti-patterns"
    assert _msg("add_slide_and_revise") == (
        "Add a slide after slide 3 on versioning prompts, and add it to the checklist on the "
        "final slide"
    )
    assert {cid: _msg(cid) for cid in INSERT_CASES} == INSERT_MESSAGES
    # #314 follow-up: the two blank-slide messages, exactly.
    assert _msg("fill_blank_slide") == (
        "Please make slide 4 a quick guide to which of the four patterns fits which kind of task"
    )
    assert _msg("edit_beside_blank") == (
        "Can you add a one-line takeaway beneath the stats on the fifth slide?"
    )
    assert {cid: _msg(cid) for cid in BLANK_CASES} == BLANK_MESSAGES


@pytest.mark.parametrize("cid", NEW_CASE_IDS)
def test_new_cases_continue_the_existing_prior_exchange(cid):
    prior = _load("edit_request").payload["conversation"][:2]
    assert _load(cid).payload["conversation"][:2] == prior


def test_messages_differ_from_the_train_pack():
    from evals.packs.architect import mutations

    for cid in CASE_IDS:
        assert _msg(cid) != mutations.MESSAGES[cid], cid


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_validates_and_passes(cid):
    c = _load(cid)
    out = ArchitectOutput.model_validate(c.reference)
    assert out.intent == EXPECT[cid]["intent"]
    # #314: scored as the harness scores it, with the reference and the payload's current deck.
    ok, why = expected_category_score(
        AGENT, c.reference, c.expect,
        reference=c.reference, current_deck_spec=c.payload["current_deck_spec"],
    )
    assert ok, why


def test_build_reference_carries_the_deck2_spec():
    ref = _load("build_request").reference
    DeckSpec.model_validate(ref["deck_spec"])
    assert ref["deck_spec"] == case.gold_deck_spec(DECK)


def test_edit_reference_targets_one_zero_based_position():
    ref = _load("edit_request").reference
    assert ref["intent"] == "edit"
    assert ref["target_positions"] == [EDIT_POS]


def test_edit_slide_is_the_four_patterns_bullet_slide_in_deck2():
    brief = case.gold_deck_spec(DECK)["slides"][EDIT_POS]["content_brief"].lower()
    assert "bullet" in brief and "four" in brief


def test_edit_reference_revises_only_the_target_slide_brief():
    ref = _load("edit_request").reference
    DeckSpec.model_validate(ref["deck_spec"])
    gold = case.gold_deck_spec(DECK)
    spec = ref["deck_spec"]
    assert {k: v for k, v in spec.items() if k != "slides"} == {k: v for k, v in gold.items() if k != "slides"}
    assert len(spec["slides"]) == len(gold["slides"]) == 6
    for pos, (got, want) in enumerate(zip(spec["slides"], gold["slides"])):
        if pos != EDIT_POS:
            assert got == want, pos
    s, g = spec["slides"][EDIT_POS], gold["slides"][EDIT_POS]
    assert {k: v for k, v in s.items() if k != "content_brief"} == {k: v for k, v in g.items() if k != "content_brief"}
    brief = s["content_brief"].lower()
    assert brief != g["content_brief"].lower()
    assert "four cards" in brief or "4 cards" in brief
    assert "bullet slide" not in brief


# ---- #313: the edit references revise only their target slides ----

def _by_position(spec):
    return {s["position"]: s for s in spec["slides"]}


# #314: an insert reference changes the slide count, so it is checked by alignment instead
# (test_insert_references_are_unambiguous_to_production). A blank case's deck is not the gold
# (test_blank_references_align_to_production). An edit-operations reference has no deck_spec; it
# is composed by production's own semantics instead (test_eval_operations_scorer), and checked
# against the gold by test_operations_references_change_only_what_the_message_names.
@pytest.mark.parametrize(
    "cid",
    [c for c in EDIT_CASES
     if c not in INSERT_CASES and c not in BLANK_CASES and c not in OPERATIONS_CASES],
)
def test_edit_references_revise_only_their_targets(cid):
    ref = _load(cid).reference
    assert ref["intent"] == "edit"
    targets = EXPECT[cid]["positions"]
    assert sorted(ref["target_positions"]) == targets
    spec = ref["deck_spec"]
    DeckSpec.model_validate(spec)
    gold = case.gold_deck_spec(DECK)
    # Deck-level fields are the gold's ...
    assert {k: v for k, v in spec.items() if k != "slides"} == {k: v for k, v in gold.items() if k != "slides"}
    assert [s["position"] for s in spec["slides"]] == [s["position"] for s in gold["slides"]]
    got, want = _by_position(spec), _by_position(gold)
    for pos in want:
        if pos not in targets:
            assert got[pos] == want[pos], pos  # ... and so is every non-target slide.
            continue
        changed = {k for k in want[pos] if got[pos].get(k) != want[pos][k]} | (set(got[pos]) - set(want[pos]))
        # No held-out target slide's purpose changes (Appendix H): only the brief is revised.
        assert changed == {"content_brief"}, (pos, changed)
    if cid == "edit_request":
        brief = got[EDIT_POS]["content_brief"].lower()
        assert "four cards" in brief or "4 cards" in brief
    elif cid == "edit_polite_ordinal":
        brief = got[3]["content_brief"]
        assert "headline stat" in brief
        assert "leads with typical iteration cycles" in brief
    elif cid == "edit_last_slide":
        brief = got[5]["content_brief"]
        assert "opens with the call to action" in brief
        assert "five-item" in brief
    elif cid == "edit_multi_slide":
        for pos in (1, 2):
            assert got[pos]["content_brief"].endswith("with no callout"), pos
    else:
        pytest.fail(f"no brief markers pinned for {cid}")


def test_new_cases_are_fair_on_the_gold():
    """Each #313 request asks for a real change to what the deck-2 gold slide actually holds."""
    slides = _by_position(case.gold_deck_spec(DECK))
    assert max(slides) == 5 and len(slides) == 6  # "the final slide" is position 5
    # The stat the request names is not already first on the 4th slide.
    stats = slides[3]["content_brief"]
    assert stats.index("iteration cycles") > stats.index("token cost reduction")
    # The final slide puts the checklist before the call to action.
    closing = slides[5]["content_brief"]
    assert closing.index("five-item") < closing.index("call to action")
    assert "callout" in slides[1]["content_brief"]
    assert "callout" in slides[2]["content_brief"]
    assert "techniques" in slides[2]["purpose"]


# ---- #313 (plan Task 7): the payload carries the production slide numbering and references ----

@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_numbering_is_the_deck(cid):
    numbering = _load(cid).payload["slide_numbering"]
    if cid in HAS_DECK:
        # #314 follow-up: the numbering counts the blank (production numbers the rows).
        count = BLANK_DECK_SLIDES if cid in BLANK_CASES else DECK_SLIDES
        want = [{"slide_number": n, "position": n - 1} for n in range(1, count + 1)]
        assert numbering == want
    else:
        assert numbering == []


@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_references_are_pinned(cid):
    assert _load(cid).payload["slide_references"] == SLIDE_REFERENCES[cid]


# #314: an insert's references name current slides, not its new positions (test_insert_anchors).
# So do an edit-operations case's: a deleted or moved slide, an anchor, a replaced slide
# (test_slide_references_are_pinned), while its positions are the edited deck's rebuild set.
@pytest.mark.parametrize(
    "cid", [c for c in EDIT_CASES if c not in INSERT_CASES and c not in OPERATIONS_CASES]
)
def test_resolved_references_equal_the_expected_edit_positions(cid):
    """A2's deterministic proof on the eval messages: the resolver yields every expected target."""
    c = _load(cid)
    references = c.payload["slide_references"]
    assert sorted({p for r in references for p in r["positions"]}) == c.expect["positions"]
    assert all(r["out_of_range"] == [] for r in references)


@pytest.mark.parametrize("cid", OPERATIONS_CASES)
def test_operations_references_change_only_what_the_message_names(cid):
    """The two checks above, for a reference given as operations, which neither can read.

    The scorer compares a candidate's deck-level fields with the REFERENCE's, so a reference that
    also rewrote the deck (a narrative_arc after a delete, say) would pass itself and fail every
    correct answer. Only the gold catches that.
    """
    c = _load(cid)
    out = ArchitectOutput.model_validate(c.reference)
    gold = DeckSpec.model_validate(case.gold_deck_spec(DECK))
    result = apply_operations(gold.slides, out.operations)
    assert isinstance(result, OperationsResult), result
    composed = compose_edit_spec(gold, result, out.deck_changes)
    assert isinstance(composed, DeckSpec), composed
    # Deck-level fields are the gold's: none of these messages asks for a deck-level change.
    assert composed.model_dump(exclude={"slides"}) == gold.model_dump(exclude={"slides"})
    # Every slide an operation names, as its subject or its anchor, is one the message names.
    named = {p for r in c.payload["slide_references"] for p in r["positions"]}
    touched = {
        p for op in out.operations for p in (op.position, op.after_position)
        if p is not None and p >= 0
    }
    assert touched == named
    # An update revises its slide's brief and nothing else.
    by_position = {s.position: s.model_dump(exclude={"position"}) for s in gold.slides}
    for op in out.operations:
        if op.op == "update":
            new, old = op.slides[0].model_dump(), by_position[op.position]
            assert {k for k in new if new[k] != old[k]} == {"content_brief"}, op.position


def test_a_discuss_case_still_names_a_slide():
    """References are lexical, not intent: a question naming a slide resolves it, stays discuss."""
    c = _load("discuss_slide_question")
    references = c.payload["slide_references"]
    assert references and all(r["positions"] for r in references)
    assert c.expect == {"intent": "discuss"}
    assert c.reference["intent"] == "discuss" and c.reference["target_positions"] == []


@pytest.mark.parametrize("cid", CASE_IDS)
def test_committed_slide_keys_are_the_production_helper(cid):
    """Each committed payload's two #313 keys are what architect_node's helper builds from it."""
    p = case.load_case(AGENT, cid, root=COMMITTED).payload
    spec = p["current_deck_spec"]
    positions = [s["position"] for s in spec["slides"]] if spec else []
    assert {k: p[k] for k in SLIDE_KEYS} == architect_slide_payload(
        p["conversation"], p["message"], positions
    )


def test_ask_data_reference_has_a_data_request():
    ref = _load("ask_data").reference
    assert DataRequest.model_validate(ref["data_request"]).metric
    assert not ref.get("deck_spec")


def test_confirm_design_reference_proposes_acme_without_a_deck_spec():
    ref = _load("confirm_design").reference
    assert ref["proposed_design_contract"]["design_system_id"] == 4
    assert ref["proposed_design_contract"]["template_id"] == 7
    assert ref["deck_spec"] is None


def test_confirm_design_reference_warns_every_slide_is_rebuilt():
    msg = _load("confirm_design").reference["message"].lower()
    assert "every slide" in msg and "rebuilt" in msg


@pytest.mark.parametrize("cid", ["discuss", "discuss_slide_question"])
def test_discuss_reference_has_no_payload(cid):
    ref = _load(cid).reference
    assert ref["intent"] == "discuss"
    assert not ref.get("deck_spec")
    assert not ref.get("data_request")
    assert not ref.get("target_positions")
    assert not ref.get("proposed_design_contract")


def test_slide_question_reference_answers_about_the_named_slide():
    # The message speaks 1-indexed (architect.py SLIDE NUMBERS): slide 2 is deck-2 position 1.
    msg = _load("discuss_slide_question").reference["message"]
    assert "Slide 2" in msg
    assert "techniques" in msg


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_wrong_and_valid(cid):
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    ArchitectOutput.model_validate(bad)
    assert bad != c.reference
    # #314: both kwargs, so an insert case is scored with production semantics, not vacuously.
    ok, why = expected_category_score(
        AGENT, bad, c.expect,
        reference=c.reference, current_deck_spec=c.payload["current_deck_spec"],
    )
    if cid in JUDGE_ONLY_CALIBRATION:
        # Right place and right targets: only the judge can see the new slide is off-request.
        assert ok, f"judge-only should_fail must pass the deterministic scorer: {why}"
    else:
        assert not ok, f"calibration should_fail unexpectedly passes: {why}"


# #314 follow-up: a blank case's should_fail is an edit too (test_blank_calibration_is_pinned).
# So is an edit-operations case's: a wrong plan for the same edit (test_eval_operations_scorer).
@pytest.mark.parametrize(
    "cid",
    [c for c in CASE_IDS
     if c not in ("edit_request", *SLIPPED, *INSERT_CASES, *BLANK_CASES, *OPERATIONS_CASES)],
)
def test_calibration_has_the_wrong_intent(cid):
    assert _cal(cid)["should_fail"]["intent"] != EXPECT[cid]["intent"]


def test_polite_ordinal_calibration_asks_instead_of_acting():
    bad = _cal("edit_polite_ordinal")["should_fail"]
    assert bad["intent"] == "discuss"
    assert bad["deck_spec"] is None
    assert bad["target_positions"] == []
    assert bad["data_request"] is None and bad["proposed_design_contract"] is None


def test_slide_question_calibration_acts_instead_of_answering():
    bad = _cal("discuss_slide_question")["should_fail"]
    assert bad["intent"] == "edit"
    assert bad["target_positions"] == [1]
    assert bad["deck_spec"] is None


@pytest.mark.parametrize("cid", SLIPPED)
def test_slipped_calibrations(cid):
    """The realistic wrong answer to a position case: the reference with every target slipped by +1."""
    ref = _load(cid).reference
    bad = _cal(cid)["should_fail"]
    targets = ref["target_positions"]
    assert sorted(targets) == EXPECT[cid]["positions"]
    assert bad["target_positions"] == [p + 1 for p in targets]
    assert {k: v for k, v in bad.items() if k != "target_positions"} == {
        k: v for k, v in ref.items() if k != "target_positions"
    }


def test_edit_calibration_is_the_one_based_off_by_one():
    bad = _cal("edit_request")["should_fail"]
    assert bad["intent"] == "edit"
    assert bad["target_positions"] == [EDIT_POS + 1]


def _serialised(obj) -> bytes:
    """``obj`` as the generator writes a case file (``mutations._dump``, reused by heldout.py)."""
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()


def _without_slide_keys(data: bytes) -> bytes:
    """A payload.json's bytes with the two #313 keys removed, re-serialised as the generator does.

    The file must already be in the generator's serialisation, so re-serialising cannot hide a
    formatting change; removing the keys then leaves every other key, value and order as written.
    """
    obj = json.loads(data)
    assert data == _serialised(obj), "payload.json is not in the generator's serialisation"
    return _serialised({k: v for k, v in obj.items() if k not in SLIDE_KEYS})


def test_existing_cases_are_byte_identical(generated):
    """D7, D11: the five existing cases are their 679d2f21 bytes.

    payload.json is compared with the two #313 keys stripped: it may differ only by those keys.
    """
    got = {
        path: hashlib.sha256(
            _without_slide_keys(data) if path.endswith("/payload.json") else data
        ).hexdigest()
        for path, data in generated.items()
        if path.split("/")[0] in EXISTING_CASE_IDS
    }
    assert got == EXISTING_CASE_SHA256


def test_the_313_cases_are_byte_identical(generated):
    """#314 (Task 9): adding the insert cases rewrites none of the four #313 case files."""
    got = {
        path: hashlib.sha256(data).hexdigest()
        for path, data in generated.items()
        if path.split("/")[0] in CASES_313
    }
    assert got == CASES_313_SHA256


def test_the_insert_cases_are_byte_identical(generated):
    """#314 follow-up (Task 11): adding the blank cases rewrites none of the four insert case files."""
    got = {
        path: hashlib.sha256(data).hexdigest()
        for path, data in generated.items()
        if path.split("/")[0] in INSERT_CASES
    }
    assert got == INSERT_CASES_SHA256


def test_generator_is_idempotent(generated):
    from evals.packs.architect import heldout

    before = dict(generated)
    heldout.generate(out_dir=CASES)
    assert _snapshot(CASES) == before


def test_default_output_is_the_heldout_tree_not_train():
    """generate() with no out_dir must write cases_heldout, never the train cases tree."""
    from evals.packs.architect import heldout, mutations

    assert heldout.CASES_DIR == case.cases_dir(AGENT, split="heldout") == COMMITTED
    assert heldout.CASES_DIR != mutations.CASES_DIR


def test_committed_cases_are_current():
    """Committed cases_heldout tree is byte-identical to a fresh tmp generation (read-only on it)."""
    committed = _snapshot(COMMITTED)
    fresh = _snapshot(CASES)
    missing = set(fresh) - set(committed)
    extra = set(committed) - set(fresh)
    assert not missing and not extra, (
        f"File set mismatch: not committed={sorted(missing)}, stale committed={sorted(extra)}"
    )
    differing = sorted(p for p in fresh if fresh[p] != committed[p])
    assert not differing, f"Committed files differ from generated state: {differing}"


# ---- #314 (Appendix H, D10, D11): the add-a-slide cases on deck 2 ----

def _without_position(slide):
    return {k: v for k, v in slide.items() if k != "position"}


def _deck_level(spec):
    return {k: v for k, v in spec.items() if k != "slides"}


def _new_slide(position, fields):
    return {"position": position, **fields, **NEW_SLIDE_DEFAULTS}


def _spliced(gold, inserts, revisions=None):
    """Oracle: ``gold`` with ``inserts`` (FINAL position -> text fields) spliced in, every slide
    re-stamped to its index, then ``revisions`` (FINAL position -> (old, new) brief substring)."""
    spec = copy.deepcopy(gold)
    slides = spec["slides"]
    assert [s["position"] for s in slides] == list(range(len(slides)))
    for final in sorted(inserts):
        slides.insert(final, _new_slide(final, inserts[final]))
    for index, slide in enumerate(slides):
        slide["position"] = index
    for final, (old, new) in (revisions or {}).items():
        assert slides[final]["content_brief"].count(old) == 1, final
        slides[final]["content_brief"] = slides[final]["content_brief"].replace(old, new)
    return spec


def _replaced(gold, slides):
    """Oracle: ``gold`` with the slides at ``slides`` (position -> text fields) replaced."""
    spec = copy.deepcopy(gold)
    for position, fields in slides.items():
        spec["slides"][position] = _new_slide(position, fields)
    return spec


def _expected_reference(cid):
    gold = case.gold_deck_spec(DECK)
    return {
        "intent": "edit",
        "message": INSERT_REFERENCE_MESSAGES[cid],
        "deck_spec": _spliced(gold, INSERTED_SLIDES[cid], INSERT_REVISIONS.get(cid)),
        "data_request": None,
        "target_positions": EXPECT[cid]["positions"],
        "proposed_design_contract": None,
    }


def _expected_should_fail(cid):
    """An insert should_fail is the reference with only its targets and deck_spec changed."""
    gold = case.gold_deck_spec(DECK)
    ref = _expected_reference(cid)
    if cid == "add_slide_anchor":  # right place and targets, off-request new slide (judge-only)
        (final, fields), = INSERTED_SLIDES[cid].items()
        return {**ref, "deck_spec": _spliced(gold, {final: {**fields, **OFF_REQUEST_SLIDE}})}
    if cid == "add_slide_end":  # the last slide replaced instead of a slide added
        (_, fields), = INSERTED_SLIDES[cid].items()
        last = DECK_SLIDES - 1
        return {**ref, "target_positions": [last], "deck_spec": _replaced(gold, {last: fields})}
    if cid == "add_slide_as_number":  # inserted one place late
        (final, fields), = INSERTED_SLIDES[cid].items()
        return {
            **ref, "target_positions": [final + 1],
            "deck_spec": _spliced(gold, {final + 1: fields}),
        }
    if cid == "add_slide_and_revise":  # added, but the requested revision forgotten
        return {
            **ref, "target_positions": EXPECT[cid]["inserted"],
            "deck_spec": _spliced(gold, INSERTED_SLIDES[cid]),
        }
    raise AssertionError(f"no should_fail pinned for {cid}")


@pytest.mark.parametrize("cid", INSERT_CASES)
def test_insert_reference_is_pinned(cid):
    """The whole reference: the deck-2 gold spec with the new slide spliced in and re-stamped,
    plus only the named revision; the deck-level fields untouched."""
    assert _load(cid).reference == _expected_reference(cid)


def test_insert_reference_pins_are_literal():
    """The oracle's targets and final positions, written out (so the oracle cannot drift)."""
    ref = {cid: _expected_reference(cid) for cid in INSERT_CASES}
    assert {cid: r["target_positions"] for cid, r in ref.items()} == {
        "add_slide_anchor": [4], "add_slide_end": [6],
        "add_slide_as_number": [3], "add_slide_and_revise": [3, 6],
    }
    assert {cid: len(r["deck_spec"]["slides"]) for cid, r in ref.items()} == dict.fromkeys(
        INSERT_CASES, 7
    )
    assert {cid: sorted(INSERTED_SLIDES[cid]) for cid in INSERT_CASES} == {
        cid: EXPECT[cid]["inserted"] for cid in INSERT_CASES
    }


@pytest.mark.parametrize("cid", INSERT_CASES)
def test_insert_calibration_is_pinned(cid):
    bad = _cal(cid)["should_fail"]
    ArchitectOutput.model_validate(bad)
    assert bad == _expected_should_fail(cid)


def test_insert_calibration_pins_are_literal():
    bad = {cid: _expected_should_fail(cid) for cid in INSERT_CASES}
    assert {cid: b["target_positions"] for cid, b in bad.items()} == {
        "add_slide_anchor": [4], "add_slide_end": [5],
        "add_slide_as_number": [4], "add_slide_and_revise": [3],
    }
    assert {cid: len(b["deck_spec"]["slides"]) for cid, b in bad.items()} == {
        "add_slide_anchor": 7, "add_slide_end": 6,
        "add_slide_as_number": 7, "add_slide_and_revise": 7,
    }
    assert bad["add_slide_end"]["deck_spec"]["slides"][5]["purpose"].startswith("Appendix")
    assert bad["add_slide_as_number"]["deck_spec"]["slides"][4]["purpose"] == (
        INSERTED_SLIDES["add_slide_as_number"][3]["purpose"]
    )


@pytest.mark.parametrize("cid", INSERT_CASES)
def test_insert_references_are_unambiguous_to_production(cid):
    """D10: production's own alignment reads each reference as exactly the expected insert.

    ``align_slides`` (the function architect_node and the scorer call) gives the expected new
    slides and revisions; every current slide keeps its order and shifts past the new one, and
    every slide outside ``positions`` is its gold slide ignoring position.
    """
    c = _load(cid)
    gold = case.gold_deck_spec(DECK)
    spec = c.reference["deck_spec"]
    inserted, positions = c.expect["inserted"], c.expect["positions"]
    alignment = align_slides(
        DeckSpec.model_validate(gold).slides, DeckSpec.model_validate(spec).slides
    )
    assert list(alignment.inserted_indices) == inserted
    assert list(alignment.revised_indices) == sorted(set(positions) - set(inserted))
    # Positions are re-stamped: the spec's own numbering is the canonical one.
    assert [s["position"] for s in spec["slides"]] == list(
        range(len(gold["slides"]) + len(inserted))
    )
    assert list(alignment.inserted) == inserted
    kept = [j for j in range(len(spec["slides"])) if j not in inserted]
    assert dict(alignment.old_to_new_index) == dict(enumerate(kept))
    for old, new in alignment.old_to_new_index.items():
        if new not in positions:
            assert _without_position(spec["slides"][new]) == _without_position(
                gold["slides"][old]
            ), (old, new)
    assert _deck_level(spec) == _deck_level(gold)


# Which production check each non-judge-only insert should_fail trips (D10's fail rationales).
INSERT_CALIBRATION_TRAP = {
    "add_slide_end": "inserted",
    "add_slide_as_number": "inserted",
    "add_slide_and_revise": "revised",
}


@pytest.mark.parametrize("cid", INSERT_CASES)
def test_insert_calibration_fails_production_scoring_on_its_trap(cid):
    """Each should_fail is a spec production would apply; it fails on its planted trap only."""
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    gold = DeckSpec.model_validate(case.gold_deck_spec(DECK))
    align_slides(gold.slides, DeckSpec.model_validate(bad["deck_spec"]).slides)  # not refused
    ok, why = expected_category_score(
        AGENT, bad, c.expect,
        reference=c.reference, current_deck_spec=c.payload["current_deck_spec"],
    )
    if cid in JUDGE_ONLY_CALIBRATION:
        assert ok, why
        return
    assert not ok, why
    assert why.startswith("Insert: "), why
    assert INSERT_CALIBRATION_TRAP[cid] in why, why


def _resolved_positions(cid):
    return [p for r in _load(cid).payload["slide_references"] for p in r["positions"]]


def test_insert_anchors():
    """The resolved references name CURRENT slides; each case's insert follows from them."""
    ins = {cid: _load(cid).expect["inserted"] for cid in INSERT_CASES}
    last_old = DECK_SLIDES - 1
    # "before slide N": the new slide takes the named slide's position.
    assert _resolved_positions("add_slide_anchor") == ins["add_slide_anchor"]
    # An indefinite ordinal and an append name no current slide.
    assert _resolved_positions("add_slide_as_number") == []
    assert _resolved_positions("add_slide_end") == []
    assert ins["add_slide_end"] == [DECK_SLIDES]
    # The anchor, then the last current slide, which the insert shifts by one.
    assert _resolved_positions("add_slide_and_revise") == [
        ins["add_slide_and_revise"][0] - 1, last_old,
    ]
    assert EXPECT["add_slide_and_revise"]["positions"] == ins["add_slide_and_revise"] + [
        last_old + 1
    ]


def _ref_slide(cid, position):
    return _load(cid).reference["deck_spec"]["slides"][position]


def test_insert_markers():
    # C18: the plan's first anchor substring appears only in the message, so only the second is
    # a brief marker.
    assert "optimised version" in _ref_slide("add_slide_anchor", 4)["content_brief"]
    off_request = _cal("add_slide_anchor")["should_fail"]["deck_spec"]["slides"][4]["content_brief"]
    assert "conferences" in off_request and "prompt" not in off_request.lower(), off_request
    assert _ref_slide("add_slide_end", 6)["purpose"].startswith("Appendix")
    anti = _ref_slide("add_slide_as_number", 3)["content_brief"]
    assert "four common prompt anti-patterns" in anti
    checklist = _ref_slide("add_slide_and_revise", 6)["content_brief"]
    assert "six-item" in checklist and "version every prompt" in checklist


def test_insert_cases_are_fair_on_the_gold():
    """Each #314 request asks for a slide the deck-2 gold does not already hold."""
    gold = case.gold_deck_spec(DECK)
    slides = _by_position(gold)
    assert slides[4]["purpose"].startswith("Provide the workflow")  # the slide the anchor precedes
    assert "five-item" in slides[5]["content_brief"]
    for slide in gold["slides"]:
        purpose = slide["purpose"].lower()
        assert not any(
            word in purpose for word in ("glossary", "anti-pattern", "version", "conference")
        ), purpose
    assert "techniques" in slides[2]["purpose"]


@pytest.mark.parametrize("cid", INSERT_CASES)
def test_insert_faults_name_the_trap(cid):
    c = _load(cid)
    for position in c.expect["inserted"]:
        assert f"position {position}" in c.fault, c.fault


# ---- #314 follow-up (manual insert, plan Task 11, D5): the blank-slide cases on deck 2 ----

def _restamped(spec):
    for index, slide in enumerate(spec["slides"]):
        slide["position"] = index
    return spec


def _blank_deck(gold):
    """Oracle: ``gold`` with a blank entry spliced in at BLANK_AT, every slide re-stamped.

    Written out by hand, so it is independent of the production splice it is checked against
    (test_blank_payload_splices_the_blank).
    """
    spec = copy.deepcopy(gold)
    assert [s["position"] for s in spec["slides"]] == list(range(len(spec["slides"])))
    spec["slides"].insert(BLANK_AT, {
        "purpose": "", "content_brief": "", "assumes": "", "hands_off": "", "data_references": [],
    })
    return _restamped(spec)


def _expected_blank_reference(cid):
    """fill: the blank filled in place. beside: only BESIDE_POS's brief revised, blank untouched."""
    deck = _blank_deck(case.gold_deck_spec(DECK))
    if cid == "fill_blank_slide":
        deck["slides"][BLANK_AT] = _new_slide(BLANK_AT, FILLED_SLIDE)
    elif cid == "edit_beside_blank":
        old, new = BESIDE_REVISION
        slide = deck["slides"][BESIDE_POS]
        assert slide["content_brief"].count(old) == 1
        slide["content_brief"] = slide["content_brief"].replace(old, new)
    else:
        raise AssertionError(f"no reference pinned for {cid}")
    return {
        "intent": "edit",
        "message": BLANK_REFERENCE_MESSAGES[cid],
        "deck_spec": deck,
        "data_request": None,
        "target_positions": EXPECT[cid]["positions"],
        "proposed_design_contract": None,
    }


def _expected_blank_should_fail(cid):
    ref = _expected_blank_reference(cid)
    if cid == "fill_blank_slide":
        # The named number read as "a new slide 4": the slide is inserted at BLANK_AT and the
        # blank, left blank, shifts to BLANK_AT + 1. Same message and targets as the reference.
        deck = _blank_deck(case.gold_deck_spec(DECK))
        deck["slides"].insert(BLANK_AT, _new_slide(BLANK_AT, FILLED_SLIDE))
        return {**ref, "deck_spec": _restamped(deck)}
    if cid == "edit_beside_blank":
        # The requested edit, plus the untouched blank filled with invented text.
        deck = copy.deepcopy(ref["deck_spec"])
        deck["slides"][BLANK_AT] = _new_slide(BLANK_AT, INVENTED_FILL)
        return {**ref, "target_positions": [BLANK_AT, BESIDE_POS], "deck_spec": deck}
    raise AssertionError(f"no should_fail pinned for {cid}")


@pytest.mark.parametrize("cid", BLANK_CASES)
def test_blank_payload_splices_the_blank(cid):
    """The payload is what architect_node sends after a manual insert at BLANK_AT: the persisted
    spec with production's blank entry spliced in, a committed count and numbering that count it."""
    p = _load(cid).payload
    gold = case.gold_deck_spec(DECK)
    spec = p["current_deck_spec"]
    DeckSpec.model_validate(spec)
    assert spec == _blank_deck(gold)
    # Production's own manual-insert splice of the persisted spec column.
    assert spec == json.loads(spec_json_with_blank_entry(json.dumps(gold), BLANK_AT))
    assert spec["slides"][BLANK_AT] == {**BLANK_DECK_SPEC_ENTRY, "position": BLANK_AT}
    assert [i for i, s in enumerate(spec["slides"]) if is_blank_slide_spec(s)] == [BLANK_AT]
    assert [s["position"] for s in spec["slides"]] == list(range(BLANK_DECK_SLIDES))
    assert _deck_level(spec) == _deck_level(gold)
    # One committed row per spec entry, the blank's row included (production rejects a mismatch).
    assert p["committed_slide_count"] == len(spec["slides"]) == DECK_SLIDES + 1
    numbering = p["slide_numbering"]
    assert len(numbering) == BLANK_DECK_SLIDES
    assert numbering[BLANK_AT] == {"slide_number": BLANK_AT + 1, "position": BLANK_AT}
    assert p["conversation"][:2] == _load("edit_request").payload["conversation"][:2]


def test_blank_slide_numbers_name_the_blank_and_its_neighbour():
    """The user names the blank by its slide number; edit_beside_blank names the slide after it,
    whose number counts the blank (gold slide 4 is now slide 5)."""
    assert _resolved_positions("fill_blank_slide") == [BLANK_AT] == EXPECT["fill_blank_slide"][
        "positions"
    ]
    assert _resolved_positions("edit_beside_blank") == [BESIDE_POS] == EXPECT[
        "edit_beside_blank"
    ]["positions"]
    assert BESIDE_POS == BLANK_AT + 1
    gold = case.gold_deck_spec(DECK)
    payload_deck = _load("edit_beside_blank").payload["current_deck_spec"]
    assert _without_position(payload_deck["slides"][BESIDE_POS]) == _without_position(
        gold["slides"][BESIDE_POS - 1]
    )


@pytest.mark.parametrize("cid", BLANK_CASES)
def test_blank_reference_is_pinned(cid):
    """The whole reference: the blank deck with only the requested slide changed."""
    assert _load(cid).reference == _expected_blank_reference(cid)


@pytest.mark.parametrize("cid", BLANK_CASES)
def test_blank_calibration_is_pinned(cid):
    bad = _cal(cid)["should_fail"]
    ArchitectOutput.model_validate(bad)
    assert bad == _expected_blank_should_fail(cid)


def test_blank_pins_are_literal():
    """The oracles' targets, lengths and where the blank ends up, written out."""
    ref = {cid: _expected_blank_reference(cid) for cid in BLANK_CASES}
    bad = {cid: _expected_blank_should_fail(cid) for cid in BLANK_CASES}
    assert {cid: r["target_positions"] for cid, r in ref.items()} == {
        "fill_blank_slide": [3], "edit_beside_blank": [4],
    }
    assert {cid: b["target_positions"] for cid, b in bad.items()} == {
        "fill_blank_slide": [3], "edit_beside_blank": [3, 4],
    }
    assert {cid: len(r["deck_spec"]["slides"]) for cid, r in ref.items()} == dict.fromkeys(
        BLANK_CASES, 7
    )
    assert {cid: len(b["deck_spec"]["slides"]) for cid, b in bad.items()} == {
        "fill_blank_slide": 8, "edit_beside_blank": 7,
    }

    def blanks(spec):
        return [i for i, s in enumerate(spec["slides"]) if is_blank_slide_spec(s)]

    assert blanks(ref["fill_blank_slide"]["deck_spec"]) == []
    assert blanks(ref["edit_beside_blank"]["deck_spec"]) == [3]
    assert blanks(bad["fill_blank_slide"]["deck_spec"]) == [4]  # left blank, one place later
    assert blanks(bad["edit_beside_blank"]["deck_spec"]) == []  # the blank filled too


@pytest.mark.parametrize("cid", BLANK_CASES)
def test_blank_references_align_to_production(cid):
    """D10: production's alignment of the payload deck to the reference is an equal-length edit
    that revises exactly ``positions``; every other slide, the blank included unless filled, is
    the payload's slide unchanged."""
    c = _load(cid)
    current = c.payload["current_deck_spec"]
    spec = c.reference["deck_spec"]
    positions = c.expect["positions"]
    assert c.expect["inserted"] == []
    alignment = align_slides(
        DeckSpec.model_validate(current).slides, DeckSpec.model_validate(spec).slides
    )
    assert list(alignment.inserted_indices) == []
    assert list(alignment.revised_indices) == positions
    assert dict(alignment.old_to_new_index) == {i: i for i in range(BLANK_DECK_SLIDES)}
    for index, slide in enumerate(spec["slides"]):
        if index not in positions:
            assert slide == current["slides"][index], index
    assert _deck_level(spec) == _deck_level(current)
    filled = not is_blank_slide_spec(spec["slides"][BLANK_AT])
    assert filled == (cid == "fill_blank_slide")


# Which production check each blank should_fail trips (D10's fail rationales).
BLANK_CALIBRATION_TRAP = {
    "fill_blank_slide": "inserted [3] != []",
    "edit_beside_blank": "revised [3, 4] != [4]",
}


@pytest.mark.parametrize("cid", BLANK_CASES)
def test_blank_calibration_fails_production_scoring_on_its_trap(cid):
    """Each should_fail is a spec production would apply; it fails on its planted trap only."""
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    current = DeckSpec.model_validate(c.payload["current_deck_spec"])
    alignment = align_slides(current.slides, DeckSpec.model_validate(bad["deck_spec"]).slides)
    if cid == "fill_blank_slide":
        assert list(alignment.inserted_indices) == [BLANK_AT]
        assert list(alignment.revised_indices) == []
    else:
        assert list(alignment.inserted_indices) == []
        assert list(alignment.revised_indices) == [BLANK_AT, BESIDE_POS]
    ok, why = expected_category_score(
        AGENT, bad, c.expect,
        reference=c.reference, current_deck_spec=c.payload["current_deck_spec"],
    )
    assert not ok, why
    assert why.startswith("Insert: "), why
    assert BLANK_CALIBRATION_TRAP[cid] in why, why


@pytest.mark.parametrize("cid", BLANK_CASES)
def test_blank_faults_name_the_trap(cid):
    c = _load(cid)
    assert "blank" in c.fault, c.fault
    assert f"position {BLANK_AT}" in c.fault, c.fault
    if cid == "edit_beside_blank":
        assert f"position {BESIDE_POS}" in c.fault, c.fault


def test_blank_markers():
    filled = _ref_slide("fill_blank_slide", BLANK_AT)
    assert "task types" in filled["content_brief"], filled
    stats = _ref_slide("edit_beside_blank", BESIDE_POS)["content_brief"]
    assert "one-line takeaway" in stats and stats.startswith("Three-stat card slide"), stats
    invented = _cal("edit_beside_blank")["should_fail"]["deck_spec"]["slides"][BLANK_AT]
    assert invented["purpose"].startswith("Bridge") and not is_blank_slide_spec(invented)


def test_blank_cases_are_fair_on_the_gold():
    """The fill asks for a slide deck 2 does not hold; the edit asks for a real change."""
    gold = case.gold_deck_spec(DECK)
    slides = _by_position(gold)
    assert not any(is_blank_slide_spec(s) for s in gold["slides"])
    # The blank sits between the techniques and the impact stats; the slide after it is the stats.
    assert "techniques" in slides[BLANK_AT - 1]["purpose"]
    assert slides[BESIDE_POS - 1]["content_brief"].startswith("Three-stat card slide")
    assert "takeaway" not in slides[BESIDE_POS - 1]["content_brief"]
    for slide in gold["slides"]:
        text = (slide["purpose"] + " " + slide["content_brief"]).lower()
        assert "task type" not in text and "which pattern" not in text, text
