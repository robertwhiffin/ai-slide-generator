"""Immutable Graph Release history: a lock-free, statement-coherent read model.

The first statement of every read fixes the release set, and every later statement
is filtered to those ids.  Releases are append-only (a release's only permitted
change is its first ``effective_to`` close), and mappings, revisions and evidence
links are never rewritten for an existing release.  So under READ COMMITTED the
result is one coherent snapshot as of that first statement, even when a
publication commits between statements, and no row lock is taken.

This module performs no model, endpoint or runtime work and logs nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestRun,
    GraphRelease,
    GraphReleaseAgent,
    GraphReleaseTestRun,
)
from src.services.graph_configuration_content import (
    GraphConfigurationIntegrityError,
    validate_definition_hash,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    DefinitionContent,
)

_EXPECTED_AGENT_KEYS = frozenset(GRAPH_V1_AGENT_KEYS)
_AGENT_KEY_ORDER = {key: index for index, key in enumerate(GRAPH_V1_AGENT_KEYS)}


@dataclass(frozen=True)
class ReleaseRef:
    release_id: int
    version_number: int


@dataclass(frozen=True)
class ReleaseHistoryEntry:
    release_id: int
    version_number: int
    is_active: bool
    release_note: str
    published_by: str
    published_at: datetime
    effective_from: datetime
    effective_to: datetime | None
    previous: ReleaseRef | None
    restored_from: ReleaseRef | None
    #: Later releases whose ``restored_from`` is this one, ascending by version.
    restored_by: tuple[ReleaseRef, ...]
    #: Roles whose revision differs from the predecessor's, in
    #: ``GRAPH_V1_AGENT_KEYS`` order; v1 (no predecessor) lists all seven.
    changed_agent_keys: tuple[AgentKey, ...]


@dataclass(frozen=True)
class ReleaseDefinition:
    agent_key: AgentKey
    agent_definition_revision_id: int
    content_hash: str
    content: DefinitionContent


@dataclass(frozen=True)
class ReleaseEvidence:
    agent_test_run_id: int
    agent_key: AgentKey
    test_case_id: int
    test_case_version: int
    evidence_kind: Literal["approval", "historical_restore"]
    #: Non-None iff ``evidence_kind == "historical_restore"``.
    source: ReleaseRef | None
    verdict: str | None
    verdict_reviewer: str | None
    verdict_at: datetime | None
    execution_status: str
    deterministic_checks_passed: bool
    run_at: datetime


@dataclass(frozen=True)
class ReleaseDetail:
    entry: ReleaseHistoryEntry
    #: Exactly seven, in ``GRAPH_V1_AGENT_KEYS`` order, read-only.
    definitions: Mapping[AgentKey, ReleaseDefinition]
    #: Ordered by (``GRAPH_V1_AGENT_KEYS`` index, test case id, run id).
    evidence: tuple[ReleaseEvidence, ...]


class GraphVersionNotFound(LookupError):  # noqa: N818 - stable public domain name
    """No Graph Release has the requested version number."""

    def __init__(self, version_number: int) -> None:
        super().__init__(f"Graph Version {version_number} does not exist")
        self.version_number = version_number


@dataclass(frozen=True)
class _HistorySnapshot:
    entries: tuple[ReleaseHistoryEntry, ...]
    refs: Mapping[int, ReleaseRef]
    mappings: Mapping[int, Mapping[str, int]]


def _read_history(session: Session) -> _HistorySnapshot:
    # The one statement that fixes the release set.  ``populate_existing`` makes it
    # overwrite any release already in the session's identity map, so a release
    # loaded before a later close cannot survive here as a second active row.
    releases = list(
        session.scalars(
            select(GraphRelease)
            .order_by(GraphRelease.version_number.desc())
            .execution_options(populate_existing=True)
        )
    )
    if not releases:
        raise GraphConfigurationIntegrityError("graph configuration has no release")
    ids = [release.id for release in releases]

    mappings: dict[int, dict[str, int]] = {release_id: {} for release_id in ids}
    for release_id, agent_key, revision_id in session.execute(
        select(
            GraphReleaseAgent.graph_release_id,
            GraphReleaseAgent.agent_key,
            GraphReleaseAgent.agent_definition_revision_id,
        ).where(GraphReleaseAgent.graph_release_id.in_(ids))
    ):
        mappings[release_id][agent_key] = revision_id
    if any(set(mapping) != _EXPECTED_AGENT_KEYS for mapping in mappings.values()):
        raise GraphConfigurationIntegrityError("release mapping rows are incomplete")

    active = [release for release in releases if release.effective_to is None]
    if len(active) != 1:
        raise GraphConfigurationIntegrityError(
            "graph configuration must have exactly one active release"
        )

    refs = {release.id: ReleaseRef(release.id, release.version_number) for release in releases}

    def ref(release_id: int | None) -> ReleaseRef | None:
        if release_id is None:
            return None
        if release_id not in refs:
            raise GraphConfigurationIntegrityError(
                "release lineage references a release outside the release set"
            )
        return refs[release_id]

    restored_by: dict[int, list[ReleaseRef]] = {release_id: [] for release_id in ids}
    for release in sorted(releases, key=lambda row: row.version_number):
        source = ref(release.restored_from_release_id)
        if source is not None:
            restored_by[source.release_id].append(refs[release.id])

    entries: list[ReleaseHistoryEntry] = []
    for release in releases:
        previous = ref(release.previous_release_id)
        own = mappings[release.id]
        prior = None if previous is None else mappings[previous.release_id]
        changed = tuple(
            key for key in GRAPH_V1_AGENT_KEYS if prior is None or prior[key] != own[key]
        )
        entries.append(
            ReleaseHistoryEntry(
                release_id=release.id,
                version_number=release.version_number,
                is_active=release.effective_to is None,
                release_note=release.release_note,
                published_by=release.published_by,
                published_at=release.published_at,
                effective_from=release.effective_from,
                effective_to=release.effective_to,
                previous=previous,
                restored_from=ref(release.restored_from_release_id),
                restored_by=tuple(restored_by[release.id]),
                changed_agent_keys=changed,
            )
        )
    return _HistorySnapshot(
        entries=tuple(entries),
        refs=MappingProxyType(refs),
        mappings=MappingProxyType(
            {release_id: MappingProxyType(mapping) for release_id, mapping in mappings.items()}
        ),
    )


def _release_definitions(
    session: Session, mapping: Mapping[str, int]
) -> Mapping[AgentKey, ReleaseDefinition]:
    """One release's exact seven definitions, hash-validated, read-only.

    ``mapping`` is one entry of ``_HistorySnapshot.mappings`` (already checked to
    name exactly the seven roles).  Each revision must exist, belong to its own
    role, and match its persisted hash; any failure is an integrity error.
    """
    revisions = {
        revision.id: revision
        for revision in session.scalars(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.id.in_(list(mapping.values()))
            )
        )
    }
    definitions: dict[AgentKey, ReleaseDefinition] = {}
    for agent_key in GRAPH_V1_AGENT_KEYS:
        revision = revisions.get(mapping[agent_key])
        if revision is None:
            raise GraphConfigurationIntegrityError("release mapping rows are incomplete")
        if revision.agent_key != agent_key:
            raise GraphConfigurationIntegrityError(
                f"release mapping for {agent_key} names another role's revision"
            )
        content = validate_definition_hash(
            revision,
            expected_hash=revision.content_hash,
            label=f"revision {revision.id}",
        )
        definitions[agent_key] = ReleaseDefinition(
            agent_key=agent_key,
            agent_definition_revision_id=revision.id,
            content_hash=revision.content_hash,
            content=content,
        )
    return MappingProxyType(definitions)


def list_release_history(session: Session) -> tuple[ReleaseHistoryEntry, ...]:
    """Every Graph Release, newest first, as of this function's first statement."""
    return _read_history(session).entries


def read_release_detail(session: Session, *, version_number: int) -> ReleaseDetail:
    """One release's entry, exact seven definitions, and linked candidate evidence."""
    snapshot = _read_history(session)
    entry = next(
        (e for e in snapshot.entries if e.version_number == version_number), None
    )
    if entry is None:
        raise GraphVersionNotFound(version_number)
    definitions = _release_definitions(session, snapshot.mappings[entry.release_id])

    rows = session.execute(
        select(GraphReleaseTestRun, AgentTestRun)
        .join(AgentTestRun, AgentTestRun.id == GraphReleaseTestRun.agent_test_run_id)
        .where(
            GraphReleaseTestRun.graph_release_id == entry.release_id,
            AgentTestRun.run_kind == "candidate",
        )
    ).all()
    linked = session.scalar(
        select(func.count())
        .select_from(GraphReleaseTestRun)
        .where(GraphReleaseTestRun.graph_release_id == entry.release_id)
    )
    if linked != len(rows):
        raise GraphConfigurationIntegrityError(
            "release evidence references a non-candidate run"
        )

    evidence: list[ReleaseEvidence] = []
    for link, run in rows:
        source = None
        if link.source_release_id is not None:
            source = snapshot.refs.get(link.source_release_id)
            if source is None:
                raise GraphConfigurationIntegrityError(
                    "release evidence names a source outside the release set"
                )
        evidence.append(
            ReleaseEvidence(
                agent_test_run_id=run.id,
                agent_key=run.agent_key,
                test_case_id=run.test_case_id,
                test_case_version=run.test_case_version,
                evidence_kind=link.evidence_kind,
                source=source,
                verdict=run.verdict,
                verdict_reviewer=run.verdict_reviewer,
                verdict_at=run.verdict_at,
                execution_status=run.execution_status,
                deterministic_checks_passed=run.deterministic_checks_passed,
                run_at=run.run_at,
            )
        )
    evidence.sort(
        key=lambda e: (_AGENT_KEY_ORDER[e.agent_key], e.test_case_id, e.agent_test_run_id)
    )
    return ReleaseDetail(
        entry=entry,
        definitions=definitions,
        evidence=tuple(evidence),
    )
