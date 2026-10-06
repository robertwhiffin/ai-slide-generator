"""Self-tests for the data_analyst eval pack (Task 15). Behavioural; no model, no network."""
import json

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.skill_io import AnalystOutput
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case
from evals.harness.scorers import expected_category_score

AGENT = "data_analyst"
CASE_IDS = ["figures_inline", "two_sources", "missing_data", "needs_tool", "conflicting_figures"]
MUTATIONS = ["missing_data", "needs_tool", "conflicting_figures"]
POSITIVES = ["figures_inline", "two_sources"]
EXPECT = {
    "figures_inline": {"outcome": "success"},
    "two_sources": {"outcome": "success"},
    "missing_data": {"outcome": "missing_data"},
    "needs_tool": {"outcome": "no_tool"},
    "conflicting_figures": {"outcome": "success"},
}
# Figures that must appear verbatim in the user's message.
MESSAGE_FIGURES = {
    "figures_inline": ["98%", "StatCounter"],
    "two_sources": ["8–15 MB", "under 1 MB"],
    "conflicting_figures": ["8 MB", "15 MB", "Survey A", "Survey B"],
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
PAYLOAD_KEYS = {"data_request", "deck_purpose"}


def _snapshot():
    cases = PACK_DIR / "cases"
    if not cases.exists():
        return {}
    return {
        str(p.relative_to(PACK_DIR)): p.read_bytes()
        for p in sorted(cases.rglob("*"))
        if p.is_file()
    }


# Capture committed state BEFORE any generate() call in this module (packs-facts rule).
_initial_snapshot = _snapshot()


@pytest.fixture(scope="module", autouse=True)
def generated():
    from evals.packs.data_analyst import mutations

    mutations.generate()
    return _snapshot()


def _cal(cid):
    return json.loads((PACK_DIR / "cases" / cid / "calibration.json").read_text())


def _msg(cid):
    return case.load_case(AGENT, cid).payload["data_request"]


def test_exactly_the_five_cases():
    cases = case.load_cases(AGENT)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    dirs = sorted(d.name for d in (PACK_DIR / "cases").iterdir() if d.is_dir())
    assert dirs == sorted(CASE_IDS)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    d = PACK_DIR / "cases" / cid
    assert sorted(p.name for p in d.iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = case.load_case(AGENT, cid)
    assert c.design_system_active is True
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert set(c.payload) == PAYLOAD_KEYS
    assert c.kind == ("mutation" if cid in MUTATIONS else "positive")
    assert (c.fault == "") == (c.kind == "positive")
    assert c.expect == EXPECT[cid]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    p = case.load_case(AGENT, cid).payload
    assert set(p) == PAYLOAD_KEYS
    assert isinstance(p["data_request"], str) and p["data_request"].strip()
    assert p["deck_purpose"] is None


@pytest.mark.parametrize("cid", list(MESSAGE_FIGURES))
def test_figures_appear_verbatim_in_the_message(cid):
    msg = _msg(cid)
    for fig in MESSAGE_FIGURES[cid]:
        assert fig in msg, f"{fig!r} missing from {cid} message"


def test_missing_data_message_asks_for_figures_it_does_not_contain():
    msg = _msg("missing_data")
    assert "Reveal.js" in msg and "2023" in msg
    assert "monthly active users" in msg.lower()
    assert not any(ch.isdigit() for ch in msg.replace("2023", ""))


def test_needs_tool_message_asks_for_a_database_query():
    msg = _msg("needs_tool").lower()
    assert "query" in msg and "warehouse" in msg and "revenue by region" in msg


def test_positive_messages_carry_figures_and_mutations_differ():
    assert len({_msg(c) for c in CASE_IDS}) == 5


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_validates_and_passes(cid):
    c = case.load_case(AGENT, cid)
    out = AnalystOutput.model_validate(c.reference)
    assert out.outcome == EXPECT[cid]["outcome"]
    ok, why = expected_category_score(AGENT, c.reference, c.expect)
    assert ok, why


@pytest.mark.parametrize("cid", ["figures_inline", "two_sources", "conflicting_figures"])
def test_success_references_have_synthesis_and_sources(cid):
    ref = case.load_case(AGENT, cid).reference
    assert ref["synthesis"].strip()
    assert ref["sources"] and all(isinstance(s, str) and s for s in ref["sources"])


def test_figures_inline_reference_uses_the_stated_figure():
    ref = case.load_case(AGENT, "figures_inline").reference
    assert "98%" in ref["synthesis"]


def test_two_sources_reference_cites_both():
    ref = case.load_case(AGENT, "two_sources").reference
    assert len(ref["sources"]) == 2
    syn = ref["synthesis"]
    assert "8–15 MB" in syn
    assert "1 MB" in syn


def test_conflicting_reference_flags_the_conflict():
    ref = case.load_case(AGENT, "conflicting_figures").reference
    syn = ref["synthesis"]
    assert "8 MB" in syn and "15 MB" in syn
    assert any(w in syn.lower() for w in ("conflict", "disagree", "differ"))


def test_missing_data_reference_names_the_gap():
    ref = case.load_case(AGENT, "missing_data").reference
    assert ref["outcome"] == "missing_data"
    assert ref["gap"] and ref["gap"].strip()
    assert not ref.get("synthesis")


def test_needs_tool_reference_claims_no_data():
    ref = case.load_case(AGENT, "needs_tool").reference
    assert ref["outcome"] == "no_tool"
    assert not ref.get("synthesis")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_valid_and_different(cid):
    c = case.load_case(AGENT, cid)
    bad = _cal(cid)["should_fail"]
    AnalystOutput.model_validate(bad)
    assert bad != c.reference


@pytest.mark.parametrize("cid", ["missing_data", "needs_tool"])
def test_mutation_calibration_has_the_wrong_outcome(cid):
    c = case.load_case(AGENT, cid)
    bad = _cal(cid)["should_fail"]
    assert bad["outcome"] != EXPECT[cid]["outcome"]
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"


@pytest.mark.parametrize("cid", POSITIVES)
def test_positive_calibration_wrongly_claims_missing_data(cid):
    c = case.load_case(AGENT, cid)
    bad = _cal(cid)["should_fail"]
    assert bad["outcome"] == "missing_data"
    ok, _ = expected_category_score(AGENT, bad, c.expect)
    assert not ok


def test_conflicting_calibration_passes_the_scorer_but_hides_the_conflict():
    c = case.load_case(AGENT, "conflicting_figures")
    bad = _cal("conflicting_figures")["should_fail"]
    assert bad["outcome"] == "success"
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert ok, why  # the judge, not the scorer, must fail this
    syn = bad["synthesis"]
    lacks_a_value = "8 MB" not in syn or "15 MB" not in syn
    lacks_conflict_word = not any(w in syn.lower() for w in ("conflict", "disagree", "differ"))
    assert lacks_a_value or lacks_conflict_word


def test_generator_is_idempotent(generated):
    from evals.packs.data_analyst import mutations

    before = dict(generated)
    mutations.generate()
    assert _snapshot() == before


def test_committed_cases_are_current():
    current = _snapshot()
    missing = set(_initial_snapshot) - set(current)
    extra = set(current) - set(_initial_snapshot)
    assert not missing and not extra, f"File set mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
    differing = sorted(p for p in current if current[p] != _initial_snapshot[p])
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


def test_judge_prompt_checks_synthesis_is_faithful_to_the_request():
    text = _prompt().lower()
    assert "faithful" in text
    assert "invent" in text
    assert "data_request" in text
    assert "synthesis" in text and "success" in text
    assert "conflict" in text
    assert "flag" in text


def test_judge_prompt_handles_the_positive_cases():
    text = _prompt().lower()
    assert "pass" in text and "fail" in text
    assert "reference" in text and "example" in text
    for word in ("missing_data", "no_tool"):
        assert word in text
    assert "two" in text and "source" in text  # cites both sources


def test_judge_prompt_describes_only_what_the_judge_receives():
    text = _prompt().lower()
    assert "measures" not in text or "null" in text or "none" in text
    for stray in ("overflow", "contrast", "render_measures", "fault label"):
        assert stray not in text
