"""Atomic startup persistence for the shared Graph Configuration aggregate.

The frozen v1 data is deliberately resolved only after the transaction has taken the
bootstrap lock and proved that no release exists. Existing deployments validate their
current persisted aggregate without importing or comparing against that snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text

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
    DefinitionContent,
    GraphV1Manifest,
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


class GraphConfiguration:
    """Create v1 once or validate the complete current persisted aggregate."""

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
