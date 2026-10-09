"""#271 Task 10: the recorded HTTP contract the admin Playwright journey replays (AC9).

``frontend/tests/fixtures/graphLifecycleContract.json`` is RECORDED from Task 6's
PostgreSQL journey (``python -m tests.integration.graph_lifecycle_journey
--write-contract <path>``), never hand-written.  This join proves the file still
matches the backend's wire models, so a Playwright spec replaying it cannot drift
from the real API:

* every exchange names the response and request models its route really uses (the
  resolver reads the shipped routers, so a route that changes model drifts here);
* every recorded body round-trips its response model exactly (``extra="forbid"``
  rejects an added key; the round trip catches a missing or renamed one, and gives
  exact key sets for the models without ``forbid``, C49);
* every recorded request round-trips its request model, through
  ``model_validate_json`` so strict models see wire types (C21);
* the exchange ids are exactly the journey's, in order;
* ``recorded_at_commit`` is an ancestor of ``HEAD``.

A fresh recording's SHAPE is compared with this file by
``tests/integration/test_graph_lifecycle_acceptance_postgres.py`` (PostgreSQL), so
backend wire drift that keeps the models valid still goes red in Python.
"""

from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path

import pytest

from tests.integration.graph_lifecycle_journey import (
    CONTRACT_EXCHANGE_KEYS,
    CONTRACT_PATH,
    CONTRACT_VERSION,
    STAGES,
    exchange_models,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every exchange the Task 6 journey records, in recording order.  The admin
#: Playwright journey (Task 10) replays the ``/api/admin`` ones; Task 11's
#: conversation journey consumes the ``/api/sessions`` ones (S02, S11 mid-root,
#: S12, S12b, S16).
EXPECTED_EXCHANGE_IDS = [
    "S01-workbench",
    "S02-post-old-root",
    "S02-post-control-default-body",
    "S03-workbench-before-edit",
    "S03-put-architect",
    "S03-readiness-after-architect",
    "S03-put-builder",
    "S03-readiness-after-builder",
    "S03-put-fixer-stale",
    "S03-workbench-after-edit",
    "S04-post-builder-schema-contract-upgrade",
    "S04-readiness-after-upgrade",
    "S04-put-builder-overlay",
    "S04-readiness-after-overlay",
    "S05-post-architect-protected-assembly-upgrade",
    "S05-readiness-after-upgrade",
    "S05-put-architect-custom-block",
    "S05-readiness-after-custom-block",
    "S06-get-model-endpoints",
    "S06-workbench-before-endpoint",
    "S06-put-fixer-endpoint",
    "S06-readiness-after-endpoint",
    "S07-workbench-before-runs",
    "S07-get-test-cases-architect",
    "S07-post-run-architect",
    "S07-get-runs-architect",
    "S07-readiness-after-run-architect",
    "S07-get-test-cases-builder",
    "S07-post-run-builder",
    "S07-get-runs-builder",
    "S07-readiness-after-run-builder",
    "S07-get-test-cases-fixer",
    "S07-post-run-fixer",
    "S07-get-runs-fixer",
    "S07-readiness-after-run-fixer",
    "S08-reject-builder",
    "S08-readiness-after-reject",
    "S08-approve-architect",
    "S08-readiness-after-approve-architect",
    "S08-approve-fixer",
    "S08-readiness-after-approve-fixer",
    "S08-post-rerun-builder",
    "S08-get-runs-builder-after-rerun",
    "S09-readiness-before-rerun-approval",
    "S09-approve-builder-rerun",
    "S09-readiness-after-rerun-approval",
    "S10-get-release-preview",
    "S11-post-mid-root",
    "S11-post-release-stale",
    "S11-post-release",
    "S11-workbench-after-publish",
    "S12-post-new-root",
    "S12-post-contribute-old-root",
    "S12-post-duplicate-old-root",
    "S12-get-old-root",
    "S12-get-mid-root",
    "S12-get-contributor",
    "S12b-get-old-root-collaboration-history",
    "S14-get-releases",
    "S14-get-release-1",
    "S14-get-release-2",
    "S14-get-release-1-comparison",
    "S14-get-release-99",
    "S15-get-rollback-preview-1",
    "S15-post-rollback-1-stale",
    "S15-post-rollback-1",
    "S15-workbench-after-rollback",
    "S16-post-post-rollback-root",
    "S16-get-new-root",
    "S16-get-old-root",
]


def _load() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _model(dotted: str):
    module, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(module), name)


def _exchanges() -> list[dict]:
    return _load()["exchanges"]


def test_the_contract_is_the_recorded_file_at_its_version() -> None:
    contract = _load()
    assert set(contract) == {"contract_version", "recorded_at_commit", "exchanges"}
    assert contract["contract_version"] == CONTRACT_VERSION == 1
    assert CONTRACT_PATH == REPO_ROOT / "frontend/tests/fixtures/graphLifecycleContract.json"
    for exchange in contract["exchanges"]:
        assert tuple(exchange) == CONTRACT_EXCHANGE_KEYS, exchange["id"]


def test_the_exchange_ids_are_exactly_the_journeys_in_stage_order() -> None:
    ids = [exchange["id"] for exchange in _exchanges()]
    assert ids == EXPECTED_EXCHANGE_IDS
    order = list(STAGES)
    stage_positions = [order.index(exchange_id.split("-", 1)[0]) for exchange_id in ids]
    assert stage_positions == sorted(stage_positions), "exchanges are not in stage order"


def test_every_exchange_names_the_models_its_route_really_uses() -> None:
    recorded = [
        (exchange["id"], exchange["response_model"], exchange["request_model"])
        for exchange in _exchanges()
    ]
    derived = [
        (
            exchange["id"],
            *exchange_models(
                exchange["method"],
                exchange["path"],
                exchange["status"],
                exchange["request"],
                exchange["body"],
            ),
        )
        for exchange in _exchanges()
    ]
    assert recorded == derived


@pytest.mark.parametrize("exchange_id", EXPECTED_EXCHANGE_IDS)
def test_every_recorded_body_round_trips_its_response_model(exchange_id: str) -> None:
    exchange = next(e for e in _exchanges() if e["id"] == exchange_id)
    if exchange["response_model"] is None:
        # Sessions routes return plain dicts; shape check only (C21, C35): their
        # recursive key structure and status are pinned by the PostgreSQL shape
        # comparison.  The one admin exchange without a model is the 404 detail.
        assert exchange["path"].startswith("/api/sessions") or (
            exchange["status"] == 404 and set(exchange["body"]) == {"detail"}
        ), exchange_id
        return
    model = _model(exchange["response_model"])
    parsed = model.model_validate_json(json.dumps(exchange["body"]))
    # Exact keys, recursively: an added key fails ``extra="forbid"`` (or this
    # equality for the models without it, C49); a dropped or renamed one fails here.
    assert parsed.model_dump(mode="json") == exchange["body"], exchange_id


@pytest.mark.parametrize("exchange_id", EXPECTED_EXCHANGE_IDS)
def test_every_recorded_request_round_trips_its_request_model(exchange_id: str) -> None:
    exchange = next(e for e in _exchanges() if e["id"] == exchange_id)
    if exchange["request_model"] is None:
        assert exchange["request"] is None, exchange_id
        return
    model = _model(exchange["request_model"])
    # C21: ``model_validate_json`` so a strict model sees JSON wire types.
    parsed = model.model_validate_json(json.dumps(exchange["request"]))
    assert parsed.model_dump(mode="json", exclude_unset=True) == exchange["request"], exchange_id


def test_the_admin_journey_mutations_carry_the_bodies_the_ui_must_send() -> None:
    """The three request bodies the Playwright journey deep-equals (steps 2, 6, 7)."""
    by_id = {exchange["id"]: exchange for exchange in _exchanges()}
    assert by_id["S03-put-architect"]["request"]["lock_version"] == 0
    # Temperature input removed from workbench UI: save carries the stored value (0.7).
    assert by_id["S03-put-architect"]["request"]["candidate"]["model"]["temperature"] == 0.7
    assert by_id["S11-post-release"]["request"] == {
        "lock_version": by_id["S10-get-release-preview"]["body"]["draft"]["lock_version"],
        "release_note": "Lifecycle Graph Version 2.",
    }
    assert by_id["S15-post-rollback-1"]["request"] == {
        "lock_version": by_id["S15-get-rollback-preview-1"]["body"]["lock_version"],
        "release_note": "Roll back to Graph Version 1.",
    }


def test_recorded_at_commit_is_an_ancestor_of_head() -> None:
    commit = _load()["recorded_at_commit"]
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), commit
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (commit, result.returncode, result.stderr)
