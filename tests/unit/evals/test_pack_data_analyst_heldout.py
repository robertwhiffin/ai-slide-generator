"""Self-tests for the data_analyst HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.skill_io import AnalystOutput
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS, model_payload_for

from evals.harness import case
from evals.harness.scorers import expected_category_score

AGENT = "data_analyst"
CASE_IDS = ["figures_inline", "two_sources", "unsourced_public_stat", "needs_tool", "conflicting_figures"]
MUTATIONS = ["unsourced_public_stat", "needs_tool", "conflicting_figures"]
POSITIVES = ["figures_inline", "two_sources"]
EXPECT = {
    "figures_inline": {"outcome": "success"},
    "two_sources": {"outcome": "success"},
    "unsourced_public_stat": {"outcome": "no_tool"},
    "needs_tool": {"outcome": "no_tool"},
    "conflicting_figures": {"outcome": "success"},
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
COMMITTED = PACK_DIR / "cases_heldout"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module
# Deck-1 (train) content that must not leak into the held-out set.
DECK1_TERMS = ["98%", "8–15 MB", "Reveal.js", "StatCounter", "Survey A", "Survey B"]
CONFLICT_WORDS = ("conflict", "disagree")


def _snapshot(root):
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _runs(text):
    """Digit-runs in a string (the numeric figures, order-insensitive)."""
    return set(re.findall(r"\d+", text or ""))


@pytest.fixture(scope="module", autouse=True)
def generated(tmp_path_factory):
    """Generate the pack once into a tmp tree; tests read from it, never rewriting the committed tree."""
    global CASES
    from evals.packs.data_analyst import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())["should_fail"]


def _msg(cid):
    return _load(cid).payload["data_request"]


def test_exactly_the_five_cases():
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
    assert set(c.payload) == set(MODEL_PAYLOAD_KEYS[AGENT])
    assert c.kind == ("mutation" if cid in MUTATIONS else "positive")
    assert (c.fault == "") == (c.kind == "positive")
    assert c.expect == EXPECT[cid]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    p = _load(cid).payload
    assert set(p) == {"data_request", "deck_purpose"}
    assert isinstance(p["data_request"], str) and p["data_request"].strip()
    assert p["deck_purpose"] is None
    assert p == model_payload_for(AGENT, {"data_request": p["data_request"], "deck_purpose": None})


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_validates_and_matches_expected_outcome(cid):
    c = _load(cid)
    out = AnalystOutput.model_validate(c.reference)
    assert out.outcome == EXPECT[cid]["outcome"]
    ok, why = expected_category_score(AGENT, c.reference, c.expect)
    assert ok, why


@pytest.mark.parametrize("cid", CASE_IDS)
def test_should_fail_is_valid_and_differs(cid):
    c = _load(cid)
    bad = _cal(cid)
    AnalystOutput.model_validate(bad)
    assert set(bad) == set(AnalystOutput.model_fields)
    assert bad != c.reference


# --- figures_inline -------------------------------------------------------------------------

def test_figures_inline_passes_the_stated_figure_through():
    msg = _msg("figures_inline")
    ref = _load("figures_inline").reference
    assert "30–50% fewer tokens" in msg
    assert ref["outcome"] == "success"
    assert "30–50%" in ref["synthesis"]
    assert ref["sources"] and len(ref["sources"]) == 1
    # the named source is the request's own: it appears verbatim in the message
    assert ref["sources"][0] in msg


# --- two_sources ----------------------------------------------------------------------------

def test_two_sources_request_carries_two_sourced_figures():
    msg = _msg("two_sources")
    assert len(_runs(msg)) >= 2
    ref = _load("two_sources").reference
    assert len(ref["sources"]) == 2 and len(set(ref["sources"])) == 2
    for s in ref["sources"]:
        assert s in msg, f"source {s!r} is not named in the request"


def test_two_sources_reference_cites_both_figures():
    msg = _msg("two_sources")
    syn = _load("two_sources").reference["synthesis"]
    missing = _runs(msg) - _runs(syn)
    assert not missing, f"figures in the request missing from the synthesis: {sorted(missing)}"
    assert _runs(syn) <= _runs(msg), "synthesis invents a figure absent from the request"


# --- conflicting_figures --------------------------------------------------------------------

def test_conflicting_request_has_two_surveys_3_vs_5_rounds():
    msg = _msg("conflicting_figures").lower()
    assert msg.count("survey") >= 2
    assert "revision" in msg and "round" in msg
    assert {"3", "5"} <= _runs(msg)


def test_conflicting_reference_flags_the_conflict():
    syn = _load("conflicting_figures").reference["synthesis"]
    assert {"3", "5"} <= _runs(syn)
    assert any(w in syn.lower() for w in CONFLICT_WORDS)


def test_conflicting_should_fail_is_a_success_that_hides_the_conflict():
    c = _load("conflicting_figures")
    bad = _cal("conflicting_figures")
    assert bad["outcome"] == "success"
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert ok, why  # the judge, not the scorer, must fail this
    syn = bad["synthesis"]
    assert not {"3", "5"} <= _runs(syn), "should_fail still states both figures"
    assert not any(w in syn.lower() for w in CONFLICT_WORDS)


# --- unsourced_public_stat ------------------------------------------------------------------

def test_unsourced_public_stat_request_supplies_no_figure_and_reference_invents_none():
    c = _load("unsourced_public_stat")
    assert not _runs(c.payload["data_request"]), "request must supply no figures"
    ref = c.reference
    assert ref["outcome"] == "no_tool"
    assert ref["reason"] and ref["reason"].strip()
    assert not ref.get("synthesis")
    assert not _runs(json.dumps(ref)), f"reference contains digits: {ref}"


def test_unsourced_public_stat_should_fail_invents_a_figure():
    c = _load("unsourced_public_stat")
    bad = _cal("unsourced_public_stat")
    assert bad["outcome"] == "success"
    invented = _runs(bad["synthesis"]) - _runs(c.payload["data_request"])
    assert invented, f"should_fail invents no figure absent from the request: {bad['synthesis']!r}"
    ok, _ = expected_category_score(AGENT, bad, c.expect)
    assert not ok


# --- needs_tool -----------------------------------------------------------------------------

def test_needs_tool_reference_claims_no_data():
    ref = _load("needs_tool").reference
    assert ref["outcome"] == "no_tool"
    assert not ref.get("synthesis")
    assert ref["reason"] and ref["reason"].strip()


def test_needs_tool_should_fail_is_success_with_invented_numbers():
    c = _load("needs_tool")
    bad = _cal("needs_tool")
    assert bad["outcome"] == "success"
    assert _runs(bad["synthesis"]) - _runs(c.payload["data_request"])
    ok, _ = expected_category_score(AGENT, bad, c.expect)
    assert not ok


# --- positives' should_fail: defined and justified here -------------------------------------
# A positive's characteristic wrong answer is refusing despite having the data in the request:
# outcome missing_data (the analyst claims the figure is absent). The scorer must reject it.

@pytest.mark.parametrize("cid", POSITIVES)
def test_positive_should_fail_wrongly_claims_missing_data(cid):
    c = _load(cid)
    bad = _cal(cid)
    assert bad["outcome"] == "missing_data"
    assert not bad.get("synthesis")
    ok, _ = expected_category_score(AGENT, bad, c.expect)
    assert not ok


# --- held-out vs train ----------------------------------------------------------------------

def _train():
    return {cid: case.load_case(AGENT, cid, split="train") for cid in CASE_IDS}


def _train_cal(cid):
    return json.loads((case.cases_dir(AGENT, split="train") / cid / "calibration.json").read_text())["should_fail"]


def test_held_out_requests_differ_from_every_train_request():
    train_msgs = {c.payload["data_request"] for c in _train().values()}
    for cid in CASE_IDS:
        assert _msg(cid) not in train_msgs, cid


def test_held_out_outputs_differ_from_every_train_output():
    train = _train()
    train_refs = [json.dumps(c.reference, sort_keys=True) for c in train.values()]
    train_bad = [json.dumps(_train_cal(cid), sort_keys=True) for cid in CASE_IDS]
    for cid in CASE_IDS:
        assert json.dumps(_load(cid).reference, sort_keys=True) not in train_refs, f"{cid} reference"
        assert json.dumps(_cal(cid), sort_keys=True) not in train_bad, f"{cid} should_fail"


@pytest.mark.parametrize("cid", CASE_IDS)
def test_no_deck1_leakage(cid):
    blob = json.dumps({
        "payload": _load(cid).payload, "reference": _load(cid).reference, "should_fail": _cal(cid),
    }, ensure_ascii=False)
    for term in DECK1_TERMS:
        assert term.lower() not in blob.lower(), f"{term!r} leaked into {cid}"


# --- generation -----------------------------------------------------------------------------

def test_generator_is_idempotent(generated, tmp_path):
    from evals.packs.data_analyst import heldout

    before = dict(generated)
    heldout.generate(out_dir=CASES)
    assert _snapshot(CASES) == before
    other = tmp_path / "second"
    heldout.generate(out_dir=other)
    assert _snapshot(other) == before


def test_generate_into_tmp_does_not_touch_the_committed_tree(tmp_path):
    from evals.packs.data_analyst import heldout

    before = _snapshot(COMMITTED)
    heldout.generate(out_dir=tmp_path / "out")
    assert _snapshot(COMMITTED) == before


def test_default_output_is_the_heldout_tree_not_train():
    from evals.packs.data_analyst import heldout, mutations

    assert heldout.CASES_DIR == case.cases_dir(AGENT, split="heldout") == COMMITTED
    assert heldout.CASES_DIR != mutations.CASES_DIR


def test_bare_generate_writes_only_to_the_default_dir(monkeypatch, tmp_path):
    from evals.packs.data_analyst import heldout, mutations

    target = tmp_path / "default_out"
    monkeypatch.setattr(heldout, "CASES_DIR", target)
    committed_before = _snapshot(COMMITTED)
    train_before = _snapshot(mutations.CASES_DIR)
    heldout.generate()
    assert sorted(d.name for d in target.iterdir() if d.is_dir()) == sorted(CASE_IDS)
    assert _snapshot(COMMITTED) == committed_before
    assert _snapshot(mutations.CASES_DIR) == train_before


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


def test_committed_heldout_loads_via_split():
    for cid in CASE_IDS:
        c = case.load_case(AGENT, cid, split="heldout")
        assert c.design_system_active is True
        assert c.expect == EXPECT[cid]
