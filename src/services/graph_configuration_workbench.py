"""Locked, coherent read model for the Agent Definition workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select, true

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration_content import (
    GraphConfigurationIntegrityError,
    validate_definition_hash,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    AssemblyRules,
    ContentIdentity,
    DefinitionContent,
    ModelConfiguration,
    SchemaOverlay,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_EXPECTED_AGENT_KEYS = frozenset(GRAPH_V1_AGENT_KEYS)


@dataclass(frozen=True)
class ActiveReleaseSnapshot:
    release_id: int
    version_number: int
    previous_release_id: int | None
    restored_from_release_id: int | None
    release_note: str
    published_by: str
    published_at: datetime
    effective_from: datetime
    effective_to: datetime | None


@dataclass(frozen=True)
class DraftMetadataSnapshot:
    draft_id: int
    base_release_id: int
    base_version_number: int
    lock_version: int
    updated_by: str
    updated_at: datetime


class _DefinitionContentSnapshot:
    """Compatibility view over the single content record held by each snapshot."""

    content: DefinitionContent

    @property
    def definition_version(self) -> int:
        return self.content.definition_version

    @property
    def prompt_text(self) -> str:
        return self.content.prompt_text

    @property
    def model(self) -> ModelConfiguration:
        return self.content.model

    @property
    def schema_overlay(self) -> SchemaOverlay:
        return self.content.schema_overlay

    @property
    def assembly_rules(self) -> AssemblyRules:
        return self.content.assembly_rules

    @property
    def protected_assembly(self) -> ContentIdentity:
        return self.content.protected_assembly

    @property
    def schema_contract(self) -> ContentIdentity:
        return self.content.schema_contract


@dataclass(frozen=True)
class PublishedDefinitionSnapshot(_DefinitionContentSnapshot):
    revision_id: int
    content_hash: str
    content: DefinitionContent


@dataclass(frozen=True)
class DraftDefinitionSnapshot(_DefinitionContentSnapshot):
    base_revision_id: int
    candidate_hash: str
    content: DefinitionContent


@dataclass(frozen=True)
class ModelAgentNodeSnapshot:
    agent_key: AgentKey
    display_name: str
    execution_kind: Literal["model"]
    editable: Literal[True]
    changed: bool
    published: PublishedDefinitionSnapshot
    draft: DraftDefinitionSnapshot
    read_only_reason: None


@dataclass(frozen=True)
class DeterministicAgentNodeSnapshot:
    agent_key: Literal["foreman"]
    display_name: Literal["Foreman"]
    execution_kind: Literal["deterministic"]
    editable: Literal[False]
    changed: Literal[False]
    published: None
    draft: None
    read_only_reason: str


@dataclass(frozen=True)
class GraphWorkbenchSnapshot:
    active_release: ActiveReleaseSnapshot
    draft: DraftMetadataSnapshot
    nodes: tuple[ModelAgentNodeSnapshot | DeterministicAgentNodeSnapshot, ...]


_WORKBENCH_ORDER = (
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "foreman",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
)
_DISPLAY_NAMES = {
    "architect": "Architect",
    "data_analyst": "Data Analyst",
    "builder": "Builder",
    "build_reviewer": "Build Reviewer",
    "foreman": "Foreman",
    "fixer": "Fixer",
    "fix_reviewer": "Fix Reviewer",
    "deck_reviewer": "Deck Reviewer",
}
_FOREMAN_READ_ONLY_REASON = (
    "Foreman is deterministic scheduling and routing code; "
    "it has no Agent Definition."
)


class _GraphConfigurationWorkbench:
    """Read and verify one coherent current workbench aggregate."""

    def read_workbench(self, session: Session) -> GraphWorkbenchSnapshot:
        """Read under shared parent locks so parent and children cannot diverge."""
        parent_rows = session.execute(
            select(GraphRelease, GraphDraft)
            .select_from(GraphRelease)
            .join(GraphDraft, true())
            .where(GraphRelease.effective_to.is_(None))
            .with_for_update(read=True, of=(GraphRelease, GraphDraft))
        ).all()
        if len(parent_rows) != 1:
            active_count = session.scalar(
                select(func.count())
                .select_from(GraphRelease)
                .where(GraphRelease.effective_to.is_(None))
            )
            if active_count != 1:
                raise GraphConfigurationIntegrityError(
                    "graph configuration must have exactly one active release"
                )
            drafts = list(session.scalars(select(GraphDraft)))
            if len(drafts) != 1 or drafts[0].id != 1:
                raise GraphConfigurationIntegrityError(
                    "graph configuration must have exactly one singleton draft"
                )
            raise GraphConfigurationIntegrityError(
                "graph configuration parent snapshot is inconsistent"
            )

        release, draft = parent_rows[0]
        if draft.id != 1:
            raise GraphConfigurationIntegrityError(
                "graph configuration must have exactly one singleton draft"
            )
        if draft.base_release_id != release.id:
            raise GraphConfigurationIntegrityError(
                "shared draft is not based on the current active release"
            )

        mapping_rows = session.execute(
            select(GraphReleaseAgent, AgentDefinitionRevision)
            .outerjoin(
                AgentDefinitionRevision,
                AgentDefinitionRevision.id
                == GraphReleaseAgent.agent_definition_revision_id,
            )
            .where(GraphReleaseAgent.graph_release_id == release.id)
        ).all()
        mapping_keys = {mapping.agent_key for mapping, _revision in mapping_rows}
        if (
            len(mapping_rows) != len(_EXPECTED_AGENT_KEYS)
            or mapping_keys != _EXPECTED_AGENT_KEYS
        ):
            raise GraphConfigurationIntegrityError(
                "active release does not have the exact role mapping set"
            )

        published: dict[str, tuple[AgentDefinitionRevision, DefinitionContent]] = {}
        for mapping, revision in mapping_rows:
            if revision is None or revision.agent_key != mapping.agent_key:
                raise GraphConfigurationIntegrityError(
                    "active release has a role-incompatible mapping"
                )
            content = validate_definition_hash(
                revision,
                expected_hash=revision.content_hash,
                label=f"revision {revision.id}",
            )
            published[mapping.agent_key] = (revision, content)

        draft_rows = list(session.scalars(select(GraphDraftAgent)))
        if any(row.graph_draft_id != draft.id for row in draft_rows):
            raise GraphConfigurationIntegrityError(
                "shared draft agents must all belong to the singleton draft"
            )
        draft_keys = {row.agent_key for row in draft_rows}
        if (
            len(draft_rows) != len(_EXPECTED_AGENT_KEYS)
            or draft_keys != _EXPECTED_AGENT_KEYS
        ):
            raise GraphConfigurationIntegrityError(
                "shared draft does not have the exact role key set"
            )
        candidates: dict[str, tuple[GraphDraftAgent, DefinitionContent]] = {}
        for draft_row in draft_rows:
            content = validate_definition_hash(
                draft_row,
                expected_hash=draft_row.candidate_hash,
                label=f"draft role {draft_row.agent_key}",
            )
            candidates[draft_row.agent_key] = (draft_row, content)

        nodes: list[ModelAgentNodeSnapshot | DeterministicAgentNodeSnapshot] = []
        for agent_key in _WORKBENCH_ORDER:
            if agent_key == "foreman":
                nodes.append(
                    DeterministicAgentNodeSnapshot(
                        agent_key="foreman",
                        display_name="Foreman",
                        execution_kind="deterministic",
                        editable=False,
                        changed=False,
                        published=None,
                        draft=None,
                        read_only_reason=_FOREMAN_READ_ONLY_REASON,
                    )
                )
                continue
            revision, published_content = published[agent_key]
            draft_row, draft_content = candidates[agent_key]
            nodes.append(
                ModelAgentNodeSnapshot(
                    agent_key=agent_key,
                    display_name=_DISPLAY_NAMES[agent_key],
                    execution_kind="model",
                    editable=True,
                    changed=draft_row.candidate_hash != revision.content_hash,
                    published=PublishedDefinitionSnapshot(
                        revision_id=revision.id,
                        content_hash=revision.content_hash,
                        content=published_content,
                    ),
                    draft=DraftDefinitionSnapshot(
                        base_revision_id=revision.id,
                        candidate_hash=draft_row.candidate_hash,
                        content=draft_content,
                    ),
                    read_only_reason=None,
                )
            )

        return GraphWorkbenchSnapshot(
            active_release=ActiveReleaseSnapshot(
                release_id=release.id,
                version_number=release.version_number,
                previous_release_id=release.previous_release_id,
                restored_from_release_id=release.restored_from_release_id,
                release_note=release.release_note,
                published_by=release.published_by,
                published_at=release.published_at,
                effective_from=release.effective_from,
                effective_to=release.effective_to,
            ),
            draft=DraftMetadataSnapshot(
                draft_id=draft.id,
                base_release_id=draft.base_release_id,
                base_version_number=release.version_number,
                lock_version=draft.lock_version,
                updated_by=draft.updated_by,
                updated_at=draft.updated_at,
            ),
            nodes=tuple(nodes),
        )
