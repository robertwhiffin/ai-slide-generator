"""Atomic Graph Release publication from the shared draft (#269).

Publication is not a second draft writer.  It takes the draft writer's own parent
lock (``_lock_current_parents(exclusive=True)``), re-runs the saves' local
validators, and writes only the draft **parent** row (rebase plus the one audit
helper).  The evidence gate decides readiness under its own locks; this module
never consults #268's readiness result to decide anything.

Lock order (global): L0 active release -> L0 draft (one statement) -> L1 all
seven draft agents by ``agent_key`` -> [gate: L2 case rows -> L3 run rows].
No model, runtime or network call happens while any of these are held.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Mapping, Protocol

from sqlalchemy import func, select

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration_content import (
    GraphConfigurationIntegrityError,
    as_utc_aware,
    database_transaction_timestamp,
    materialize_or_reuse_revision,
)
from src.services.graph_configuration_draft import (
    DraftContentRejected,
    DraftValidationIssue,
    _GraphConfigurationDraft,
)
from src.services.graph_configuration_workbench import (
    ActiveReleaseSnapshot,
    DraftMetadataSnapshot,
    GraphWorkbenchSnapshot,
    ModelAgentNodeSnapshot,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    DefinitionContent,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_EXPECTED_AGENT_KEYS = frozenset(GRAPH_V1_AGENT_KEYS)
RELEASE_NOTE_MAX_LENGTH = 2000
_NOTE_NOT_STRING = DraftValidationIssue(
    "release_note", "strict_type", "Release note must be a string."
)
_BLANK_NOTE = DraftValidationIssue(
    "release_note", "blank", "Release note must not be blank."
)
_NOTE_TOO_LONG = DraftValidationIssue(
    "release_note",
    "too_long",
    f"Release note must be at most {RELEASE_NOTE_MAX_LENGTH} characters.",
)

EvidenceKind = Literal["approval", "historical_restore"]
PublicationGapCode = Literal["no_required_case", "no_eligible_approval"]


@dataclass(frozen=True)
class EvidenceLink:
    agent_test_run_id: int
    agent_key: AgentKey
    test_case_id: int
    evidence_kind: EvidenceKind
    source_release_id: int | None


@dataclass(frozen=True)
class PublicationGap:
    agent_key: AgentKey
    #: ``None`` iff ``code == "no_required_case"``.
    test_case_id: int | None
    code: PublicationGapCode


@dataclass(frozen=True)
class PublicationNotReady:
    #: The gaps the gate found under its own locks: authoritative.  Ordered by
    #: ``GRAPH_V1_AGENT_KEYS`` index, then ``test_case_id``; never empty.
    locked_gaps: tuple[PublicationGap, ...]
    #: #268's readiness computed inside the same transaction, for the wire body
    #: only.  It never decides publication.
    readiness: object

    def __post_init__(self) -> None:
        if not self.locked_gaps:
            raise ValueError("PublicationNotReady requires at least one gap")
        for gap in self.locked_gaps:
            if gap.code == "no_required_case" and gap.test_case_id is not None:
                raise ValueError("a no_required_case gap names no test case")
            if gap.code == "no_eligible_approval" and gap.test_case_id is None:
                raise ValueError("a no_eligible_approval gap names its test case")
            if gap.code not in ("no_required_case", "no_eligible_approval"):
                raise ValueError(f"unknown publication gap code {gap.code!r}")


class PublicationEvidenceGate(Protocol):
    def lock_and_verify(
        self,
        session: Session,
        *,
        snapshot: GraphWorkbenchSnapshot,
        changed_agent_keys: tuple[AgentKey, ...],
    ) -> tuple[EvidenceLink, ...] | PublicationNotReady: ...


@dataclass(frozen=True)
class PublishedMapping:
    agent_key: AgentKey
    agent_definition_revision_id: int
    content_hash: str
    #: True iff the revision row existed before this transaction.
    reused: bool


@dataclass(frozen=True)
class PublishedRelease:
    release: ActiveReleaseSnapshot
    previous_release_id: int
    changed_agent_keys: tuple[AgentKey, ...]
    mappings: Mapping[AgentKey, PublishedMapping]
    evidence: tuple[EvidenceLink, ...]
    draft: DraftMetadataSnapshot


@dataclass(frozen=True)
class PublicationConflict:
    expected_lock_version: int
    current_lock_version: int
    active_release_id: int
    active_version_number: int
    draft: DraftMetadataSnapshot


@dataclass(frozen=True)
class NothingToPublish:
    draft: DraftMetadataSnapshot
    active_release_id: int
    active_version_number: int


class PublicationRejected(ValueError):  # noqa: N818 - stable public domain name
    """The 422 family: raised before any lock or before any write, never after."""

    issues: tuple[DraftValidationIssue, ...]

    def __init__(self, *issues: DraftValidationIssue) -> None:
        if not issues:
            raise ValueError("PublicationRejected requires at least one issue")
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


PublicationOutcome = (
    PublishedRelease | PublicationConflict | NothingToPublish | PublicationNotReady
)


class _GraphConfigurationPublication(_GraphConfigurationDraft):
    """Publish the shared draft as the next complete Graph Release."""

    def publish_draft(
        self,
        session: Session,
        *,
        expected_lock_version: int,
        release_note: str,
        actor: str,
        evidence_gate: PublicationEvidenceGate,
    ) -> PublicationOutcome:
        self._validate_publication_request(actor, expected_lock_version, release_note)
        with session.begin():
            release_row, draft_row = self._lock_current_parents(session, exclusive=True)
            self._lock_all_draft_agents(session, draft_id=draft_row.id)
            snapshot = self._snapshot_locked_workbench(
                session, release=release_row, draft=draft_row
            )
            if expected_lock_version != draft_row.lock_version:
                return PublicationConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=draft_row.lock_version,
                    active_release_id=release_row.id,
                    active_version_number=release_row.version_number,
                    draft=snapshot.draft,
                )
            model_nodes = _model_nodes(snapshot)
            changed = tuple(key for key in GRAPH_V1_AGENT_KEYS if model_nodes[key].changed)
            if not changed:
                return NothingToPublish(
                    snapshot.draft, release_row.id, release_row.version_number
                )
            self._validate_changed_candidates(model_nodes, changed)
            gate_result = evidence_gate.lock_and_verify(
                session, snapshot=snapshot, changed_agent_keys=changed
            )
            if isinstance(gate_result, PublicationNotReady):
                return gate_result
            return self._commit_locked_publication(
                session,
                release_row=release_row,
                draft_row=draft_row,
                snapshot=snapshot,
                contents={
                    key: model_nodes[key].draft.content for key in GRAPH_V1_AGENT_KEYS
                },
                evidence=tuple(gate_result),
                release_note=release_note,
                actor=actor,
                restored_from_release_id=None,
            )

    @staticmethod
    def _validate_publication_request(
        actor: object, lock_version: object, release_note: object
    ) -> None:
        """Strict request shape, checked before any lock: actor, lock, then note."""
        issues = _GraphConfigurationDraft._actor_issues(actor)
        issues.extend(_GraphConfigurationDraft._lock_version_issues(lock_version))
        if not isinstance(release_note, str):
            issues.append(_NOTE_NOT_STRING)
        elif not release_note.strip():
            issues.append(_BLANK_NOTE)
        elif len(release_note) > RELEASE_NOTE_MAX_LENGTH:
            issues.append(_NOTE_TOO_LONG)
        if issues:
            raise PublicationRejected(*issues)

    @staticmethod
    def _lock_all_draft_agents(session: Session, *, draft_id: int) -> list[GraphDraftAgent]:
        """L1: every draft role row, ``agent_key`` order, after the L0 parents."""
        rows = list(
            session.scalars(
                select(GraphDraftAgent)
                .where(GraphDraftAgent.graph_draft_id == draft_id)
                .order_by(GraphDraftAgent.agent_key)
                .with_for_update()
            )
        )
        if len(rows) != len(_EXPECTED_AGENT_KEYS) or {
            row.agent_key for row in rows
        } != _EXPECTED_AGENT_KEYS:
            raise GraphConfigurationIntegrityError(
                "shared draft does not have the exact role key set"
            )
        return rows

    def _validate_changed_candidates(
        self,
        model_nodes: Mapping[AgentKey, ModelAgentNodeSnapshot],
        changed: tuple[AgentKey, ...],
    ) -> None:
        """The saves' local phase (incl. #266's endpoint policy), then post-stale.

        Never the remote endpoint check: that is a network call, and the active
        release row is held ``FOR UPDATE`` here (Correction 37).
        """
        issues: list[DraftValidationIssue] = []
        for key in changed:
            content = model_nodes[key].draft.content
            try:
                self._run_candidate_validators(self._save_local_validators(), content)
                self._run_candidate_validators(self.post_stale_validators, content)
            except DraftContentRejected as rejection:
                issues.extend(
                    DraftValidationIssue(
                        f"definitions.{key}.{issue.field}", issue.code, issue.message
                    )
                    for issue in rejection.issues
                )
        if issues:
            raise PublicationRejected(*issues)

    def _commit_locked_publication(
        self,
        session: Session,
        *,
        release_row: GraphRelease,
        draft_row: GraphDraft,
        snapshot: GraphWorkbenchSnapshot,
        contents: Mapping[AgentKey, DefinitionContent],
        evidence: tuple[EvidenceLink, ...],
        release_note: str,
        actor: str,
        restored_from_release_id: int | None,
    ) -> PublishedRelease:
        """The one publication write.  The caller holds L0 and supplies all seven."""
        if set(contents) != _EXPECTED_AGENT_KEYS or len(contents) != len(
            _EXPECTED_AGENT_KEYS
        ):
            raise GraphConfigurationIntegrityError(
                "publication requires exactly seven definitions"
            )
        timestamp = database_transaction_timestamp(session)
        if timestamp <= as_utc_aware(release_row.effective_from):
            raise GraphConfigurationIntegrityError(
                "publication timestamp does not follow the active release interval"
            )
        created: dict[AgentKey, tuple[AgentDefinitionRevision, bool]] = {
            key: materialize_or_reuse_revision(
                session, contents[key], actor=actor, timestamp=timestamp
            )
            for key in GRAPH_V1_AGENT_KEYS
        }
        session.flush()
        published = {key: node.published for key, node in _model_nodes(snapshot).items()}
        for key, (revision, _was_created) in created.items():
            if (
                published[key].content_hash == revision.content_hash
                and revision.id != published[key].revision_id
            ):
                raise GraphConfigurationIntegrityError(
                    f"unchanged role {key!r} did not reuse its revision"
                )
        latest = session.scalar(select(func.max(GraphRelease.version_number)))
        if latest != release_row.version_number:
            raise GraphConfigurationIntegrityError(
                "active release is not the latest Graph Version"
            )
        release_row.effective_to = timestamp
        # Close before insert: ``uq_graph_release_one_active`` is not deferrable.
        session.flush()
        new_release = GraphRelease(
            version_number=latest + 1,
            previous_release_id=release_row.id,
            restored_from_release_id=restored_from_release_id,
            release_note=release_note,
            published_by=actor,
            published_at=timestamp,
            effective_from=timestamp,
        )
        session.add(new_release)
        session.flush()
        expected_mapping = {key: created[key][0].id for key in GRAPH_V1_AGENT_KEYS}
        session.add_all(
            GraphReleaseAgent(
                graph_release_id=new_release.id,
                agent_key=key,
                agent_definition_revision_id=expected_mapping[key],
            )
            for key in GRAPH_V1_AGENT_KEYS
        )
        session.flush()
        readback = dict(
            session.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == new_release.id)
            ).all()
        )
        if readback != expected_mapping:
            raise GraphConfigurationIntegrityError(
                "published release mapping is incomplete"
            )
        self._link_evidence(session, release_id=new_release.id, evidence=evidence)
        draft_row.base_release_id = new_release.id
        self._advance_locked_draft(draft_row, actor=actor, timestamp=timestamp)
        session.flush()
        return PublishedRelease(
            release=ActiveReleaseSnapshot(
                release_id=new_release.id,
                version_number=new_release.version_number,
                previous_release_id=new_release.previous_release_id,
                restored_from_release_id=new_release.restored_from_release_id,
                release_note=new_release.release_note,
                published_by=new_release.published_by,
                published_at=new_release.published_at,
                effective_from=new_release.effective_from,
                effective_to=new_release.effective_to,
            ),
            previous_release_id=release_row.id,
            changed_agent_keys=tuple(
                key
                for key in GRAPH_V1_AGENT_KEYS
                if published[key].content_hash != created[key][0].content_hash
            ),
            mappings=MappingProxyType(
                {
                    key: PublishedMapping(
                        agent_key=key,
                        agent_definition_revision_id=created[key][0].id,
                        content_hash=created[key][0].content_hash,
                        reused=not created[key][1],
                    )
                    for key in GRAPH_V1_AGENT_KEYS
                }
            ),
            evidence=evidence,
            draft=DraftMetadataSnapshot(
                draft_id=draft_row.id,
                base_release_id=draft_row.base_release_id,
                base_version_number=new_release.version_number,
                lock_version=draft_row.lock_version,
                updated_by=draft_row.updated_by,
                updated_at=draft_row.updated_at,
            ),
        )

    def _link_evidence(
        self,
        session: Session,
        *,
        release_id: int,
        evidence: tuple[EvidenceLink, ...],
    ) -> None:
        """Phase A: no evidence table writer exists yet; Task 4 replaces this body."""
        if evidence:
            raise GraphConfigurationIntegrityError(
                "release evidence linking is not available"
            )


def _model_nodes(
    snapshot: GraphWorkbenchSnapshot,
) -> dict[AgentKey, ModelAgentNodeSnapshot]:
    nodes = {
        node.agent_key: node
        for node in snapshot.nodes
        if node.execution_kind == "model"
    }
    if set(nodes) != _EXPECTED_AGENT_KEYS:
        raise GraphConfigurationIntegrityError(
            "workbench snapshot does not have the exact role key set"
        )
    return nodes


__all__ = [
    "EvidenceKind",
    "EvidenceLink",
    "NothingToPublish",
    "PublicationConflict",
    "PublicationEvidenceGate",
    "PublicationGap",
    "PublicationGapCode",
    "PublicationNotReady",
    "PublicationOutcome",
    "PublicationRejected",
    "PublishedMapping",
    "PublishedRelease",
    "RELEASE_NOTE_MAX_LENGTH",
]
