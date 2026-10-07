"""Cross-split guards: the held-out set must stay complete, distinct from train, and unable to clobber it.

Behavioural and offline; no model, no network. These are guards over committed data, so they pass on
a healthy tree and go red when a split is damaged or when held-out content leaks from train.
"""
import importlib
import json

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)

from evals.harness import case

HELDOUT_CASE_IDS = {
    "builder": {"cover_slide", "bullets_problem", "stat_cards", "too_much_content", "stat_no_data"},
    "build_reviewer": {"clean", "broken_handoff", "rogue_colour", "overflow", "source_contradiction"},
    "fixer": {"rogue_colour", "overflow", "contrast_failure", "brief_not_delivered", "source_contradiction"},
    "fix_reviewer": {
        "good_fix_accept", "good_contrast_fix_accept", "restyle_reject",
        "content_broken_reject", "fault_left_reject",
    },
    "deck_reviewer": {"clean", "missing_conclusion", "out_of_order", "repetition", "arc_gap_drop_workflow"},
    "architect": {"build_request", "edit_request", "ask_data", "confirm_design", "discuss"},
    "data_analyst": {
        "figures_inline", "conflicting_figures", "two_sources", "needs_tool", "unsourced_public_stat",
    },
}
AGENTS = sorted(HELDOUT_CASE_IDS)
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")


def _case_dirs(agent, split):
    base = case.cases_dir(agent, split=split)
    return sorted(d for d in base.iterdir() if d.is_dir())


def _is_empty_output(data):
    """A reference that carries nothing (``{"findings": []}``) is the correct answer for any clean case, so
    byte equality there is inherent, not leakage."""
    try:
        obj = json.loads(data)
    except ValueError:
        return False
    return isinstance(obj, dict) and not any(obj.values())


def _bytes_of(agent, split, name):
    out = {}
    for d in _case_dirs(agent, split):
        data = (d / name).read_bytes()
        if name == "reference.json" and _is_empty_output(data):
            continue
        out[d.name] = data
    return out


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_total_is_thirty_five():
    assert sum(len(v) for v in HELDOUT_CASE_IDS.values()) == 35


@pytest.mark.parametrize("agent", AGENTS)
def test_heldout_case_ids_pinned(agent):
    assert {d.name for d in _case_dirs(agent, "heldout")} == HELDOUT_CASE_IDS[agent]


@pytest.mark.parametrize("agent", AGENTS)
def test_every_heldout_case_has_the_four_files(agent):
    for d in _case_dirs(agent, "heldout"):
        assert sorted(p.name for p in d.iterdir()) == sorted(FILES), d


@pytest.mark.parametrize("agent", AGENTS)
def test_design_system_active_in_every_heldout_case(agent):
    cases = case.load_cases(agent, split="heldout")
    assert {c.case_id for c in cases} == HELDOUT_CASE_IDS[agent]
    for c in cases:
        assert c.design_system_active is True, f"{agent}/{c.case_id}"


@pytest.mark.parametrize("name", ["payload.json", "reference.json"])
@pytest.mark.parametrize("agent", AGENTS)
def test_no_heldout_file_equals_a_train_one_within_the_agent(agent, name):
    train = {v: k for k, v in _bytes_of(agent, "train", name).items()}
    for cid, data in _bytes_of(agent, "heldout", name).items():
        assert data not in train, f"{agent}/{cid}/{name} equals train case {train.get(data)}"


@pytest.mark.parametrize("name", ["payload.json", "reference.json"])
def test_no_heldout_file_equals_a_train_one_across_all_agents(name):
    train = {}
    for a in AGENTS:
        for cid, data in _bytes_of(a, "train", name).items():
            train[data] = f"{a}/{cid}"
    for a in AGENTS:
        for cid, data in _bytes_of(a, "heldout", name).items():
            assert data not in train, f"{a}/{cid}/{name} equals train {train[data]}"


@pytest.mark.parametrize("agent", AGENTS)
def test_default_output_dir_is_heldout_not_train(agent):
    heldout = importlib.import_module(f"evals.packs.{agent}.heldout")
    assert heldout.CASES_DIR == case.cases_dir(agent, split="heldout")
    assert heldout.CASES_DIR != case.cases_dir(agent, split="train")


@pytest.mark.parametrize("agent", AGENTS)
def test_bare_generate_writes_only_under_the_default_dir(agent, tmp_path, monkeypatch):
    heldout = importlib.import_module(f"evals.packs.{agent}.heldout")
    train_dir = case.cases_dir(agent, split="train")
    committed_heldout = case.cases_dir(agent, split="heldout")
    train_before = _tree(train_dir)
    heldout_before = _tree(committed_heldout)
    target = tmp_path / "cases_heldout"
    monkeypatch.setattr(heldout, "CASES_DIR", target)

    heldout.generate()

    written = [p for p in target.rglob("*") if p.is_file()]
    assert {p.parent.name for p in written} == HELDOUT_CASE_IDS[agent]
    assert all(target in p.parents for p in written)
    assert _tree(train_dir) == train_before, "bare generate() changed the train cases tree"
    assert _tree(committed_heldout) == heldout_before, "bare generate() changed the committed held-out tree"
