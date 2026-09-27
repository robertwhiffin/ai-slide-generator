"""Graph Release rollback: compare, validate, preview and restore (#270).

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
- ``restore_release`` takes L0 exclusive (the first statement of its own
  transaction), L1 (all seven draft agents), then L3 (the source's linked
  candidate runs, ``FOR UPDATE OF agent_test_run`` in id order) before #269's
  core links them (Correction 28).  It never takes L2 and runs no approval gate.

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

from src.database.models.graph_configuration import (
    AgentTestRun,
    GraphRelease,
    GraphReleaseTestRun,
)
from src.services.graph_configuration_content import GraphConfigurationIntegrityError
from src.services.graph_configuration_draft import (
    DraftContentRejected,
    DraftValidationIssue,
)
from src.services.graph_configuration_publication import (
    EvidenceLink,
    FieldDiff,
    PublicationConflict,
    PublicationRejected,
    PublishedRelease,
    _GraphConfigurationPublication,
    _model_nodes,
    definition_field_diffs,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    DefinitionContent,
    definition_content_hash,
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

    from src.database.models.graph_configuration import GraphDraft
    from src.services.graph_configuration_workbench import GraphWorkbenchSnapshot
    from src.services.graph_release_history import _HistorySnapshot

DraftEffect = Literal["reset", "kept", "unchanged"]
RollbackBlock = Literal["source_is_active", "matches_active", "incompatible"]

_AGENT_KEY_ORDER = {key: index for index, key in enumerate(GRAPH_V1_AGENT_KEYS)}
#: Correction 19: a wrong type (``bool`` included) versus a non-positive ``int``.
_VERSION_NOT_INT = DraftValidationIssue(
    "version_number", "strict_type", "version_number must be an integer."
)
_VERSION_OUT_OF_RANGE = DraftValidationIssue(
    "version_number", "out_of_range", "version_number must be a positive integer."
)


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
class RestoredRelease:
    #: #269's ``PublishedRelease``; ``published.release.restored_from_release_id``
    #: is ``source.release_id`` and every mapping is ``reused``.
    published: PublishedRelease
    source: ReleaseRef
    #: Exactly seven, in ``GRAPH_V1_AGENT_KEYS`` order: what the rebase did.
    draft_effect: Mapping[AgentKey, DraftEffect]


@dataclass(frozen=True)
class RollbackSourceActive:
    active: ReleaseRef


@dataclass(frozen=True)
class RollbackMatchesActive:
    active: ReleaseRef
    source: ReleaseRef


class RollbackIncompatible(ValueError):  # noqa: N818 - stable public domain name
    """The historical release fails today's structural validation; nothing written."""

    source: ReleaseRef
    issues: tuple[DraftValidationIssue, ...]

    def __init__(
        self, source: ReleaseRef, issues: tuple[DraftValidationIssue, ...]
    ) -> None:
        if not issues:
            raise ValueError("RollbackIncompatible requires at least one issue")
        self.source = source
        self.issues = tuple(issues)
        super().__init__(
            f"Graph Version {source.version_number} is not restorable: "
            + "; ".join(issue.message for issue in self.issues)
        )


RollbackOutcome = (
    RestoredRelease | PublicationConflict | RollbackSourceActive | RollbackMatchesActive
)


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

    def restore_release(
        self,
        session: Session,
        *,
        version_number: int,
        expected_lock_version: int,
        release_note: str,
        actor: str,
    ) -> RollbackOutcome:
        """Publish a historical release's exact seven revisions as the next version.

        One transaction, in the global lock order: L0 (``_lock_current_parents``,
        exclusive, the first statement), L1 (all seven draft agents), then L3
        (the source's linked runs, ``FOR UPDATE`` in id order) before #269's core
        links them.  Rollback owns every rollback-specific refusal, because the
        core accepts a no-op (Correction 26); every refusal precedes every write.
        No approval gate runs (Correction 30) and no model, runtime or remote
        endpoint call is made.  The draft is rebased three ways (Q7 default): the
        core moves the parent once, then clean roles whose restored content
        differs are reset; pending edits are kept.
        """
        self._validate_rollback_request(
            version_number, actor, expected_lock_version, release_note
        )
        with session.begin():
            release_row, draft_row = self._lock_current_parents(session, exclusive=True)
            draft_rows = {
                row.agent_key: row
                for row in self._lock_all_draft_agents(session, draft_id=draft_row.id)
            }
            snapshot = self._snapshot_locked_workbench(
                session, release=release_row, draft=draft_row
            )
            source = self._load_source(session, version_number=version_number)
            if expected_lock_version != draft_row.lock_version:
                return PublicationConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=draft_row.lock_version,
                    active_release_id=release_row.id,
                    active_version_number=release_row.version_number,
                    draft=snapshot.draft,
                )
            active = ReleaseRef(release_row.id, release_row.version_number)
            if source.ref.release_id == release_row.id:
                return RollbackSourceActive(active)
            model_nodes = _model_nodes(snapshot)
            if all(
                source.definitions[key].agent_definition_revision_id
                == model_nodes[key].published.revision_id
                for key in GRAPH_V1_AGENT_KEYS
            ):
                return RollbackMatchesActive(active=active, source=source.ref)
            contents = source.contents
            issues = self._structural_issues(contents)
            if issues:
                raise RollbackIncompatible(source.ref, issues)
            evidence = self._historical_evidence(
                session, source_release_id=source.ref.release_id, lock=True
            )
            effect = self._draft_effect(
                snapshot,
                {key: source.definitions[key].content_hash for key in GRAPH_V1_AGENT_KEYS},
            )
            published = self._commit_locked_publication(
                session,
                release_row=release_row,
                draft_row=draft_row,
                snapshot=snapshot,
                contents=contents,
                evidence=evidence,
                release_note=release_note,
                actor=actor,
                restored_from_release_id=source.ref.release_id,
            )
            if not all(m.reused for m in published.mappings.values()):
                raise GraphConfigurationIntegrityError(
                    "rollback materialized a new revision"
                )
            for key in GRAPH_V1_AGENT_KEYS:
                if effect[key] == "reset":
                    self._assign_locked_candidate(draft_rows[key], contents[key])
            session.flush()
            new_release_row = session.get(GraphRelease, published.release.release_id)
            if new_release_row is None:
                raise GraphConfigurationIntegrityError(
                    "restored release is missing after publication"
                )
            self._verify_rebased_draft(
                session,
                release_row=new_release_row,
                draft_row=draft_row,
                effect=effect,
                before=snapshot,
                restored=contents,
            )
            return RestoredRelease(
                published=published, source=source.ref, draft_effect=effect
            )

    def _validate_rollback_request(
        self,
        version_number: object,
        actor: object,
        lock_version: object,
        release_note: object,
    ) -> None:
        """Before any lock: ``version_number``, then #269's actor, lock and note rules.

        One copy of publication's rules (Correction 31); the version issue codes
        follow Correction 19.
        """
        issues: list[DraftValidationIssue] = []
        if isinstance(version_number, bool) or not isinstance(version_number, int):
            issues.append(_VERSION_NOT_INT)
        elif version_number < 1:
            issues.append(_VERSION_OUT_OF_RANGE)
        try:
            self._validate_publication_request(actor, lock_version, release_note)
        except PublicationRejected as rejection:
            issues.extend(rejection.issues)
        if issues:
            raise PublicationRejected(*issues)

    def _verify_rebased_draft(
        self,
        session: Session,
        *,
        release_row: GraphRelease,
        draft_row: GraphDraft,
        effect: Mapping[AgentKey, DraftEffect],
        before: GraphWorkbenchSnapshot,
        restored: Mapping[AgentKey, DefinitionContent],
    ) -> None:
        """Re-read the draft against the restored release and prove the rebase.

        ``reset`` and ``unchanged`` roles hold exactly the restored content (so
        ``changed is False``: the core read back a mapping of exactly these
        revisions); ``kept`` roles keep their exact prior candidate.  Anything
        else is an integrity error, raised inside the transaction so nothing
        commits.
        """
        if draft_row.base_release_id != release_row.id:
            raise GraphConfigurationIntegrityError(
                "rebased draft is not based on the restored release"
            )
        prior = _model_nodes(before)
        after = _model_nodes(
            self._snapshot_locked_workbench(session, release=release_row, draft=draft_row)
        )
        for key in GRAPH_V1_AGENT_KEYS:
            node = after[key]
            prior_hash = prior[key].draft.candidate_hash
            code = effect[key]
            if code == "kept":
                holds = node.draft.candidate_hash == prior_hash
            elif code in ("reset", "unchanged"):
                holds = node.draft.candidate_hash == definition_content_hash(
                    restored[key]
                )
            else:
                holds = False
            if not holds:
                raise GraphConfigurationIntegrityError(
                    f"rebased draft role {key!r} does not match its effect {code!r}"
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
        as in ``_changed_candidate_issues``: both call ``_candidate_contents_issues``.
        """
        return tuple(
            self._candidate_contents_issues(
                {key: contents[key] for key in GRAPH_V1_AGENT_KEYS}
            )
        )

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
