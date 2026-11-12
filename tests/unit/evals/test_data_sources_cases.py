"""Task 8a (agent-mode MCP and Genie Agents): the architect's ``data_sources`` case set.
Behavioural and offline; no model, no network.

Names this file fixes for the implementer:

* **The set** lives apart from the architect's train and held-out cases, in
  ``evals/packs/architect/cases_data_sources/`` (``case.case_set_dir("architect",
  "data_sources")``), runnable with ``--case-set data_sources``. Its generator is
  ``evals/packs/architect/data_sources.py`` (modelled on ``image_tool.py``: ``CASES_DIR``,
  ``generate(out_dir=None)``). Every payload goes through ``model_payload_for("architect", ...)``
  and carries production's first-call keys, ``data_sources`` included; the generator asserts
  ``"data_sources" in payload`` for every case it writes, so a payload that lost the key (as
  ``MODEL_PAYLOAD_KEYS`` once stripped it) stops generation. Genie One's item is
  ``nodes.GENIE_ONE_DATA_SOURCE``.
* **Four cases**, each with ``case.yaml``, ``payload.json``, ``reference.json`` and
  ``calibration.json`` (a ``should_fail``); ``expect.intent`` is an exact match:

  - ``genie_agent_listed_needs_figures``: Genie One plus a "Sales" Genie Agent ("Regional sales by
    month"); a new deck needing regional sales figures; ``ask_data``.
  - ``no_sources_needs_figures``: ``data_sources: []``, the same request; ``build``, and the
    reference ``message`` names the data that would help.
  - ``write_request_refused``: a seeded deck; the user asks Tellr to post the deck summary to
    Slack; ``discuss``, and the reference ``message`` says Tellr does not make changes in other
    systems.
  - ``sources_listed_no_data_needed``: Genie One listed; the user asks to retitle slide 2;
    ``edit`` with ``positions: [1]``.
* **The judge sees only** ``message`` and ``current_deck_spec`` of the payload, never
  ``data_sources``: each reference passes ``expected_category`` and each ``should_fail`` fails it
  with a different intent, and the reference's ``message`` names what is asked for or refused.
"""
from __future__ import annotations

import importlib
import json
import re
from types import MappingProxyType

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case
from evals.harness.scorers import expected_category_score
from src.domain.deck_spec import DeckSpec
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_numbering import architect_slide_payload
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS, model_payload_for
from src.services.graph.nodes import GENIE_ONE_DATA_SOURCE

AGENT = "architect"
CASE_SET = "data_sources"
ROOT = case.case_set_dir(AGENT, CASE_SET)
FILES = ("calibration.json", "case.yaml", "payload.json", "reference.json")
INTENTS = {
    "genie_agent_listed_needs_figures": "ask_data",
    "no_sources_needs_figures": "build",
    "write_request_refused": "discuss",
    "sources_listed_no_data_needed": "edit",
}
#: The cases whose request is for a new deck: no deck yet.
NEW_DECK = ("genie_agent_listed_needs_figures", "no_sources_needs_figures")
#: The cases that start from a seeded deck.
SEEDED = ("write_request_refused", "sources_listed_no_data_needed")
#: The keys of every production first call of the architect (``architect_node``); the retry's
#: ``rejected_edit`` is the one key a first call never carries.
FIRST_CALL_KEYS = MODEL_PAYLOAD_KEYS[AGENT] - {"rejected_edit"}


def _cases() -> dict:
    return {c.case_id: c for c in case.load_cases(AGENT, root=ROOT)}


def _case(cid: str):
    cases = _cases()
    assert cid in cases, f"no case {cid!r} under {ROOT}"
    return cases[cid]


def _should_fail(cid: str) -> dict:
    return json.loads((ROOT / cid / "calibration.json").read_text())["should_fail"]


def _tree(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# =========================================================================== the payloads

def test_every_data_sources_case_payload_carries_data_sources():
    cases = _cases()
    assert set(cases) == set(INTENTS)
    for cid, c in cases.items():
        p = c.payload
        assert "data_sources" in p, cid
        assert model_payload_for(AGENT, p) == p, cid
        assert isinstance(p["data_sources"], list), cid
        for item in p["data_sources"]:
            assert set(item) == {"name", "description"}, (cid, item)  # production's item shape

    listed = cases["genie_agent_listed_needs_figures"].payload["data_sources"]
    assert len(listed) == 2, listed
    assert listed[0] == GENIE_ONE_DATA_SOURCE  # production's order: Genie One, then each Agent
    assert listed[1]["name"] == "Sales"
    assert listed[1]["description"].startswith("Regional sales by month"), listed[1]
    assert cases["no_sources_needs_figures"].payload["data_sources"] == []
    assert GENIE_ONE_DATA_SOURCE in cases["sources_listed_no_data_needed"].payload["data_sources"]


def test_the_payloads_are_production_shaped():
    cases = _cases()
    assert set(cases) == set(INTENTS)
    for cid, c in cases.items():
        p = c.payload
        assert set(p) == FIRST_CALL_KEYS, (cid, sorted(set(p) ^ FIRST_CALL_KEYS))
        conversation = p["conversation"]
        assert conversation[-1] == {"role": "user", "content": p["message"]}, cid
        deck = p["current_deck_spec"]
        positions = [s["position"] for s in deck["slides"]] if deck else []
        assert {k: p[k] for k in ("slide_numbering", "slide_references")} == \
            architect_slide_payload(conversation, p["message"], positions), cid
        assert p["committed_slide_count"] == len(positions), cid
    for cid in NEW_DECK:
        assert cases[cid].payload["current_deck_spec"] is None, cid
    for cid in SEEDED:
        deck = cases[cid].payload["current_deck_spec"]
        DeckSpec.model_validate(deck)
        assert len(deck["slides"]) >= 2, cid
    # "slide 2" resolves, as production resolves it, to position 1: the case's positions.
    (ref,) = cases["sources_listed_no_data_needed"].payload["slide_references"]
    assert ref["positions"] == [1]


def test_the_messages_are_the_brief_s():
    msgs = {cid: c.payload["message"] for cid, c in _cases().items()}
    assert set(msgs) == set(INTENTS)
    assert msgs["no_sources_needs_figures"] == msgs["genie_agent_listed_needs_figures"]
    figures = msgs["genie_agent_listed_needs_figures"]
    assert re.search(r"\bsales\b", figures, re.I), figures
    assert re.search(r"\bregion", figures, re.I), figures
    assert re.search(r"\bslack\b", msgs["write_request_refused"], re.I), msgs
    retitle = msgs["sources_listed_no_data_needed"]
    assert re.search(r"\bslide 2\b", retitle, re.I), retitle
    assert re.search(r"title", retitle, re.I), retitle


# =========================================================================== the cases

def test_data_sources_cases_have_concrete_intents_and_four_files():
    assert ROOT == case.PACKS_DIR / AGENT / "cases_data_sources"
    cases = _cases()
    assert set(cases) == set(INTENTS)
    assert {d.name for d in ROOT.iterdir() if d.is_dir()} == set(INTENTS)
    for cid, c in cases.items():
        assert sorted(p.name for p in (ROOT / cid).iterdir()) == sorted(FILES), cid
        assert c.agent_key == AGENT
        assert c.expect["intent"] == INTENTS[cid], (cid, c.expect)
        assert "should_fail" in json.loads((ROOT / cid / "calibration.json").read_text()), cid
    assert cases["sources_listed_no_data_needed"].expect["positions"] == [1]
    # The set lives apart from the architect's train and held-out cases.
    for split in case.SPLITS:
        ids = {c.case_id for c in case.load_cases(AGENT, split=split)}
        assert ids and not ids & set(INTENTS), split


@pytest.mark.parametrize("cid", sorted(INTENTS))
def test_the_reference_passes_and_the_should_fail_fails_expected_category(cid):
    c = _case(cid)
    ref, bad = c.reference, _should_fail(cid)
    ArchitectOutput.model_validate(ref)
    ArchitectOutput.model_validate(bad)
    deck = c.payload["current_deck_spec"]
    kw = {"reference": ref, "current_deck_spec": deck,
          "design_system_active": c.design_system_active}
    assert ref["intent"] == INTENTS[cid]
    ok, why = expected_category_score(AGENT, ref, c.expect, **kw)
    assert ok, (cid, why)
    ok, why = expected_category_score(AGENT, bad, c.expect, **kw)
    assert not ok, (cid, why)
    # The judge never sees data_sources: the difference must show in the answer itself.
    assert bad["intent"] != ref["intent"], cid
    assert bad["message"].strip() and bad["message"] != ref["message"], cid


def test_each_reference_message_names_what_is_asked_for_or_refused():
    cases = _cases()
    assert set(cases) == set(INTENTS)

    asked = cases["genie_agent_listed_needs_figures"].reference
    request = json.dumps(asked["data_request"])
    assert re.search(r"sales|revenue", request, re.I), request
    assert re.search(r"region", request, re.I), request
    assert re.search(r"region", asked["message"], re.I), asked["message"]

    built = cases["no_sources_needs_figures"].reference["message"]
    assert re.search(r"region", built, re.I), built
    assert re.search(r"sales|revenue", built, re.I), built

    refused = cases["write_request_refused"].reference["message"]
    assert re.search(r"\bTellr\b", refused), refused
    assert re.search(r"other systems", refused, re.I), refused

    retitled = cases["sources_listed_no_data_needed"].reference["message"]
    assert re.search(r"title", retitled, re.I), retitled


# =========================================================================== generation

def test_the_generator_refuses_a_payload_that_lost_data_sources(tmp_path, monkeypatch):
    """The Task 7 B1 regression: a projection without ``data_sources`` must stop generation."""
    import src.services.agent_model_payload as amp

    gen = importlib.import_module("evals.packs.architect.data_sources")
    stripped = MappingProxyType(
        {**amp.MODEL_PAYLOAD_KEYS, AGENT: amp.MODEL_PAYLOAD_KEYS[AGENT] - {"data_sources"}})
    monkeypatch.setattr(amp, "MODEL_PAYLOAD_KEYS", stripped)
    assert "data_sources" not in model_payload_for(AGENT, {"data_sources": [], "message": "m"})
    with pytest.raises(AssertionError):
        gen.generate(out_dir=tmp_path / "cases_data_sources")


def test_the_data_sources_case_set_is_generated(tmp_path):
    gen = importlib.import_module("evals.packs.architect.data_sources")
    assert gen.CASES_DIR == ROOT
    committed = _tree(ROOT)
    assert committed
    trees = [case.cases_dir(AGENT), case.cases_dir(AGENT, split="heldout")]
    before = [_tree(t) for t in trees]
    out = tmp_path / "cases_data_sources"
    gen.generate(out_dir=out)
    assert _tree(out) == committed
    assert _tree(ROOT) == committed  # writing elsewhere leaves every committed tree untouched
    assert [_tree(t) for t in trees] == before
