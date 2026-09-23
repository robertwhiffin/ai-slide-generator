from __future__ import annotations

import copy
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401
import src.services.persisted_graph_release as persisted_graph_release_module
from src.core.database import Base
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphRelease,
    GraphReleaseAgent,
)
from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime import AgentAssemblyContext, AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AssemblyRulesV1,
    AssemblyRulesV2,
    DefinitionContent,
    definition_content_hash,
)
from src.services.persisted_graph_release import (
    GraphReleaseIncompleteError,
    GraphReleaseNotFoundError,
    PersistedConfigurationUnavailableError,
    PersistedGraphReleaseLoader,
    PinnedInvocationEndpointError,
)
from src.services.prompt_assembler import V2_PROTECTED_ASSEMBLY_IDENTITY


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda conn, _record: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def v1_release_id(session_factory) -> int:
    return GraphConfiguration().bootstrap_v1(session_factory).release_id


def _release_rows(session_factory, release_id: int) -> list[tuple[Any, Any, Any]]:
    with session_factory() as db:
        return list(
            db.execute(
                select(GraphRelease, GraphReleaseAgent, AgentDefinitionRevision)
                .outerjoin(
                    GraphReleaseAgent,
                    GraphReleaseAgent.graph_release_id == GraphRelease.id,
                )
                .outerjoin(
                    AgentDefinitionRevision,
                    AgentDefinitionRevision.id
                    == GraphReleaseAgent.agent_definition_revision_id,
                )
                .where(GraphRelease.id == release_id)
            ).all()
        )


class _RowsSession(AbstractContextManager):
    def __init__(self, rows: list[tuple[Any, Any, Any]]) -> None:
        self._rows = rows

    def execute(self, _statement):
        return _RowsResult(self._rows)

    def __exit__(self, *_args) -> None:
        return None


class _RowsResult:
    def __init__(self, rows: list[tuple[Any, Any, Any]]) -> None:
        self._rows = rows

    def all(self):
        return self._rows


def _rows_factory(rows: list[tuple[Any, Any, Any]]) -> Callable[[], _RowsSession]:
    return lambda: _RowsSession(rows)


def test_resolves_the_complete_typed_v1_snapshot_and_caches_exact_release_id(
    session_factory, v1_release_id, monkeypatch
):
    loader = PersistedGraphReleaseLoader(session_factory=session_factory)
    statements = []
    original_factory = loader._session_factory

    class CountingSession(AbstractContextManager):
        def __init__(self) -> None:
            self._session = original_factory()

        def execute(self, statement):
            statements.append(statement)
            return self._session.execute(statement)

        def __exit__(self, *args) -> None:
            self._session.close()
            return None

    monkeypatch.setattr(loader, "_session_factory", CountingSession)

    resolved = {
        key: loader.resolve(v1_release_id, key) for key in GRAPH_V1_AGENT_KEYS
    }
    again = loader.resolve(v1_release_id, "architect")

    assert len(statements) == 1
    query = str(statements[0])
    assert "FROM graph_release LEFT OUTER JOIN graph_release_agent" in query
    assert "effective_to" not in query.partition("WHERE")[2]
    assert set(resolved) == set(GRAPH_V1_AGENT_KEYS)
    assert again is resolved["architect"]
    for key, definition in resolved.items():
        assert definition.graph_version == 1
        assert definition.graph_release_id == v1_release_id
        assert definition.agent_key == key
        assert isinstance(definition.content, DefinitionContent)
        assert isinstance(definition.content.assembly_rules, AssemblyRulesV1)
        assert definition.content.agent_key == key
        assert definition.content_hash == definition.content_hash.lower()


def test_loader_parses_persisted_v1_and_v2_assembly_wire_values(
    session_factory, v1_release_id
):
    v1 = PersistedGraphReleaseLoader(session_factory=session_factory).resolve(
        v1_release_id, "architect"
    )
    assert isinstance(v1.content.assembly_rules, AssemblyRulesV1)

    with session_factory.begin() as db:
        revision = db.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == "architect"
            )
        )
        assert revision is not None
        revision.assembly_rules = {
            "format_version": 2,
            "custom_blocks": [
                {
                    "kind": "custom_text",
                    "block_id": "00000000-0000-0000-0000-000000000001",
                    "anchor": "after_authored_prompt",
                    "condition": "always",
                    "text": "persisted custom text",
                }
            ],
        }
        v2_content = definition_content_from_row(revision)
        revision.content_hash = definition_content_hash(v2_content)

    v2 = PersistedGraphReleaseLoader(session_factory=session_factory).resolve(
        v1_release_id, "architect"
    )
    assert isinstance(v2.content.assembly_rules, AssemblyRulesV2)


@pytest.mark.parametrize("hybrid", ["v1_identity_v2_rules", "v2_identity_v1_rules"])
def test_exact_persisted_release_hybrids_reach_runtime_assembler_and_fail_pre_sink(
    session_factory, v1_release_id, hybrid
):
    with session_factory.begin() as db:
        revision = db.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == "architect"
            )
        )
        assert revision is not None
        if hybrid == "v1_identity_v2_rules":
            revision.assembly_rules = {"format_version": 2, "custom_blocks": []}
        else:
            revision.protected_assembly_version = V2_PROTECTED_ASSEMBLY_IDENTITY.version
            revision.protected_assembly_digest = V2_PROTECTED_ASSEMBLY_IDENTITY.digest
        content = definition_content_from_row(revision)
        revision.content_hash = definition_content_hash(content)

    class RecordingAdapter:
        def __init__(self) -> None:
            self.calls = []

        def invoke(self, **kwargs):
            self.calls.append(kwargs)
            return OUTPUT_SCHEMAS["architect"].model_construct()

    adapter = RecordingAdapter()
    sink = RecordingAgentInvocationIdentitySink()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(
            session_factory=session_factory
        ),
        model_adapter=adapter,
        identity_sink=sink,
    )

    with pytest.raises(PersistedConfigurationUnavailableError) as caught:
        runtime.run("architect", v1_release_id, {}, AgentAssemblyContext(False))

    assert caught.value.code == "invalid_persisted_definition"
    assert adapter.calls == []
    assert sink.calls == []


def test_resolves_v1_and_v2_by_their_persisted_ids_not_active_release(
    session_factory, v1_release_id
):
    with session_factory.begin() as db:
        v1 = db.get(GraphRelease, v1_release_id)
        assert v1 is not None
        v1.effective_to = v1.effective_from.replace(year=v1.effective_from.year + 1)
        v2 = GraphRelease(
            version_number=2,
            previous_release_id=v1.id,
            release_note="test V2",
            published_by="test",
        )
        db.add(v2)
        db.flush()
        db.add_all(
            GraphReleaseAgent(
                graph_release_id=v2.id,
                agent_key=mapping.agent_key,
                agent_definition_revision_id=mapping.agent_definition_revision_id,
            )
            for mapping in db.scalars(
                select(GraphReleaseAgent).where(
                    GraphReleaseAgent.graph_release_id == v1_release_id
                )
            )
        )
        db.flush()
        v2_id = v2.id

    loader = PersistedGraphReleaseLoader(session_factory=session_factory)
    assert loader.resolve(v1_release_id, "architect").graph_version == 1
    assert loader.resolve(v2_id, "architect").graph_version == 2


def test_absent_release_raises_not_found_without_active_or_latest_lookup(session_factory):
    loader = PersistedGraphReleaseLoader(session_factory=session_factory)

    with pytest.raises(GraphReleaseNotFoundError):
        loader.resolve(999, "architect")


@pytest.mark.parametrize("mapping_count", [0, 6])
def test_rejects_incomplete_persisted_release_mapping_count(
    session_factory, v1_release_id, mapping_count
):
    with session_factory.begin() as db:
        mappings = list(
            db.scalars(
                select(GraphReleaseAgent).where(
                    GraphReleaseAgent.graph_release_id == v1_release_id
                )
            )
        )
        for mapping in mappings[mapping_count:]:
            db.delete(mapping)

    with pytest.raises(GraphReleaseIncompleteError):
        PersistedGraphReleaseLoader(session_factory=session_factory).resolve(
            v1_release_id, "architect"
        )


@pytest.mark.parametrize("malformation", ["null_mapping", "missing_revision"])
def test_rejects_null_mapping_or_missing_revision_from_outer_join(
    session_factory, v1_release_id, malformation
):
    rows = _release_rows(session_factory, v1_release_id)
    release, mapping, revision = rows[0]
    if malformation == "null_mapping":
        malformed_rows = [(release, None, None)]
    else:
        malformed_rows = [(release, mapping, None), *rows[1:]]

    loader = PersistedGraphReleaseLoader(session_factory=_rows_factory(malformed_rows))
    with pytest.raises(GraphReleaseIncompleteError):
        loader.resolve(v1_release_id, "architect")


@pytest.mark.parametrize("malformation", ["wrong_role", "duplicate_role"])
def test_rejects_wrong_or_duplicate_role_mapping(
    session_factory, v1_release_id, malformation
):
    rows = _release_rows(session_factory, v1_release_id)
    release, mapping, revision = rows[0]
    if malformation == "wrong_role":
        malformed_mapping = GraphReleaseAgent(
            graph_release_id=release.id,
            agent_key="not-a-graph-role",
            agent_definition_revision_id=revision.id,
        )
        malformed_rows = [(release, malformed_mapping, revision), *rows[1:]]
    else:
        malformed_rows = [*rows, (release, mapping, revision)]

    loader = PersistedGraphReleaseLoader(session_factory=_rows_factory(malformed_rows))
    with pytest.raises(GraphReleaseIncompleteError):
        loader.resolve(v1_release_id, "architect")


def test_rejects_altered_persisted_hash_as_configuration_unavailable(
    session_factory, v1_release_id
):
    with session_factory.begin() as db:
        db.execute(
            update(AgentDefinitionRevision)
            .where(AgentDefinitionRevision.agent_key == "architect")
            .values(content_hash="0" * 64)
        )

    loader = PersistedGraphReleaseLoader(session_factory=session_factory)
    with pytest.raises(PersistedConfigurationUnavailableError) as raised:
        loader.resolve(v1_release_id, "architect")
    assert raised.value.code == "invalid_persisted_definition"
    assert loader._cache == {}


def test_converts_direct_loader_validation_value_errors_to_unavailable(
    session_factory, v1_release_id, monkeypatch
):
    def invalid_loader_owned_validation(*_args, **_kwargs):
        raise ValueError("invalid typed content")

    monkeypatch.setattr(
        persisted_graph_release_module,
        "validate_definition_hash",
        invalid_loader_owned_validation,
    )

    with pytest.raises(PersistedConfigurationUnavailableError) as raised:
        PersistedGraphReleaseLoader(session_factory=session_factory).resolve(
            v1_release_id, "architect"
        )

    assert raised.value.code == "invalid_persisted_definition"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format_version", 2),
        ("separator", "\\n"),
        ("block_order", None),
        ("protected_condition", "always"),
        ("terminal_binding", "not-the-terminal"),
    ],
)
def test_loader_rejects_each_invalid_typed_assembly_contract(
    session_factory, v1_release_id, field, value
):
    with session_factory.begin() as db:
        revision = db.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == "architect"
            )
        )
        assert revision is not None
        assembly = copy.deepcopy(revision.assembly_rules)
        if field == "block_order":
            blocks = assembly["blocks"]
            assembly["blocks"] = [blocks[0], blocks[2], blocks[1], *blocks[3:]]
        elif field == "protected_condition":
            assembly["blocks"][1]["condition"] = value
        elif field == "terminal_binding":
            assembly["blocks"][-1]["binding"] = value
        else:
            assembly[field] = value
        revision.assembly_rules = assembly
        with pytest.raises(ValidationError):
            definition_content_from_row(revision)

    with pytest.raises(PersistedConfigurationUnavailableError) as raised:
        PersistedGraphReleaseLoader(session_factory=session_factory).resolve(
            v1_release_id, "architect"
        )
    assert raised.value.code == "invalid_persisted_definition"


def test_configuration_errors_are_frozen_redacted_and_preserve_only_identity():
    for code in (
        "lakebase_unavailable",
        "invalid_persisted_definition",
        "protected_bundle_unavailable",
        "schema_contract_unavailable",
        "conversation_pin_unavailable",
    ):
        error = PersistedConfigurationUnavailableError(code=code)
        assert error.code == code
        assert str(error) == "Persisted graph configuration is unavailable"
        with pytest.raises((AttributeError, TypeError)):
            error.code = "lakebase_unavailable"

    endpoint = PinnedInvocationEndpointError(
        endpoint_name="pinned-endpoint", graph_release_id=4, agent_definition_revision_id=9
    )
    assert endpoint.endpoint_name == "pinned-endpoint"
    assert endpoint.graph_release_id == 4
    assert endpoint.agent_definition_revision_id == 9
    assert str(endpoint) == "Pinned graph model endpoint is unavailable"
    assert endpoint.args == ("pinned-endpoint", 4, 9)
    assert "prompt" not in str(endpoint).lower()
    assert "payload" not in str(endpoint).lower()
    assert "prompt" not in repr(endpoint.args).lower()
    assert "payload" not in repr(endpoint.args).lower()
