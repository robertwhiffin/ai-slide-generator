"""#271 Task 6: the staged edit-to-rollback lifecycle over real PostgreSQL (AC7, AC1).

One journey through the shipped admin and sessions routers: bootstrap, an old
conversation, edits, overlay, assembly upgrade, endpoint change, candidate runs,
verdicts, readiness, preview, publish, pinned conversations, collaboration
history, release history, rollback and post-rollback pins, then the closing
database checks.  The stages, their exact assertions and the harness live in
``graph_lifecycle_journey.py`` so Tasks 7 and 8 reuse them through ``run_to``.

A red run names its ticket: every failure is a ``StageFailure`` labelled
``[<ticket>] <stage> <name> via <seam>``, or ``[AC1/#271]`` when any code-owned
definition source was read after Graph Version 1 was bootstrapped.
"""

from __future__ import annotations

import json

import pytest

from tests.integration.graph_lifecycle_journey import (  # noqa: F401 (fixtures)
    CONTRACT_PATH,
    STAGES,
    acceptance_stack,
    build_contract,
    contract_shape,
    lifecycle_journey,
)

pytestmark = pytest.mark.postgres


def test_edit_test_approve_preview_publish_pin_rollback_lifecycle(
    lifecycle_journey,  # noqa: F811 (the imported fixture)
) -> None:
    journey = lifecycle_journey.run_to("S18")

    assert journey.completed == list(STAGES)
    assert journey.tripwire.reads == []
    ids = [exchange.id for exchange in journey.exchanges]
    assert len(ids) == len(set(ids)), "exchange ids must be unique"
    assert {exchange.id.split("-", 1)[0] for exchange in journey.exchanges} == set(STAGES) - {"S18"}


def test_a_fresh_recording_has_the_checked_in_contracts_shape(
    lifecycle_journey,  # noqa: F811 (the imported fixture)
) -> None:
    """Task 10 (AC9): backend wire drift reds here; front-end drift reds in Playwright.

    The shape is each exchange's id, method, status and model names plus the
    recursive key structure of its request and body, with JSON type names for
    scalars, so ids and timestamps never differ between two recordings.  Re-record
    with ``python -m tests.integration.graph_lifecycle_journey --write-contract
    frontend/tests/fixtures/graphLifecycleContract.json`` and commit the output.
    """
    journey = lifecycle_journey.run_to("S18")
    fresh = contract_shape(build_contract(journey.exchanges, recorded_at_commit="fresh"))
    checked_in = contract_shape(json.loads(CONTRACT_PATH.read_text(encoding="utf-8")))
    assert [row[0] for row in fresh] == [row[0] for row in checked_in]
    for fresh_row, checked_in_row in zip(fresh, checked_in, strict=True):
        assert fresh_row == checked_in_row, fresh_row[0]
