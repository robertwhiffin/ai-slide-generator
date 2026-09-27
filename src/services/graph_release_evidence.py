"""The approval evidence gate and the release evidence linker (#269 Task 4).

``ApprovalEvidenceGate.lock_and_verify`` runs inside ``publish_draft``'s
transaction, after L0 (release then draft ``FOR UPDATE``) and L1 (every draft
agent).  It decides publication from rows it locks itself, in the global order:

1. **L2** -- every ``agent_test_case`` row of the changed roles, with NO
   ``is_active`` / ``is_required`` filter, ``ORDER BY id``, ``FOR SHARE``
   (Correction 29).  A filtered lock drops a row a concurrent supersede retired
   while the lock waited, and never sees the inserted successor.
2. A NEW statement re-selects the changed roles' active required cases; the gate
   decides on that set.  A changed role with none is a ``no_required_case`` gap
   (Correction 1).
3. **L3** -- the candidate runs that can satisfy those cases, ``ORDER BY id``,
   ``FOR UPDATE`` (Correction 33 addendum).  The predicate is literal columns of
   ``agent_test_run`` only, so the row-lock recheck (EvalPlanQual) re-evaluates
   every term on the updated row.
4. A NEW statement re-verifies the locked rows with #268's shared
   ``eligible_approval_clause`` (Correction 45), so a verdict that committed while
   L3 waited is seen, and the gate and readiness can never disagree on eligibility.
   (A correlated predicate inside the locking statement would not be re-checked:
   Correction 33.)

The newest eligible approval (``run_at``, then ``id``) of each active required
case is the evidence; optional and inactive cases never block and are never
linked (Q5).  The gate never writes.  #268's readiness is called only on the
not-ready path, before any publication write, for the refusal body only: it
never decides and its ``run_id`` is never linked (Correction 32).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from sqlalchemy import and_, or_, select, true

from src.database.models.graph_configuration import (
    AgentTestCase,
    AgentTestRun,
    GraphDraftAgent,
    GraphReleaseTestRun,
)
from src.services.agent_test_workbench import eligible_approval_clause
from src.services.graph_configuration_content import GraphConfigurationIntegrityError
from src.services.graph_configuration_publication import (
    EvidenceLink,
    PublicationGap,
    PublicationNotReady,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS, AgentKey

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.services.graph_configuration_workbench import GraphWorkbenchSnapshot


_ROLE_ORDER = {key: index for index, key in enumerate(GRAPH_V1_AGENT_KEYS)}


def _lock_changed_role_case_rows(session: Session, keys: tuple[AgentKey, ...]) -> None:
    """L2: every case row of the changed roles, unfiltered, id order, ``FOR SHARE``."""
    session.execute(
        select(AgentTestCase)
        .where(AgentTestCase.agent_key.in_(keys))
        .order_by(AgentTestCase.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).all()


def _active_required_cases(
    session: Session, keys: tuple[AgentKey, ...]
) -> list[AgentTestCase]:
    """A NEW statement after L2: its snapshot includes a supersede that
    committed while the lock waited."""
    return list(
        session.scalars(
            select(AgentTestCase)
            .where(
                AgentTestCase.agent_key.in_(keys),
                AgentTestCase.is_active.is_(true()),
                AgentTestCase.is_required.is_(true()),
            )
            .order_by(AgentTestCase.id)
            .execution_options(populate_existing=True)
        )
    )


def _lock_candidate_runs(
    session: Session, cases: list[AgentTestCase], hashes: dict[str, str]
) -> list[int]:
    """L3: the runs that can be evidence, id order, ``FOR UPDATE``.  Literal
    columns only, one conjunction per case, so the lock's recheck covers them.
    It selects ids only: the re-verify below reads every value afresh."""
    return list(
        session.scalars(
            select(AgentTestRun.id)
            .where(
                or_(
                    *(
                        and_(
                            AgentTestRun.test_case_id == case.id,
                            AgentTestRun.test_case_version == case.version,
                            AgentTestRun.agent_key == case.agent_key,
                            AgentTestRun.candidate_hash == hashes[case.agent_key],
                        )
                        for case in cases
                    )
                ),
                AgentTestRun.run_kind == "candidate",
                AgentTestRun.verdict == "approved",
                AgentTestRun.execution_status == "completed",
                AgentTestRun.deterministic_checks_passed.is_(true()),
            )
            .order_by(AgentTestRun.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def _reverified_approvals(
    session: Session,
    *,
    locked_ids: list[int],
    case_ids: list[int],
    draft_id: int,
) -> list[tuple[int, int, object]]:
    """A NEW statement over the locked runs: #268's one eligibility predicate,
    joined to each run's own case row and that role's draft agent.  Returns
    ``(run_id, test_case_id, run_at)``."""
    return [
        (row.id, row.test_case_id, row.run_at)
        for row in session.execute(
            select(AgentTestRun.id, AgentTestRun.test_case_id, AgentTestRun.run_at)
            .join(AgentTestCase, AgentTestCase.id == AgentTestRun.test_case_id)
            .join(GraphDraftAgent, GraphDraftAgent.agent_key == AgentTestCase.agent_key)
            .where(
                AgentTestRun.id.in_(locked_ids),
                AgentTestCase.id.in_(case_ids),
                GraphDraftAgent.graph_draft_id == draft_id,
                eligible_approval_clause(AgentTestRun, AgentTestCase, GraphDraftAgent),
            )
            .order_by(AgentTestRun.id)
            .execution_options(populate_existing=True)
        )
    ]


class ApprovalEvidenceGate:
    """Lock and re-verify the exact approvals that satisfy the changed roles' gate."""

    def __init__(self, *, readiness: Callable[[Session], object]) -> None:
        #: #268's ``readiness_under_parent_lock`` in production (Correction 39):
        #: the not-ready body only, never a decision (Correction 32).
        self._readiness = readiness

    def lock_and_verify(
        self,
        session: Session,
        *,
        snapshot: GraphWorkbenchSnapshot,
        changed_agent_keys: tuple[AgentKey, ...],
    ) -> tuple[EvidenceLink, ...] | PublicationNotReady:
        keys = tuple(changed_agent_keys)
        if not keys:
            return ()
        # L1 already holds every draft agent row, so these hashes are the ones
        # the publication will materialise.
        hashes = {
            node.agent_key: node.draft.candidate_hash
            for node in snapshot.nodes
            if node.execution_kind == "model"
        }
        _lock_changed_role_case_rows(session, keys)
        cases = _active_required_cases(session, keys)
        chosen: dict[int, tuple[object, int]] = {}
        if cases:
            locked_ids = _lock_candidate_runs(session, cases, hashes)
            if locked_ids:
                for run_id, case_id, run_at in _reverified_approvals(
                    session,
                    locked_ids=locked_ids,
                    case_ids=[case.id for case in cases],
                    draft_id=snapshot.draft.draft_id,
                ):
                    best = chosen.get(case_id)
                    if best is None or (run_at, run_id) > best:
                        chosen[case_id] = (run_at, run_id)
        covered = {case.agent_key for case in cases}
        gaps = [PublicationGap(key, None, "no_required_case") for key in keys if key not in covered]
        gaps.extend(
            PublicationGap(case.agent_key, case.id, "no_eligible_approval")
            for case in cases
            if case.id not in chosen
        )
        if gaps:
            gaps.sort(key=lambda gap: (_ROLE_ORDER[gap.agent_key], gap.test_case_id or 0))
            # Before any publication write (Correction 32 rule 4).
            return PublicationNotReady(
                locked_gaps=tuple(gaps), readiness=self._readiness(session)
            )
        return tuple(
            EvidenceLink(chosen[case.id][1], case.agent_key, case.id, "approval", None)
            for case in sorted(cases, key=lambda c: (_ROLE_ORDER[c.agent_key], c.id))
        )


def link_release_evidence(
    session: Session, *, release_id: int, evidence: tuple[EvidenceLink, ...]
) -> None:
    """Insert one ``graph_release_test_run`` row per link and prove the release's
    links are exactly these.

    It takes no lock of its own: inside publication the gate already holds every
    linked run ``FOR UPDATE`` (L3), and a caller that links runs must lock them
    first, in id order (Correction 33 addendum).  The existence check is a plain
    read, so a missing run is a named integrity error rather than an FK error.
    """
    links = tuple(evidence)
    expected = {
        (link.agent_test_run_id, link.evidence_kind, link.source_release_id) for link in links
    }
    if len(expected) != len(links):
        raise GraphConfigurationIntegrityError("release evidence names a run twice")
    run_ids = sorted(link.agent_test_run_id for link in links)
    if run_ids:
        present = list(
            session.scalars(
                select(AgentTestRun.id)
                .where(AgentTestRun.id.in_(run_ids))
                .order_by(AgentTestRun.id)
            )
        )
        if present != run_ids:
            raise GraphConfigurationIntegrityError("release evidence names a missing run")
    session.add_all(
        GraphReleaseTestRun(
            graph_release_id=release_id,
            agent_test_run_id=link.agent_test_run_id,
            evidence_kind=link.evidence_kind,
            source_release_id=link.source_release_id,
        )
        for link in links
    )
    session.flush()
    readback = {
        tuple(row)
        for row in session.execute(
            select(
                GraphReleaseTestRun.agent_test_run_id,
                GraphReleaseTestRun.evidence_kind,
                GraphReleaseTestRun.source_release_id,
            ).where(GraphReleaseTestRun.graph_release_id == release_id)
        )
    }
    if readback != expected:
        raise GraphConfigurationIntegrityError(
            "release evidence read-back does not match its links"
        )


__all__ = ["ApprovalEvidenceGate", "link_release_evidence"]
