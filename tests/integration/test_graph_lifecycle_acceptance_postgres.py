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

import pytest

from tests.integration.graph_lifecycle_journey import (  # noqa: F401 (fixtures)
    STAGES,
    acceptance_stack,
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
