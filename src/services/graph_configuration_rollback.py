"""Graph Release rollback: compare, validate and preview (#270).

Rollback is a thin caller of #269's publication core with historical content.
This module owns only what is rollback-specific: loading a historical release
through the history read model, the structural checks, the per-role draft
effect, and the source release's evidence.

Locks (global order, see ``graph_configuration_publication``):

- ``compare_with_active`` takes no row lock.  Its first statement is the history
  read model's release-set statement; every later read is filtered to that set.
- ``preview_rollback`` takes the shared parent lock (``_lock_current_parents``
  with ``exclusive=False``) as the first statement of its own transaction, so
  the draft effect is coherent with the active release.  The remote endpoint
  check runs only after that transaction commits, once per distinct endpoint
  (Corrections 2 and 34): no network call happens under a lock.

This module imports neither ``graph_release_evidence`` nor #268's workbench at
module scope (Correction 29): the facade imports this module, and both of those
import the facade's dependencies back.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select

from src.database.models.graph_configuration import AgentTestRun, GraphReleaseTestRun
from src.services.graph_configuration_content import GraphConfigurationIntegrityError
from src.services.graph_configuration_draft import (
    DraftContentRejected,
    DraftValidationIssue,
)
from src.services.graph_configuration_publication import (
    EvidenceLink,
    FieldDiff,
    _GraphConfigurationPublication,
    _model_nodes,
    definition_field_diffs,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    DefinitionContent,
)
from src.services.graph_release_history import (
    GraphVersionNotFound,
    ReleaseDefinition,
    ReleaseRef,
    _read_history,
    _release_definitions,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.services.graph_configuration_workbench import GraphWorkbenchSnapshot
    from src.services.graph_release_history import _HistorySnapshot

DraftEffect = Literal["reset", "kept", "unchanged"]
RollbackBlock = Literal["source_is_active", "matches_active", "incompatible"]

_AGENT_KEY_ORDER = {key: index for index, key in enumerate(GRAPH_V1_AGENT_KEYS)}


@dataclass(frozen=True)
class AgentComparison:
    agent_key: AgentKey
    active_revision_id: int
    historical_revision_id: int
    same_revision: bool
    #: #269's ``FieldDiff``: ``published`` is the active value, ``candidate`` the
    #: historical one.  Empty iff the two contents are equal.
    field_diffs: tuple[FieldDiff, ...]


@dataclass(frozen=True)
class ReleaseComparison:
    active: ReleaseRef
    historical: ReleaseRef
    #: Exactly seven, in ``GRAPH_V1_AGENT_KEYS`` order.
    agents: tuple[AgentComparison, ...]


@dataclass(frozen=True)
class RollbackPreview:
    source: ReleaseRef
    active: ReleaseRef
    next_version_number: int
    lock_version: int
    default_release_note: str
    comparison: ReleaseComparison
    #: The links a rollback would write: every candidate run linked to the
    #: source, as ``historical_restore`` with ``source_release_id`` = the source.
    evidence: tuple[EvidenceLink, ...]
    #: Exactly seven, in ``GRAPH_V1_AGENT_KEYS`` order.
    draft_effect: Mapping[AgentKey, DraftEffect]
    #: Structural issues (publication's local and post-stale phases), with
    #: fields ``definitions.<agent_key>.<field>``.  Computed even when an earlier
    #: check blocks, so the caller can show them.
    issues: tuple[DraftValidationIssue, ...]
    #: The remote endpoint check's failures, run after the locked transaction
    #: committed.  Advisory: a warning never blocks (Correction 2).
    warnings: tuple[DraftValidationIssue, ...]
    #: The first applicable refusal in ``RollbackBlock`` order, else ``None``.
    blocked: RollbackBlock | None

    @property
    def restorable(self) -> bool:
        return self.blocked is None


@dataclass(frozen=True)
class _HistoricalSource:
    ref: ReleaseRef
    #: Exactly seven, in ``GRAPH_V1_AGENT_KEYS`` order, hash-validated.
    definitions: Mapping[AgentKey, ReleaseDefinition]

    @property
    def contents(self) -> Mapping[AgentKey, DefinitionContent]:
        return MappingProxyType(
            {key: self.definitions[key].content for key in GRAPH_V1_AGENT_KEYS}
        )


def _compare(
    *,
    active: ReleaseRef,
    active_definitions: Mapping[AgentKey, tuple[int, DefinitionContent]],
    historical: ReleaseRef,
    historical_definitions: Mapping[AgentKey, ReleaseDefinition],
) -> ReleaseComparison:
    agents: list[AgentComparison] = []
    for key in GRAPH_V1_AGENT_KEYS:
        active_revision_id, active_content = active_definitions[key]
        restored = historical_definitions[key]
        agents.append(
            AgentComparison(
                agent_key=key,
                active_revision_id=active_revision_id,
                historical_revision_id=restored.agent_definition_revision_id,
                same_revision=active_revision_id == restored.agent_definition_revision_id,
                field_diffs=definition_field_diffs(active_content, restored.content),
            )
        )
    return ReleaseComparison(active=active, historical=historical, agents=tuple(agents))


class _GraphConfigurationRollback(_GraphConfigurationPublication):
    """Rollback: a thin caller of #269's publication core with historical content."""

    def compare_with_active(
        self, session: Session, *, version_number: int
    ) -> ReleaseComparison:
        """The active release against one historical release, per role.  Lock-free.

        One history read fixes the release set (its one active entry is "active"),
        so both sides come from the same snapshot (Corrections 22 and 33).
        """
        with session.begin():
            history = _read_history(session)
            active = next(entry for entry in history.entries if entry.is_active)
            source = self._source_from_history(
                session, history, version_number=version_number
            )
            active_definitions = _release_definitions(
                session, history.mappings[active.release_id]
            )
            return _compare(
                active=ReleaseRef(active.release_id, active.version_number),
                active_definitions={
                    key: (d.agent_definition_revision_id, d.content)
                    for key, d in active_definitions.items()
                },
                historical=source.ref,
                historical_definitions=source.definitions,
            )

    def preview_rollback(
        self, session: Session, *, version_number: int
    ) -> RollbackPreview:
        """What rolling back to ``version_number`` now would do.  Writes nothing.

        The checks are ``restore_release``'s, evaluated without raising:
        ``blocked`` is the first applicable of ``source_is_active``,
        ``matches_active`` and ``incompatible``.
        """
        with session.begin():
            release_row, draft_row = self._lock_current_parents(session, exclusive=False)
            snapshot = self._snapshot_locked_workbench(
                session, release=release_row, draft=draft_row
            )
            source = self._load_source(session, version_number=version_number)
            active = ReleaseRef(release_row.id, release_row.version_number)
            model_nodes = _model_nodes(snapshot)
            comparison = _compare(
                active=active,
                active_definitions={
                    key: (node.published.revision_id, node.published.content)
                    for key, node in model_nodes.items()
                },
                historical=source.ref,
                historical_definitions=source.definitions,
            )
            contents = source.contents
            issues = self._structural_issues(contents)
            if source.ref.release_id == release_row.id:
                blocked: RollbackBlock | None = "source_is_active"
            elif all(agent.same_revision for agent in comparison.agents):
                blocked = "matches_active"
            elif issues:
                blocked = "incompatible"
            else:
                blocked = None
            evidence = self._historical_evidence(
                session, source_release_id=source.ref.release_id, lock=False
            )
            draft_effect = self._draft_effect(
                snapshot,
                {key: source.definitions[key].content_hash for key in GRAPH_V1_AGENT_KEYS},
            )
            next_version_number = release_row.version_number + 1
            lock_version = draft_row.lock_version
        # The shared parent lock is released: only now may a network call run.
        warnings = self._endpoint_warnings(contents)
        return RollbackPreview(
            source=source.ref,
            active=active,
            next_version_number=next_version_number,
            lock_version=lock_version,
            default_release_note=(
                f"Roll back to Graph Version {source.ref.version_number}."
            ),
            comparison=comparison,
            evidence=evidence,
            draft_effect=draft_effect,
            issues=issues,
            warnings=warnings,
            blocked=blocked,
        )

    def _load_source(self, session: Session, *, version_number: int) -> _HistoricalSource:
        """The historical release's exact seven definitions (Correction 33, Option B).

        Reads through the history read model, whose revision validation maps
        malformed content to ``GraphConfigurationIntegrityError``.  Inside the
        caller's locked transaction these are plain reads.
        """
        return self._source_from_history(
            session, _read_history(session), version_number=version_number
        )

    @staticmethod
    def _source_from_history(
        session: Session, history: _HistorySnapshot, *, version_number: int
    ) -> _HistoricalSource:
        entry = next(
            (e for e in history.entries if e.version_number == version_number), None
        )
        if entry is None:
            raise GraphVersionNotFound(version_number)
        return _HistoricalSource(
            ref=ReleaseRef(entry.release_id, entry.version_number),
            definitions=_release_definitions(session, history.mappings[entry.release_id]),
        )

    def _structural_issues(
        self, contents: Mapping[AgentKey, DefinitionContent]
    ) -> tuple[DraftValidationIssue, ...]:
        """Publication's exact phases per role (Correction 32), never the remote one.

        The saves' local phase (incl. #266's endpoint-name policy), then the
        post-stale phase, in one ``try``: a failed local phase skips post-stale,
        as in ``_changed_candidate_issues``.
        """
        issues: list[DraftValidationIssue] = []
        for key in GRAPH_V1_AGENT_KEYS:
            try:
                self._run_candidate_validators(self._save_local_validators(), contents[key])
                self._run_candidate_validators(self.post_stale_validators, contents[key])
            except DraftContentRejected as rejection:
                issues.extend(
                    DraftValidationIssue(
                        f"definitions.{key}.{issue.field}", issue.code, issue.message
                    )
                    for issue in rejection.issues
                )
        return tuple(issues)

    @staticmethod
    def _draft_effect(
        snapshot: GraphWorkbenchSnapshot, restored_hashes: Mapping[AgentKey, str]
    ) -> Mapping[AgentKey, DraftEffect]:
        """The three-way rebase per role (Q7 default, Correction 35).

        A pending edit (draft differs from the active release) is ``kept``; a
        clean role whose restored content differs is ``reset``; a clean role
        restored to identical content is ``unchanged``.
        """
        model_nodes = _model_nodes(snapshot)
        effect: dict[AgentKey, DraftEffect] = {}
        for key in GRAPH_V1_AGENT_KEYS:
            node = model_nodes[key]
            if node.draft.candidate_hash != node.published.content_hash:
                effect[key] = "kept"
            elif restored_hashes[key] == node.published.content_hash:
                effect[key] = "unchanged"
            else:
                effect[key] = "reset"
        return MappingProxyType(effect)

    @staticmethod
    def _historical_evidence(
        session: Session, *, source_release_id: int, lock: bool
    ) -> tuple[EvidenceLink, ...]:
        """Every candidate run linked to the source, as ``historical_restore`` links.

        ``lock=True`` is the rollback's L3 (Correction 28): ``FOR UPDATE OF
        agent_test_run`` in id order, refreshing the identity map.  The link
        count that follows is a new statement, so it is the post-wait re-check.
        """
        statement = (
            select(AgentTestRun)
            .join(
                GraphReleaseTestRun,
                GraphReleaseTestRun.agent_test_run_id == AgentTestRun.id,
            )
            .where(
                GraphReleaseTestRun.graph_release_id == source_release_id,
                AgentTestRun.run_kind == "candidate",
            )
            .order_by(AgentTestRun.id)
        )
        if lock:
            statement = statement.with_for_update(of=AgentTestRun).execution_options(
                populate_existing=True
            )
        runs = list(session.scalars(statement))
        linked = session.scalar(
            select(func.count())
            .select_from(GraphReleaseTestRun)
            .where(GraphReleaseTestRun.graph_release_id == source_release_id)
        )
        if linked != len(runs):
            raise GraphConfigurationIntegrityError(
                "release evidence references a non-candidate run"
            )
        return tuple(
            EvidenceLink(
                run.id, run.agent_key, run.test_case_id, "historical_restore", source_release_id
            )
            for run in sorted(
                runs, key=lambda r: (_AGENT_KEY_ORDER[r.agent_key], r.test_case_id, r.id)
            )
        )

    def _endpoint_warnings(
        self, contents: Mapping[AgentKey, DefinitionContent]
    ) -> tuple[DraftValidationIssue, ...]:
        """The saves' remote check, once per distinct endpoint, outside any lock.

        Every role using a failing endpoint gets the warning, in
        ``GRAPH_V1_AGENT_KEYS`` order.  No validator composed: no warnings.
        """
        results: dict[str, tuple[DraftValidationIssue, ...]] = {}
        for key in GRAPH_V1_AGENT_KEYS:
            endpoint = contents[key].model.endpoint_name
            if endpoint in results:
                continue
            try:
                self._validate_remote_endpoint(contents[key])
            except DraftContentRejected as rejection:
                results[endpoint] = rejection.issues
            else:
                results[endpoint] = ()
        return tuple(
            DraftValidationIssue(f"definitions.{key}.{issue.field}", issue.code, issue.message)
            for key in GRAPH_V1_AGENT_KEYS
            for issue in results[contents[key].model.endpoint_name]
        )
