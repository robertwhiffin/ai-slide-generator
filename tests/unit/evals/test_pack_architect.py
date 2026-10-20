"""Self-tests for the architect eval pack (Task 14). Behavioural; no model, no network."""
import copy
import hashlib
import json

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckSpec
from src.domain.skill_io import ArchitectOutput, DataRequest
from src.domain.slide_alignment import align_slides
from src.domain.slide_numbering import architect_slide_payload
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS
from src.services.template_sections import section_inventory

from evals.harness import case
from evals.harness.scorers import expected_category_score

AGENT = "architect"
EXISTING_CASE_IDS = ["build_request", "edit_request", "ask_data", "confirm_design", "discuss"]
# #313: intent and slide-reference cases on the existing deck (plan Task 3, D6).
CASES_313 = ["edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question"]
# #314: add-a-slide cases on the same deck (plan Task 9, D11). They are folded into NEW_CASE_IDS,
# so MUTATIONS, HAS_DECK, CASE_IDS and EDIT_CASES all carry them (C19).
INSERT_CASES = ["add_slide_anchor", "add_slide_end", "add_slide_as_number", "add_slide_and_revise"]
NEW_CASE_IDS = CASES_313 + INSERT_CASES
CASE_IDS = EXISTING_CASE_IDS + NEW_CASE_IDS
MUTATIONS = ["edit_request", "ask_data", "confirm_design"] + NEW_CASE_IDS
EXPECT = {
    "build_request": {"intent": "build"},
    "edit_request": {"intent": "edit", "positions": [1]},
    "ask_data": {"intent": "ask_data"},
    "confirm_design": {"intent": "confirm_design_contract"},
    "discuss": {"intent": "discuss"},
    "edit_polite_ordinal": {"intent": "edit", "positions": [1]},
    "edit_last_slide": {"intent": "edit", "positions": [9]},
    "edit_multi_slide": {"intent": "edit", "positions": [3, 4, 5]},
    "discuss_slide_question": {"intent": "discuss"},
    # #314: positions and inserted are in the revised deck's numbering (D10).
    "add_slide_anchor": {"intent": "edit", "positions": [3], "inserted": [3]},
    "add_slide_end": {"intent": "edit", "positions": [10], "inserted": [10]},
    "add_slide_as_number": {"intent": "edit", "positions": [1], "inserted": [1]},
    "add_slide_and_revise": {"intent": "edit", "positions": [8, 10], "inserted": [8]},
}
HAS_DECK = {"edit_request", "confirm_design", "discuss"} | set(NEW_CASE_IDS)
EDIT_CASES = [c for c in CASE_IDS if EXPECT[c]["intent"] == "edit"]
# #314 (D11, finding 11): this case's should_fail is right place and right targets with an
# off-request new slide. The deterministic scorer passes it; only the judge separates it.
JUDGE_ONLY_CALIBRATION = {"add_slide_anchor"}
# Position cases whose calibration is the reference with every target slipped by +1 (D7).
SLIPPED = ["edit_last_slide", "edit_multi_slide"]
# The only target slide whose purpose may change: gold position 9 promises "a visual scorecard",
# which the edit_last_slide request removes (plan Task 3, review finding 11).
PURPOSE_REVISED = {"edit_last_slide"}
# D7: adding the #313 cases leaves the five existing cases byte-identical. Digests of the files at
# 679d2f21. Task 7 adds the two SLIDE_KEYS to every payload.json on purpose and re-pins nothing: a
# payload.json digest is checked on that payload with the two keys stripped (D11).
EXISTING_CASE_SHA256 = {
    "ask_data/calibration.json": "afc2f75a4a409ec4c7a2f78d1bb339f86b5d3946797008c8b56c08b09b9a1c78",
    "ask_data/case.yaml": "80efe39fd29dc2e46a2501fe0f230fc6c5c9681765f568e63f92be260ab59acd",
    "ask_data/payload.json": "ba8993c02ad182acb917ccecc82d3bbf20a3c183d99cab3a824883e0845584d1",
    "ask_data/reference.json": "95270e20cae5e7089c1215b370f6f26764b5b275ed6f5f481b5b24310e37c0a9",
    "build_request/calibration.json": "cdb0f35e3df90091bdff95ab7abbac7648396d6cb2b3aaaa148a8c35b38a4f33",
    "build_request/case.yaml": "02e9256188dad0c24a724a740f8acfa2fe033d9ff87ba3bc8bd0c0a2af47eece",
    "build_request/payload.json": "0e1210dad0caa69bac998ec59105d979d8d5352329d307b53cc50fbea13b7aef",
    "build_request/reference.json": "7e69cb0dae5018a4eb1b24088ddbed3c7e26bfcc857bfeafc9fde30fe59185ce",
    "confirm_design/calibration.json": "5ea6b080af5b98f76ee31f9b643e48c4b2f240cc22a293d633fc84e34b75797e",
    "confirm_design/case.yaml": "d927b9058811d5f15b1527bdc02317f051b9386454b5c69e3c0603bea11b643c",
    "confirm_design/payload.json": "ffda58a3a9f8ab2dde7d1068d8706fb809b238bb07da80d1a87dc5746eb6af21",
    "confirm_design/reference.json": "0ed5a2c4df6fdf70d67b7b3b2001bab52554fb7eca391cd16c01e71ebe55a120",
    "discuss/calibration.json": "0bbd94ce62de1965d9f4398e8b92d8846d5f766a4faad5b3115deef104c95348",
    "discuss/case.yaml": "b9ad94d1a9ae20949f243b129567a851d2fee203060316c484e4da3b90fa11ad",
    "discuss/payload.json": "8fe5b05f9fd5530043cde5e463e05ae02e4b19ccabfd3ece42eadfa9205d2e13",
    "discuss/reference.json": "bc1efe1d49195d0639b4719e15630ef885dc3677410d86d1148d8174d55e66f3",
    "edit_request/calibration.json": "e82af2a41cb659149919a296a8353cf169baf89b438c2fc0f3c5debceb58dec5",
    "edit_request/case.yaml": "8bfcf57a048107ec813aa05ce492d90b0aa39778c123958d2872e4f94c58dc04",
    "edit_request/payload.json": "e565ae0c1f4423dcc9be92d89e587475ff44a85aa77d6a224acb914587e4b4fa",
    "edit_request/reference.json": "2c6efe6c3afedff97c8a786b84e996b2f131b7b4bbd612a521f57ec2edf789b0",
}
# #314 (Task 9): adding the insert cases leaves the four #313 cases byte-identical. Digests of the
# whole files at b2a97b42 (their payloads already carry the two SLIDE_KEYS).
CASES_313_SHA256 = {
    "edit_polite_ordinal/calibration.json":
        "11cbdc0e7f95f7d7aab629cd715c95780118cde9b5351576f25791ba52b108a6",
    "edit_polite_ordinal/case.yaml":
        "5de8ea556d580d7a8230b31121a21c929a00a5eb3dc87ebe562ffd5dbb9ed0c1",
    "edit_polite_ordinal/payload.json":
        "4a3a4f17caad936a33ad9bdcada633ebdc89ed30dab3c086614b48ee5b5b65ae",
    "edit_polite_ordinal/reference.json":
        "bef068c5d1fec38538ff50839ab6047648de3c61b428e7da050aeda3d70dc85b",
    "edit_last_slide/calibration.json":
        "ee4833085e7a5932b68413d240c30fce7c0046c56725b01d43469aa29ba758c5",
    "edit_last_slide/case.yaml":
        "9f68e3602ad7ab1e5125c7a24b9303f0d18d5fcd2dc990223e04976fcccbc69b",
    "edit_last_slide/payload.json":
        "c8ae93708c47a5b21cc66c0d2f0ea97dea089f6934ade6a0b3d93d7b7387ef09",
    "edit_last_slide/reference.json":
        "f7ca09156f482c70838f07408afa7e6a423bc56715117515ebad0d01bcf3525f",
    "edit_multi_slide/calibration.json":
        "722047fb255e335808ed0c929241d9b5f01ee0870e73eac9758f0bed0c51c111",
    "edit_multi_slide/case.yaml":
        "bec2d36c1b869543fba59dc336fbe32d816beae8b851e2af33f9cebb6a69a854",
    "edit_multi_slide/payload.json":
        "1856b10dacbd5c1abd0be2583f11cb68fc12c4c4a788cf8922dd41455f7e198b",
    "edit_multi_slide/reference.json":
        "5f1c583dcc6ceb7dbf30f87851327ddd95fa93622f8354cea8664d50d049fe6b",
    "discuss_slide_question/calibration.json":
        "dcae36cf30115f1ee0455232863ebcd592f143580e07e336caf8862a0bbe1bcb",
    "discuss_slide_question/case.yaml":
        "c0f2c482f70a10c57e93036a6968eba40eec0a9476d8e96db607d3d6804f01ce",
    "discuss_slide_question/payload.json":
        "de3aa9845c798f74094deb2e050cfa86b6ec37ad36af8a3953a1deb1d1e4da3b",
    "discuss_slide_question/reference.json":
        "35dac0f6db8bad7edd41da5cb296f917111bdf073cd8b20baa3c2dbd04130f50",
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
DECK_SLIDES = 10
# #313 (plan Task 7): every slide reference resolved in each case's message, pinned literally.
SLIDE_REFERENCES = {
    "build_request": [],
    "edit_request": [
        {"text": "slide 2", "slide_numbers": [2], "positions": [1], "out_of_range": []},
    ],
    "ask_data": [],
    "confirm_design": [],
    "discuss": [],
    "edit_polite_ordinal": [
        {"text": "second slide", "slide_numbers": [2], "positions": [1], "out_of_range": []},
    ],
    "edit_last_slide": [
        {"text": "last slide", "slide_numbers": [10], "positions": [9], "out_of_range": []},
    ],
    "edit_multi_slide": [
        {
            "text": "Slides 4-6", "slide_numbers": [4, 5, 6], "positions": [3, 4, 5],
            "out_of_range": [],
        },
    ],
    "discuss_slide_question": [
        {"text": "slide 7", "slide_numbers": [7], "positions": [6], "out_of_range": []},
    ],
    # #314: references resolve in the CURRENT deck's numbering, so an anchor names the slide the
    # new one follows, not the new slide's own position.
    "add_slide_anchor": [
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []},
    ],
    "add_slide_end": [],
    "add_slide_as_number": [
        {"text": "slide 2", "slide_numbers": [2], "positions": [1], "out_of_range": []},
    ],
    "add_slide_and_revise": [
        {"text": "slide 8", "slide_numbers": [8], "positions": [7], "out_of_range": []},
        {"text": "last slide", "slide_numbers": [10], "positions": [9], "out_of_range": []},
    ],
}
LAYOUT = case.EVALS_DIR / "fixtures/meridian/bundle/templates/standard/index.html"

# ---- #314 (plan Task 9): the insert cases' content, pinned literally ----
INSERT_MESSAGES = {
    "add_slide_anchor": (
        "Add a slide after slide 3 that compares Reveal.js, Slidev and Marp side by side"
    ),
    "add_slide_end": "Add a final slide that lists the sources behind the evidence",
    "add_slide_as_number": "Insert a new slide 2 with an agenda for the talk",
    "add_slide_and_revise": (
        "Add a slide after slide 8 on offline use and security, and add it to the summary on the "
        "last slide"
    ),
}
INSERT_REFERENCE_MESSAGES = {
    "add_slide_anchor": (
        "I'll add a new slide 4 comparing Reveal.js, Slidev and Marp side by side, straight after "
        "slide 3."
    ),
    "add_slide_end": "I'll add a final slide, slide 11, listing the sources behind the evidence.",
    "add_slide_as_number": (
        "I'll insert a new slide 2 with the agenda for the talk; the current slide 2 becomes "
        "slide 3."
    ),
    "add_slide_and_revise": (
        "I'll add slide 9 on offline use and security after slide 8, and add it to the summary on "
        "the last slide, now slide 11."
    ),
}
# The new slide's text fields, by the case and its FINAL position in the revised deck.
INSERTED_SLIDES = {
    "add_slide_anchor": {3: {
        "purpose": "Compare the leading HTML slide frameworks side by side",
        "content_brief": (
            "Comparison table of Reveal.js, Slidev and Marp across authoring format, "
            "interactivity, theming and export options, one column per framework"
        ),
        "assumes": "The audience has just met HTML slides and heard the leading frameworks named",
        "hands_off": "Whichever framework a team picks, the case for HTML slides holds",
    }},
    "add_slide_end": {10: {
        "purpose": "Appendix — the sources behind the evidence",
        "content_brief": (
            "Bulleted list of the sources behind the five evidence beats, one line per beat: "
            "responsiveness, typography, interactivity, accessibility and collaboration"
        ),
        "assumes": "The audience has heard the verdict and may want to check the evidence",
        "hands_off": "Every claim in the deck can be traced to a source",
    }},
    "add_slide_as_number": {1: {
        "purpose": "Set out the agenda for the talk",
        "content_brief": (
            "Agenda slide listing the five narrative beats in order: why the tool matters, "
            "PowerPoint's limits, the evidence for HTML slides, the objections, and the verdict"
        ),
        "assumes": "The audience has seen the title and knows the topic",
        "hands_off": "The talk moves from the problem, through the evidence, to a verdict",
    }},
    "add_slide_and_revise": {8: {
        "purpose": "Evidence beat 6 — Offline use and security",
        "content_brief": (
            "Show that HTML slides run offline as one self-contained file and can be served from "
            "an access-controlled internal site, with no macros or embedded executables, as three "
            "short bullets and a callout"
        ),
        "assumes": "The audience has seen the collaboration and distribution advantages",
        "hands_off": "HTML slides are safe to share and work without a network",
    }},
}
# Every new slide carries no data and no slide type or template section (plan Task 9).
NEW_SLIDE_DEFAULTS = {"data_references": [], "slide_type": None, "template_section_index": None}
# The one revision, by FINAL position: the gold brief with one substring replaced (gold 9 -> 10).
INSERT_REVISIONS = {
    "add_slide_and_revise": {10: (
        "five advantage dimensions — responsiveness, typography, interactivity, accessibility, "
        "collaboration —",
        "six advantage dimensions — responsiveness, typography, interactivity, accessibility, "
        "collaboration, and offline use and security —",
    )},
}
# The judge-only should_fail's off-request new slide: only purpose and brief differ from the
# reference's new slide.
OFF_REQUEST_SLIDE = {
    "purpose": "Recount the history of PowerPoint",
    "content_brief": (
        "Timeline of PowerPoint releases from 1987 to today, one milestone per version"
    ),
}
FRAMEWORKS = ("Reveal.js", "Slidev", "Marp")


COMMITTED = PACK_DIR / "cases"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module (I9)


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
    from evals.packs.architect import mutations

    CASES = tmp_path_factory.mktemp(AGENT) / "cases"
    mutations.generate(out_dir=CASES)
    return _snapshot(CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def test_exactly_the_pinned_cases():
    cases = case.load_cases(AGENT, root=CASES)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    dirs = sorted(d.name for d in CASES.iterdir() if d.is_dir())
    assert dirs == sorted(CASE_IDS)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    d = CASES / cid
    assert sorted(p.name for p in d.iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    assert c.design_system_active is True
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert list(c.payload) == PAYLOAD_KEYS  # the keys, in architect_node's order
    assert c.kind == ("mutation" if cid in MUTATIONS else "positive")
    assert (c.fault == "") == (c.kind == "positive")
    assert c.expect == EXPECT[cid]


def test_payload_keys_are_every_production_key():
    """An eval payload carries every key the architect model sees in production, no fewer."""
    assert set(PAYLOAD_KEYS) == set(MODEL_PAYLOAD_KEYS[AGENT])
    assert len(PAYLOAD_KEYS) == len(set(PAYLOAD_KEYS)) == 11


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    p = case.load_case(AGENT, cid, root=CASES).payload
    gold = case.gold_deck_spec()
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
        assert p["current_deck_spec"] == gold
        assert p["committed_slide_count"] == 10
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
    # Last turn is the current user message.
    assert p["conversation"][-1] == {"role": "user", "content": p["message"]}


@pytest.mark.parametrize("cid", CASE_IDS)
def test_design_system_library(cid):
    lib = case.load_case(AGENT, cid, root=CASES).payload["design_system_library"]
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
    def msg(cid):
        return case.load_case(AGENT, cid, root=CASES).payload["message"]

    assert msg("edit_request") == "On slide 2, replace the bullet list with three stat cards"
    assert msg("confirm_design") == "Switch this deck to the Acme design system"
    assert msg("discuss") == "What's the difference between Reveal.js and Slidev?"
    assert "Q3 revenue by region" in msg("ask_data") and "Q2" in msg("ask_data")
    b = msg("build_request").lower()
    assert "html" in b and "powerpoint" in b
    assert msg("edit_polite_ordinal") == "Could you make the second slide less wordy?"
    assert msg("edit_last_slide") == (
        "Simplify the last slide: drop the stat cards and keep just the verdict and the call to action"
    )
    assert msg("edit_multi_slide") == "Slides 4-6 are too text-heavy; cut the wording on each by about half"
    assert msg("discuss_slide_question") == "Why is the accessibility point on slide 7?"
    # #314: the four insert messages, exactly.
    assert msg("add_slide_anchor") == (
        "Add a slide after slide 3 that compares Reveal.js, Slidev and Marp side by side"
    )
    assert msg("add_slide_end") == "Add a final slide that lists the sources behind the evidence"
    assert msg("add_slide_as_number") == "Insert a new slide 2 with an agenda for the talk"
    assert msg("add_slide_and_revise") == (
        "Add a slide after slide 8 on offline use and security, and add it to the summary on the "
        "last slide"
    )
    assert {cid: msg(cid) for cid in INSERT_CASES} == INSERT_MESSAGES


@pytest.mark.parametrize("cid", NEW_CASE_IDS)
def test_new_cases_continue_the_existing_prior_exchange(cid):
    prior = case.load_case(AGENT, "edit_request", root=CASES).payload["conversation"][:2]
    conv = case.load_case(AGENT, cid, root=CASES).payload["conversation"]
    assert conv[:2] == prior


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_validates_and_passes(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    out = ArchitectOutput.model_validate(c.reference)
    assert out.intent == EXPECT[cid]["intent"]
    # #314: scored as the harness scores it, with the reference and the payload's current deck.
    ok, why = expected_category_score(
        AGENT, c.reference, c.expect,
        reference=c.reference, current_deck_spec=c.payload["current_deck_spec"],
    )
    assert ok, why


def test_build_reference_carries_the_gold_spec():
    ref = case.load_case(AGENT, "build_request", root=CASES).reference
    DeckSpec.model_validate(ref["deck_spec"])
    assert ref["deck_spec"] == case.gold_deck_spec()


def test_edit_reference_targets_one_zero_based_position():
    ref = case.load_case(AGENT, "edit_request", root=CASES).reference
    assert ref["target_positions"] == [1]


def test_ask_data_reference_has_a_data_request():
    ref = case.load_case(AGENT, "ask_data", root=CASES).reference
    assert DataRequest.model_validate(ref["data_request"]).metric
    assert not ref.get("deck_spec")


def test_confirm_design_reference_proposes_acme_without_a_deck_spec():
    ref = case.load_case(AGENT, "confirm_design", root=CASES).reference
    assert ref["proposed_design_contract"]["design_system_id"] == 4
    assert ref["proposed_design_contract"]["template_id"] == 7
    assert ref["deck_spec"] is None


@pytest.mark.parametrize("cid", ["discuss", "discuss_slide_question"])
def test_discuss_reference_has_no_payload(cid):
    ref = case.load_case(AGENT, cid, root=CASES).reference
    assert ref["intent"] == "discuss"
    assert not ref.get("deck_spec")
    assert not ref.get("data_request")
    assert not ref.get("target_positions")
    assert not ref.get("proposed_design_contract")


def test_slide_question_reference_answers_about_the_named_slide():
    # The message speaks 1-indexed (architect.py SLIDE NUMBERS): slide 7 is gold position 6.
    msg = case.load_case(AGENT, "discuss_slide_question", root=CASES).reference["message"]
    assert "Slide 7" in msg
    assert "accessib" in msg.lower()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_wrong_and_valid(cid):
    c = case.load_case(AGENT, cid, root=CASES)
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


@pytest.mark.parametrize(
    "cid", [c for c in CASE_IDS if c not in ("edit_request", *SLIPPED, *INSERT_CASES)]
)
def test_calibration_has_the_wrong_intent(cid):
    bad = _cal(cid)["should_fail"]
    assert bad["intent"] != EXPECT[cid]["intent"]


def test_polite_ordinal_calibration_asks_instead_of_acting():
    bad = _cal("edit_polite_ordinal")["should_fail"]
    assert bad["intent"] == "discuss"
    assert bad["deck_spec"] is None
    assert bad["target_positions"] == []
    assert bad["data_request"] is None and bad["proposed_design_contract"] is None


def test_slide_question_calibration_acts_instead_of_answering():
    bad = _cal("discuss_slide_question")["should_fail"]
    assert bad["intent"] == "edit"
    assert bad["target_positions"] == [6]
    assert bad["deck_spec"] is None


@pytest.mark.parametrize("cid", SLIPPED)
def test_slipped_calibrations(cid):
    """The realistic wrong answer to a position case: the reference with every target slipped by +1."""
    ref = case.load_case(AGENT, cid, root=CASES).reference
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
    assert set(bad["target_positions"]) == {2}


def _serialised(obj) -> bytes:
    """``obj`` as the generator writes a case file (``mutations._dump``)."""
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


def test_generator_is_idempotent(generated):
    from evals.packs.architect import mutations

    before = dict(generated)
    mutations.generate(out_dir=CASES)
    assert _snapshot(CASES) == before


def test_committed_cases_are_current():
    """The committed tree is byte-identical to a fresh generation (same file set, same bytes).

    Read-only on the committed tree: the fresh generation lives in the module's tmp tree.
    """
    committed = _snapshot(COMMITTED)
    fresh = _snapshot(CASES)
    missing = set(fresh) - set(committed)
    extra = set(committed) - set(fresh)
    assert not missing and not extra, (
        f"File set mismatch: not committed={sorted(missing)}, stale committed={sorted(extra)}"
    )
    differing = sorted(p for p in fresh if fresh[p] != committed[p])
    assert not differing, f"Committed files differ from generated state: {differing}"


def _prompt():
    return (PACK_DIR / "judge_prompt.md").read_text()


def test_judge_prompt_placeholders():
    text = _prompt()
    assert "{{ outputs }}" in text
    assert "{{ expectations }}" in text


def test_judge_prompt_verdict_before_rationale():
    text = _prompt()
    assert "FIRST" in text and text.index("FIRST") < text.index("rationale", text.index("FIRST"))


def test_judge_prompt_handles_build_and_other_intents():
    text = _prompt().lower()
    assert "build" in text
    for word in ("argument", "arc", "brief"):
        assert word in text
    assert "ballpark" in text or "similar number" in text or "comparable" in text
    assert "example" in text and "template" in text  # reference is an example, not a template
    assert "intent" in text and "consistent" in text
    for other in ("edit", "ask_data", "confirm_design_contract", "discuss"):
        assert other in text


def test_judge_prompt_does_not_require_a_planted_fault():
    text = _prompt().lower()
    assert "pass" in text and "fail" in text
    assert "no deck_spec" in text or "no payload" in text


def test_confirm_design_reference_warns_every_slide_is_rebuilt():
    # src/core/skills/architect.py: a design-contract proposal must "say plainly
    # that every slide will be rebuilt" — the known-good output must do so too.
    msg = case.load_case(AGENT, "confirm_design", root=CASES).reference["message"].lower()
    assert "every slide" in msg and "rebuilt" in msg


def test_edit_slide_is_a_bullet_list_in_the_gold():
    # The edit case is fair only if gold position 1 really is a bullet-list slide.
    assert '<ul class="bullets">' in case.gold_slide(1)
    assert "bullet" in case.gold_deck_spec()["slides"][1]["content_brief"].lower()


def test_judge_prompt_allows_a_revised_deck_spec_on_edit():
    # The builder sees only slide_spec, so an edit that revises the target brief
    # is the better answer; the judge must not fail it as a payload mismatch.
    text = _prompt().lower()
    edit_line = next(l for l in text.splitlines() if l.startswith("- edit:"))
    assert "deck_spec" in edit_line and "acceptable" in edit_line


def test_judge_prompt_fails_a_build_that_misses_the_request():
    text = _prompt().lower()
    build_line = next(l for l in text.splitlines() if l.startswith("- build:"))
    assert "purpose" in build_line and "argument" in build_line
    assert "contradicts the user's request" in build_line


# ---- USER RULING: a content-changing edit must carry the updated deck spec ----

def test_edit_reference_revises_only_the_target_slide_brief():
    ref = case.load_case(AGENT, "edit_request", root=CASES).reference
    assert ref["intent"] == "edit" and ref["target_positions"] == [1]
    DeckSpec.model_validate(ref["deck_spec"])
    gold = case.gold_deck_spec()
    spec = ref["deck_spec"]
    # Every field and every other slide is unchanged ...
    assert {k: v for k, v in spec.items() if k != "slides"} == {k: v for k, v in gold.items() if k != "slides"}
    assert len(spec["slides"]) == len(gold["slides"])
    for pos, (got, want) in enumerate(zip(spec["slides"], gold["slides"])):
        if pos != 1:
            assert got == want, pos
    # ... and on position 1 only content_brief changes, now asking for three stat cards.
    s1, g1 = spec["slides"][1], gold["slides"][1]
    assert {k: v for k, v in s1.items() if k != "content_brief"} == {k: v for k, v in g1.items() if k != "content_brief"}
    brief = s1["content_brief"].lower()
    assert brief != g1["content_brief"].lower()
    assert "three stat cards" in brief
    assert "in place of the bullet list" in brief
    assert "use bullet points" not in brief


# ---- #313: the edit references revise only their target slides ----

def _by_position(spec):
    return {s["position"]: s for s in spec["slides"]}


# #314: an insert reference changes the slide count, so it is checked by alignment instead
# (test_insert_references_are_unambiguous_to_production).
@pytest.mark.parametrize("cid", [c for c in EDIT_CASES if c not in INSERT_CASES])
def test_edit_references_revise_only_their_targets(cid):
    ref = case.load_case(AGENT, cid, root=CASES).reference
    assert ref["intent"] == "edit"
    targets = EXPECT[cid]["positions"]
    assert sorted(ref["target_positions"]) == targets
    spec = ref["deck_spec"]
    DeckSpec.model_validate(spec)
    gold = case.gold_deck_spec()
    # Deck-level fields are the gold's ...
    assert {k: v for k, v in spec.items() if k != "slides"} == {k: v for k, v in gold.items() if k != "slides"}
    assert [s["position"] for s in spec["slides"]] == [s["position"] for s in gold["slides"]]
    got, want = _by_position(spec), _by_position(gold)
    for pos in want:
        if pos not in targets:
            assert got[pos] == want[pos], pos  # ... and so is every non-target slide.
            continue
        changed = {k for k in want[pos] if got[pos].get(k) != want[pos][k]} | (set(got[pos]) - set(want[pos]))
        assert "content_brief" in changed, pos
        assert changed <= {"content_brief", "purpose"}, (pos, changed)
        assert ("purpose" in changed) == (cid in PURPOSE_REVISED), (pos, changed)
    if cid == "edit_request":
        brief = got[1]["content_brief"].lower()
        assert "three stat cards" in brief and "in place of the bullet list" in brief
    elif cid == "edit_polite_ordinal":
        brief = got[1]["content_brief"]
        assert len(brief) < len(want[1]["content_brief"])
        assert "three terse bullets" in brief
    elif cid == "edit_last_slide":
        brief = got[9]["content_brief"]
        assert "No stat cards" in brief and "call to action" in brief
        assert "scorecard" not in got[9]["purpose"]
    elif cid == "edit_multi_slide":
        for pos in (3, 4, 5):
            brief = got[pos]["content_brief"]
            assert len(brief) < len(want[pos]["content_brief"]), pos
            assert "short" in brief, pos
        # Slide 4 keeps its chart layout, consistent with its unchanged data_references.
        assert "chart-plus-commentary" in got[3]["content_brief"]
        for pos in (4, 5):
            assert got[pos]["content_brief"].endswith("in three short bullets and a one-line callout"), pos
    else:
        pytest.fail(f"no brief markers pinned for {cid}")


def test_new_cases_are_fair_on_the_gold():
    """Each #313 request asks for a real change to what the gold slide actually holds."""
    slides = _by_position(case.gold_deck_spec())
    assert max(slides) == 9 and len(slides) == 10  # "the last slide" is position 9
    assert "bullet" in slides[1]["content_brief"].lower()
    assert "three stat cards" in slides[9]["content_brief"]
    assert "call to action" in slides[9]["content_brief"]
    assert "scorecard" in slides[9]["purpose"]
    for pos, beat in ((3, 1), (4, 2), (5, 3)):
        assert slides[pos]["purpose"].startswith(f"Evidence beat {beat}"), pos
    assert "chart-plus-commentary" in slides[3]["content_brief"]
    assert "callout" in slides[4]["content_brief"]
    assert "callout" in slides[5]["content_brief"]
    assert "Accessibility" in slides[6]["purpose"]


# ---- #313 (plan Task 7): the payload carries the production slide numbering and references ----

@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_numbering_is_the_deck(cid):
    numbering = case.load_case(AGENT, cid, root=CASES).payload["slide_numbering"]
    if cid in HAS_DECK:
        want = [{"slide_number": n, "position": n - 1} for n in range(1, DECK_SLIDES + 1)]
        assert numbering == want
    else:
        assert numbering == []


@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_references_are_pinned(cid):
    references = case.load_case(AGENT, cid, root=CASES).payload["slide_references"]
    assert references == SLIDE_REFERENCES[cid]


# #314: an insert's references name current slides, not its new positions (test_insert_anchors).
@pytest.mark.parametrize("cid", [c for c in EDIT_CASES if c not in INSERT_CASES])
def test_resolved_references_equal_the_expected_edit_positions(cid):
    """A2's deterministic proof on the eval messages: the resolver yields every expected target."""
    c = case.load_case(AGENT, cid, root=CASES)
    references = c.payload["slide_references"]
    assert sorted({p for r in references for p in r["positions"]}) == c.expect["positions"]
    assert all(r["out_of_range"] == [] for r in references)


def test_a_discuss_case_still_names_a_slide():
    """References are lexical, not intent: a question naming a slide resolves it, stays discuss."""
    c = case.load_case(AGENT, "discuss_slide_question", root=CASES)
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


def test_edit_calibration_still_fails_on_the_off_by_one():
    c = case.load_case(AGENT, "edit_request", root=CASES)
    bad = _cal("edit_request")["should_fail"]
    assert bad["target_positions"] == [2]
    ok, _ = expected_category_score(AGENT, bad, c.expect)
    assert not ok


def test_judge_prompt_fails_an_edit_without_the_updated_deck_spec():
    edit_line = next(l for l in _prompt().lower().splitlines() if l.startswith("- edit:"))
    assert "deck_spec is null" in edit_line and "fail" in edit_line
    assert "does not reflect the requested change" in edit_line
    assert "pass" in edit_line and "delivers the request" in edit_line
    assert "may leave deck_spec null" not in edit_line


# ---- #314 (plan Task 9, D10, D11): the add-a-slide cases ----

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
    gold = case.gold_deck_spec()
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
    gold = case.gold_deck_spec()
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
    """The whole reference: the gold spec with the new slide spliced in and re-stamped, plus only
    the named revision; the deck-level fields untouched."""
    assert case.load_case(AGENT, cid, root=CASES).reference == _expected_reference(cid)


def test_insert_reference_pins_are_literal():
    """The oracle's targets and final positions, written out (so the oracle cannot drift)."""
    ref = {cid: _expected_reference(cid) for cid in INSERT_CASES}
    assert {cid: r["target_positions"] for cid, r in ref.items()} == {
        "add_slide_anchor": [3], "add_slide_end": [10],
        "add_slide_as_number": [1], "add_slide_and_revise": [8, 10],
    }
    assert {cid: len(r["deck_spec"]["slides"]) for cid, r in ref.items()} == dict.fromkeys(
        INSERT_CASES, 11
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
        "add_slide_anchor": [3], "add_slide_end": [9],
        "add_slide_as_number": [2], "add_slide_and_revise": [8],
    }
    assert {cid: len(b["deck_spec"]["slides"]) for cid, b in bad.items()} == {
        "add_slide_anchor": 11, "add_slide_end": 10,
        "add_slide_as_number": 11, "add_slide_and_revise": 11,
    }
    assert bad["add_slide_end"]["deck_spec"]["slides"][9]["purpose"].startswith("Appendix")
    assert bad["add_slide_as_number"]["deck_spec"]["slides"][2]["purpose"] == (
        "Set out the agenda for the talk"
    )


@pytest.mark.parametrize("cid", INSERT_CASES)
def test_insert_references_are_unambiguous_to_production(cid):
    """D10: production's own alignment reads each reference as exactly the expected insert.

    ``align_slides`` (the function architect_node and the scorer call) gives the expected new
    slides and revisions; every current slide keeps its order and shifts past the new one, and
    every slide outside ``positions`` is its gold slide ignoring position.
    """
    c = case.load_case(AGENT, cid, root=CASES)
    gold = case.gold_deck_spec()
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
    c = case.load_case(AGENT, cid, root=CASES)
    bad = _cal(cid)["should_fail"]
    gold = DeckSpec.model_validate(case.gold_deck_spec())
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
    refs = case.load_case(AGENT, cid, root=CASES).payload["slide_references"]
    return [p for r in refs for p in r["positions"]]


def test_insert_anchors():
    """The resolved references name CURRENT slides; each case's insert follows from them."""
    ins = {cid: case.load_case(AGENT, cid, root=CASES).expect["inserted"] for cid in INSERT_CASES}
    last_old = DECK_SLIDES - 1
    # "after slide N": the named slide is the one the new slide follows.
    assert _resolved_positions("add_slide_anchor") == [ins["add_slide_anchor"][0] - 1]
    # "a new slide N": the new slide takes the named number.
    assert _resolved_positions("add_slide_as_number") == ins["add_slide_as_number"]
    # "a final slide" names no current slide: the new slide is appended.
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
    return case.load_case(AGENT, cid, root=CASES).reference["deck_spec"]["slides"][position]


def test_insert_markers():
    anchor = _ref_slide("add_slide_anchor", 3)["content_brief"]
    assert all(name in anchor for name in FRAMEWORKS), anchor
    assert _ref_slide("add_slide_end", 10)["purpose"].startswith("Appendix")
    assert "five narrative beats" in _ref_slide("add_slide_as_number", 1)["content_brief"]
    summary = _ref_slide("add_slide_and_revise", 10)["content_brief"]
    assert "six advantage dimensions" in summary and "offline use and security" in summary
    off_request = _cal("add_slide_anchor")["should_fail"]["deck_spec"]["slides"][3]["content_brief"]
    assert not any(name in off_request for name in FRAMEWORKS), off_request


def test_insert_cases_are_fair_on_the_gold():
    """Each #314 request asks for a slide the gold deck does not already hold."""
    gold = case.gold_deck_spec()
    slides = _by_position(gold)
    assert "Reveal.js, Slidev, Marp" in slides[2]["content_brief"]  # named, never compared
    for slide in gold["slides"]:
        purpose = slide["purpose"].lower()
        assert not any(word in purpose for word in ("agenda", "appendix", "offline")), purpose
    assert slides[7]["purpose"].startswith("Evidence beat 5")  # the new slide is beat 6
    assert "five advantage dimensions" in slides[9]["content_brief"]
    # The arc lists the five dimensions and stays unchanged: an insert must not re-plan the deck.
    assert "responsiveness, typography, interactivity, accessibility, collaboration" in (
        gold["narrative_arc"][2]
    )


@pytest.mark.parametrize("cid", INSERT_CASES)
def test_insert_faults_name_the_trap(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    for position in c.expect["inserted"]:
        assert f"position {position}" in c.fault, c.fault
    if cid == "add_slide_and_revise":
        assert "narrative_arc" in c.fault and "five" in c.fault, c.fault
