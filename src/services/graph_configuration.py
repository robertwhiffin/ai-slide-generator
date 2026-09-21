"""Atomic startup persistence for the shared Graph Configuration aggregate.

The frozen v1 data is deliberately resolved only after the transaction has taken the
bootstrap lock and proved that no release exists. Existing deployments validate their
current persisted aggregate without importing or comparing against that snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select, text, true

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    AssemblyRules,
    ContentIdentity,
    DefinitionContent,
    GraphV1Manifest,
    ModelConfiguration,
    SchemaOverlay,
    definition_content_hash,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker


_BOOTSTRAP_LOCK_NAME = "tellr:graph-configuration-bootstrap:v1"
_EXPECTED_AGENT_KEYS = frozenset(GRAPH_V1_AGENT_KEYS)

REQUIRED_SMOKE_PAYLOADS: dict[str, dict[str, object]] = {
    "architect": {
        "session_id": "synthetic-architect",
        "conversation": [
            {"role": "user", "content": "Create a three-slide demo roadmap."}
        ],
        "message": "Create a three-slide demo roadmap.",
        "current_deck_spec": None,
        "committed_slide_count": 0,
        "previous_deck_review": None,
        "available_design_contract": None,
        "template_sections": [],
        "resolved_style": "Synthetic demo style",
        "design_system_library": [],
    },
    "data_analyst": {
        "session_id": "synthetic-data-analyst",
        "data_request": "Summarize synthetic quarterly revenue of 10, 12, and 15.",
        "deck_purpose": "Demonstrate synthetic growth",
    },
    "builder": {
        "session_id": "synthetic-builder",
        "turn_id": "synthetic-turn",
        "initiated_by": "system:bootstrap",
        "position": 1,
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "assumes": [],
        "hands_off": ["Phase 2 follows Phase 1"],
        "design_contract": {"design_system_id": None, "template_id": None},
        "resolved_data": {"facts": [], "figures": [], "sources": []},
        "section_html": "<section><h1>Roadmap</h1></section>",
        "section_css": ".slide { width: 1280px; height: 720px; }",
        "resolved_style": "Synthetic demo style",
        "design_system_active": False,
    },
    "build_reviewer": {
        "position": 1,
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
        "resolved_data": {"facts": [], "figures": [], "sources": []},
        "html": "<div class='slide'><h1>Synthetic roadmap</h1></div>",
        "scripts": "",
        "deck_brief": {
            "purpose": "Demonstrate a synthetic roadmap",
            "audience": "Demo audience",
        },
    },
    "fixer": {
        "position": 1,
        "finding": {
            "criterion": "content_overflow",
            "message": "Synthetic title overflows",
        },
        "html": "<div class='slide'><h1>Synthetic roadmap title</h1></div>",
        "scripts": "",
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
    },
    "fix_reviewer": {
        "position": 1,
        "finding": {
            "criterion": "content_overflow",
            "message": "Synthetic title overflows",
        },
        "change_summary": "Reduced the synthetic title size",
        "html": "<div class='slide'><h1 class='small'>Synthetic roadmap</h1></div>",
        "scripts": "",
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
    },
    "deck_reviewer": {
        "session_id": "synthetic-deck-reviewer",
        "narrative_arc": ["Context", "Decision", "Action"],
        "call_to_action": "Approve the synthetic roadmap",
        "slide_count": 2,
        "slides": [
            {
                "position": 1,
                "html": "<div class='slide'><h1>Context</h1></div>",
            },
            {
                "position": 2,
                "html": "<div class='slide'><h1>Action</h1></div>",
            },
        ],
    },
}


class GraphConfigurationIntegrityError(RuntimeError):
    """Persisted graph configuration is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    release_id: int
    version_number: int


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


@dataclass(frozen=True)
class PublishedDefinitionSnapshot:
    revision_id: int
    content_hash: str
    definition_version: int
    prompt_text: str
    model: ModelConfiguration
    schema_overlay: SchemaOverlay
    assembly_rules: AssemblyRules
    protected_assembly: ContentIdentity
    schema_contract: ContentIdentity


@dataclass(frozen=True)
class DraftDefinitionSnapshot:
    base_revision_id: int
    candidate_hash: str
    definition_version: int
    prompt_text: str
    model: ModelConfiguration
    schema_overlay: SchemaOverlay
    assembly_rules: AssemblyRules
    protected_assembly: ContentIdentity
    schema_contract: ContentIdentity


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


class GraphConfiguration:
    """Create v1 once or validate the complete current persisted aggregate."""

    def read_workbench(self, session: Session) -> GraphWorkbenchSnapshot:
        """Read and verify one coherent current workbench aggregate.

        The first statement takes shared locks on both mutable aggregate parents.
        Draft and publication writers must take conflicting parent locks before
        mutating children, preventing a READ COMMITTED reader from assembling a
        parent from one state and child definitions from another.
        """
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
            content = self._validate_definition_hash(
                revision,
                expected_hash=revision.content_hash,
                label=f"revision {revision.id}",
            )
            published[mapping.agent_key] = (revision, content)

        draft_rows = list(
            session.scalars(select(GraphDraftAgent))
        )
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
            content = self._validate_definition_hash(
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
                    published=self._published_snapshot(revision, published_content),
                    draft=self._draft_snapshot(
                        draft_row,
                        draft_content,
                        base_revision_id=revision.id,
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

    @staticmethod
    def _published_snapshot(
        revision: AgentDefinitionRevision,
        content: DefinitionContent,
    ) -> PublishedDefinitionSnapshot:
        return PublishedDefinitionSnapshot(
            revision_id=revision.id,
            content_hash=revision.content_hash,
            definition_version=content.definition_version,
            prompt_text=content.prompt_text,
            model=content.model,
            schema_overlay=content.schema_overlay,
            assembly_rules=content.assembly_rules,
            protected_assembly=content.protected_assembly,
            schema_contract=content.schema_contract,
        )

    @staticmethod
    def _draft_snapshot(
        draft: GraphDraftAgent,
        content: DefinitionContent,
        *,
        base_revision_id: int,
    ) -> DraftDefinitionSnapshot:
        return DraftDefinitionSnapshot(
            base_revision_id=base_revision_id,
            candidate_hash=draft.candidate_hash,
            definition_version=content.definition_version,
            prompt_text=content.prompt_text,
            model=content.model,
            schema_overlay=content.schema_overlay,
            assembly_rules=content.assembly_rules,
            protected_assembly=content.protected_assembly,
            schema_contract=content.schema_contract,
        )

    def bootstrap_v1(
        self,
        session_factory: sessionmaker,
        *,
        actor: str = "system:bootstrap",
        manifest_loader: Callable[[], GraphV1Manifest] | None = None,
    ) -> BootstrapResult:
        with session_factory.begin() as session:
            self._take_bootstrap_lock(session)
            releases_exist = bool(
                session.scalar(select(func.count()).select_from(GraphRelease))
            )
            if releases_exist:
                return self._validate_current_graph(session)

            self._reject_partial_state_without_release(session)
            self._validate_unreferenced_revisions(session)
            if manifest_loader is None:
                from src.services.graph_definition_manifest import load_graph_v1_manifest

                manifest_loader = load_graph_v1_manifest
            return self._insert_complete_v1(session, manifest_loader(), actor)

    def _take_bootstrap_lock(self, session: Session) -> None:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
                {"lock_name": _BOOTSTRAP_LOCK_NAME},
            )

    @staticmethod
    def _database_timestamp(session: Session) -> datetime:
        timestamp = session.scalar(select(func.current_timestamp()))
        if timestamp is None:
            raise GraphConfigurationIntegrityError(
                "database did not return a transaction timestamp"
            )
        if timestamp.tzinfo is None:
            # SQLite returns CURRENT_TIMESTAMP without an offset even though the value
            # is UTC. PostgreSQL returns a timezone-aware timestamptz unchanged.
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    @staticmethod
    def _content_from_revision(row: AgentDefinitionRevision) -> DefinitionContent:
        return DefinitionContent.model_validate(
            {
                "agent_key": row.agent_key,
                "definition_version": row.definition_version,
                "prompt_text": row.prompt_text,
                "model": {
                    "endpoint_name": row.endpoint_name,
                    "temperature": row.temperature,
                    "max_tokens": row.max_tokens,
                    "top_p": row.top_p,
                },
                "schema_overlay": row.schema_overlay,
                "assembly_rules": row.assembly_rules,
                "protected_assembly": {
                    "version": row.protected_assembly_version,
                    "digest": row.protected_assembly_digest,
                },
                "schema_contract": {
                    "version": row.schema_contract_version,
                    "digest": row.schema_contract_digest,
                },
            }
        )

    @staticmethod
    def _content_from_draft(row: GraphDraftAgent) -> DefinitionContent:
        return DefinitionContent.model_validate(
            {
                "agent_key": row.agent_key,
                "definition_version": row.definition_version,
                "prompt_text": row.prompt_text,
                "model": {
                    "endpoint_name": row.endpoint_name,
                    "temperature": row.temperature,
                    "max_tokens": row.max_tokens,
                    "top_p": row.top_p,
                },
                "schema_overlay": row.schema_overlay,
                "assembly_rules": row.assembly_rules,
                "protected_assembly": {
                    "version": row.protected_assembly_version,
                    "digest": row.protected_assembly_digest,
                },
                "schema_contract": {
                    "version": row.schema_contract_version,
                    "digest": row.schema_contract_digest,
                },
            }
        )

    @staticmethod
    def _revision_from_definition(
        definition: DefinitionContent,
        *,
        actor: str,
        timestamp: datetime,
    ) -> AgentDefinitionRevision:
        return AgentDefinitionRevision(
            agent_key=definition.agent_key,
            definition_version=definition.definition_version,
            content_hash=definition_content_hash(definition),
            prompt_text=definition.prompt_text,
            endpoint_name=definition.model.endpoint_name,
            temperature=definition.model.temperature,
            max_tokens=definition.model.max_tokens,
            top_p=definition.model.top_p,
            schema_overlay=definition.schema_overlay.model_dump(mode="json"),
            assembly_rules=definition.assembly_rules.model_dump(mode="json"),
            protected_assembly_version=definition.protected_assembly.version,
            protected_assembly_digest=definition.protected_assembly.digest,
            schema_contract_version=definition.schema_contract.version,
            schema_contract_digest=definition.schema_contract.digest,
            created_by=actor,
            created_at=timestamp,
        )

    @staticmethod
    def _draft_from_definition(
        definition: DefinitionContent,
        *,
        draft_id: int,
    ) -> GraphDraftAgent:
        return GraphDraftAgent(
            graph_draft_id=draft_id,
            agent_key=definition.agent_key,
            candidate_hash=definition_content_hash(definition),
            definition_version=definition.definition_version,
            prompt_text=definition.prompt_text,
            endpoint_name=definition.model.endpoint_name,
            temperature=definition.model.temperature,
            max_tokens=definition.model.max_tokens,
            top_p=definition.model.top_p,
            schema_overlay=definition.schema_overlay.model_dump(mode="json"),
            assembly_rules=definition.assembly_rules.model_dump(mode="json"),
            protected_assembly_version=definition.protected_assembly.version,
            protected_assembly_digest=definition.protected_assembly.digest,
            schema_contract_version=definition.schema_contract.version,
            schema_contract_digest=definition.schema_contract.digest,
        )

    def _validate_definition_hash(
        self,
        row: AgentDefinitionRevision | GraphDraftAgent,
        *,
        expected_hash: str,
        label: str,
    ) -> DefinitionContent:
        try:
            if isinstance(row, AgentDefinitionRevision):
                content = self._content_from_revision(row)
            else:
                content = self._content_from_draft(row)
            actual_hash = definition_content_hash(content)
        except (TypeError, ValueError) as exc:
            raise GraphConfigurationIntegrityError(
                f"{label} has invalid semantic content"
            ) from exc
        if actual_hash != expected_hash:
            raise GraphConfigurationIntegrityError(
                f"{label} content hash does not match persisted content"
            )
        return content

    def _validate_unreferenced_revisions(self, session: Session) -> None:
        for revision in session.scalars(select(AgentDefinitionRevision)):
            self._validate_definition_hash(
                revision,
                expected_hash=revision.content_hash,
                label=f"revision {revision.id}",
            )

    @staticmethod
    def _reject_partial_state_without_release(session: Session) -> None:
        artifact_tables = (
            GraphReleaseAgent,
            GraphDraft,
            GraphDraftAgent,
            AgentTestCase,
        )
        partial = [
            table.__tablename__
            for table in artifact_tables
            if session.scalar(select(func.count()).select_from(table))
        ]
        if partial:
            raise GraphConfigurationIntegrityError(
                "graph artifacts exist without a release: " + ", ".join(partial)
            )

    def _validate_current_graph(self, session: Session) -> BootstrapResult:
        releases = list(session.scalars(select(GraphRelease).order_by(GraphRelease.id)))
        active = [release for release in releases if release.effective_to is None]
        if len(active) != 1:
            raise GraphConfigurationIntegrityError(
                "graph configuration must have exactly one active release"
            )

        all_mappings = list(session.scalars(select(GraphReleaseAgent)))
        if len(all_mappings) != len(releases) * len(_EXPECTED_AGENT_KEYS):
            raise GraphConfigurationIntegrityError(
                "release mapping rows do not belong to the complete release history"
            )
        for release in releases:
            mappings = [
                mapping
                for mapping in all_mappings
                if mapping.graph_release_id == release.id
            ]
            keys = {mapping.agent_key for mapping in mappings}
            if len(mappings) != len(_EXPECTED_AGENT_KEYS) or keys != _EXPECTED_AGENT_KEYS:
                raise GraphConfigurationIntegrityError(
                    f"release {release.id} does not have the exact role mapping set"
                )
            for mapping in mappings:
                revision = session.get(
                    AgentDefinitionRevision, mapping.agent_definition_revision_id
                )
                if revision is None or revision.agent_key != mapping.agent_key:
                    raise GraphConfigurationIntegrityError(
                        f"release {release.id} has a role-incompatible mapping"
                    )
                self._validate_definition_hash(
                    revision,
                    expected_hash=revision.content_hash,
                    label=f"revision {revision.id}",
                )

        drafts = list(session.scalars(select(GraphDraft)))
        if len(drafts) != 1 or drafts[0].id != 1:
            raise GraphConfigurationIntegrityError(
                "graph configuration must have exactly one singleton draft"
            )
        current = active[0]
        if drafts[0].base_release_id != current.id:
            raise GraphConfigurationIntegrityError(
                "shared draft is not based on the current active release"
            )

        draft_agents = list(session.scalars(select(GraphDraftAgent)))
        draft_keys = {row.agent_key for row in draft_agents}
        if (
            len(draft_agents) != len(_EXPECTED_AGENT_KEYS)
            or draft_keys != _EXPECTED_AGENT_KEYS
            or any(row.graph_draft_id != 1 for row in draft_agents)
        ):
            raise GraphConfigurationIntegrityError(
                "shared draft does not have the exact role key set"
            )
        for draft_agent in draft_agents:
            self._validate_definition_hash(
                draft_agent,
                expected_hash=draft_agent.candidate_hash,
                label=f"draft role {draft_agent.agent_key}",
            )

        required_case_keys = set(
            session.scalars(
                select(AgentTestCase.agent_key).where(
                    AgentTestCase.is_active.is_(True),
                    AgentTestCase.is_required.is_(True),
                )
            )
        )
        if not _EXPECTED_AGENT_KEYS.issubset(required_case_keys):
            raise GraphConfigurationIntegrityError(
                "active required Agent Test Cases do not cover every graph role"
            )
        return BootstrapResult(False, current.id, current.version_number)

    def _insert_complete_v1(
        self,
        session: Session,
        manifest: GraphV1Manifest,
        actor: str,
    ) -> BootstrapResult:
        manifest.assert_complete(GRAPH_V1_AGENT_KEYS)
        timestamp = self._database_timestamp(session)
        definitions = {item.agent_key: item for item in manifest.definitions}
        if set(definitions) != _EXPECTED_AGENT_KEYS:
            raise GraphConfigurationIntegrityError(
                "Graph Version 1 manifest does not contain the exact role set"
            )

        revisions: dict[str, AgentDefinitionRevision] = {}
        for agent_key in GRAPH_V1_AGENT_KEYS:
            definition = definitions[agent_key]
            content_hash = definition_content_hash(definition)
            revision = session.scalar(
                select(AgentDefinitionRevision).where(
                    AgentDefinitionRevision.agent_key == agent_key,
                    AgentDefinitionRevision.content_hash == content_hash,
                )
            )
            if revision is None:
                revision = self._revision_from_definition(
                    definition, actor=actor, timestamp=timestamp
                )
                session.add(revision)
            else:
                existing = self._validate_definition_hash(
                    revision,
                    expected_hash=content_hash,
                    label=f"reusable revision {revision.id}",
                )
                if existing.canonical_payload() != definition.canonical_payload():
                    raise GraphConfigurationIntegrityError(
                        f"reusable revision {revision.id} does not match its hash"
                    )
            revisions[agent_key] = revision
        session.flush()
        if set(revisions) != _EXPECTED_AGENT_KEYS or any(
            revision.id is None for revision in revisions.values()
        ):
            raise GraphConfigurationIntegrityError(
                "Graph Version 1 revision dictionary is incomplete"
            )

        release = GraphRelease(
            version_number=1,
            release_note="Bootstrap Graph Version 1",
            published_by=actor,
            published_at=timestamp,
            effective_from=timestamp,
        )
        session.add(release)
        session.flush()
        session.add_all(
            GraphReleaseAgent(
                graph_release_id=release.id,
                agent_key=agent_key,
                agent_definition_revision_id=revisions[agent_key].id,
            )
            for agent_key in GRAPH_V1_AGENT_KEYS
        )
        session.flush()
        mapping_rows = list(
            session.scalars(
                select(GraphReleaseAgent).where(
                    GraphReleaseAgent.graph_release_id == release.id
                )
            )
        )
        if {row.agent_key: row.agent_definition_revision_id for row in mapping_rows} != {
            key: revisions[key].id for key in GRAPH_V1_AGENT_KEYS
        }:
            raise GraphConfigurationIntegrityError(
                "Graph Version 1 release mapping dictionary is incomplete"
            )

        self._insert_draft_and_cases(
            session,
            release=release,
            definitions=definitions,
            actor=actor,
            timestamp=timestamp,
        )
        return BootstrapResult(True, release.id, release.version_number)

    def _insert_draft_and_cases(
        self,
        session: Session,
        *,
        release: GraphRelease,
        definitions: dict[str, DefinitionContent],
        actor: str,
        timestamp: datetime,
    ) -> None:
        draft = GraphDraft(
            id=1,
            base_release_id=release.id,
            lock_version=0,
            updated_by=actor,
            updated_at=timestamp,
        )
        session.add(draft)
        session.add_all(
            self._draft_from_definition(definitions[key], draft_id=draft.id)
            for key in GRAPH_V1_AGENT_KEYS
        )
        session.add_all(
            AgentTestCase(
                agent_key=key,
                name=f"{key}_required_smoke_v1",
                version=1,
                is_active=True,
                is_required=True,
                synthetic_payload=REQUIRED_SMOKE_PAYLOADS[key],
                assembly_context={"design_system_active": False},
                created_by=actor,
                created_at=timestamp,
                updated_by=actor,
                updated_at=timestamp,
            )
            for key in GRAPH_V1_AGENT_KEYS
        )
        session.flush()

        draft_rows = list(
            session.scalars(
                select(GraphDraftAgent).where(GraphDraftAgent.graph_draft_id == draft.id)
            )
        )
        if {row.agent_key: row.candidate_hash for row in draft_rows} != {
            key: definition_content_hash(definitions[key])
            for key in GRAPH_V1_AGENT_KEYS
        }:
            raise GraphConfigurationIntegrityError(
                "Graph Version 1 draft dictionary is incomplete"
            )
        cases = list(
            session.scalars(
                select(AgentTestCase).where(
                    AgentTestCase.version == 1,
                    AgentTestCase.is_active.is_(True),
                    AgentTestCase.is_required.is_(True),
                )
            )
        )
        if {case.agent_key: case.synthetic_payload for case in cases} != (
            REQUIRED_SMOKE_PAYLOADS
        ):
            raise GraphConfigurationIntegrityError(
                "Graph Version 1 required smoke-case dictionary is incomplete"
            )


def bootstrap_graph_configuration(session_factory: sessionmaker) -> BootstrapResult:
    """Packaged-startup wrapper for the atomic bootstrap service."""
    return GraphConfiguration().bootstrap_v1(session_factory)
