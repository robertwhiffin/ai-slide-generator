from __future__ import annotations

import builtins
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401
from src.core.database import Base
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentRuntime,
    CodeOwnedAgentDefinitionSource,
)
from src.services.graph_configuration import (
    REQUIRED_SMOKE_PAYLOADS,
    BootstrapResult,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    definition_content_hash,
    load_graph_v1_manifest,
)

EXPECTED_REQUIRED_SMOKE_PAYLOADS = {
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


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _all_artifact_identities(session_factory) -> dict[str, list[tuple[object, ...]]]:
    with session_factory() as session:
        return {
            "revisions": list(
                session.execute(
                    select(
                        AgentDefinitionRevision.id,
                        AgentDefinitionRevision.agent_key,
                        AgentDefinitionRevision.content_hash,
                    ).order_by(AgentDefinitionRevision.id)
                ).all()
            ),
            "releases": list(
                session.execute(
                    select(GraphRelease.id, GraphRelease.version_number).order_by(
                        GraphRelease.id
                    )
                ).all()
            ),
            "mappings": list(
                session.execute(
                    select(
                        GraphReleaseAgent.graph_release_id,
                        GraphReleaseAgent.agent_key,
                        GraphReleaseAgent.agent_definition_revision_id,
                    ).order_by(
                        GraphReleaseAgent.graph_release_id,
                        GraphReleaseAgent.agent_key,
                    )
                ).all()
            ),
            "drafts": list(
                session.execute(
                    select(GraphDraft.id, GraphDraft.base_release_id).order_by(
                        GraphDraft.id
                    )
                ).all()
            ),
            "draft_agents": list(
                session.execute(
                    select(
                        GraphDraftAgent.graph_draft_id,
                        GraphDraftAgent.agent_key,
                        GraphDraftAgent.candidate_hash,
                    ).order_by(GraphDraftAgent.agent_key)
                ).all()
            ),
            "test_cases": list(
                session.execute(
                    select(
                        AgentTestCase.id,
                        AgentTestCase.agent_key,
                        AgentTestCase.name,
                        AgentTestCase.version,
                        AgentTestCase.is_active,
                        AgentTestCase.is_required,
                    ).order_by(AgentTestCase.id)
                ).all()
            ),
        }


def _expected_manifest_hashes() -> dict[str, str]:
    return {
        item.agent_key: definition_content_hash(item)
        for item in load_graph_v1_manifest().definitions
    }


def _create_active_v2(session_factory) -> int:
    with session_factory.begin() as session:
        v1 = session.scalar(select(GraphRelease).where(GraphRelease.effective_to.is_(None)))
        assert v1 is not None
        v1.effective_to = v1.effective_from.replace(year=v1.effective_from.year + 1)
        architect_v2 = load_graph_v1_manifest().definitions[0].model_copy(
            update={"prompt_text": "Synthetic future Architect prompt"}
        )
        architect_revision = GraphConfiguration._revision_from_definition(
            architect_v2,
            actor="test:v2",
            timestamp=GraphConfiguration._now(),
        )
        session.add(architect_revision)
        session.flush()
        v2 = GraphRelease(
            version_number=2,
            previous_release_id=v1.id,
            release_note="Synthetic Graph Version 2",
            published_by="test:v2",
        )
        session.add(v2)
        session.flush()
        mappings = session.scalars(
            select(GraphReleaseAgent).where(GraphReleaseAgent.graph_release_id == v1.id)
        ).all()
        session.add_all(
            GraphReleaseAgent(
                graph_release_id=v2.id,
                agent_key=mapping.agent_key,
                agent_definition_revision_id=(
                    architect_revision.id
                    if mapping.agent_key == "architect"
                    else mapping.agent_definition_revision_id
                ),
            )
            for mapping in mappings
        )
        draft = session.get(GraphDraft, 1)
        assert draft is not None
        draft.base_release_id = v2.id
        v1_cases = list(session.scalars(select(AgentTestCase)))
        for case in v1_cases:
            case.is_active = False
            session.add(
                AgentTestCase(
                    agent_key=case.agent_key,
                    name=f"{case.agent_key}_required_smoke_v2",
                    version=2,
                    is_active=True,
                    is_required=True,
                    synthetic_payload={"future": case.agent_key},
                    assembly_context={"design_system_active": False},
                    created_by="test:v2",
                    updated_by="test:v2",
                )
            )
        session.flush()
        return v2.id


def test_fresh_bootstrap_creates_exact_complete_v1(session_factory):
    result = GraphConfiguration().bootstrap_v1(session_factory)

    assert result.created is True
    assert result.version_number == 1
    hashes = _expected_manifest_hashes()
    with session_factory() as session:
        mappings = session.execute(
            select(
                GraphReleaseAgent.agent_key,
                AgentDefinitionRevision.content_hash,
            )
            .join(
                AgentDefinitionRevision,
                AgentDefinitionRevision.id
                == GraphReleaseAgent.agent_definition_revision_id,
            )
            .where(GraphReleaseAgent.graph_release_id == result.release_id)
        ).all()
        draft_hashes = dict(
            session.execute(
                select(GraphDraftAgent.agent_key, GraphDraftAgent.candidate_hash)
            ).all()
        )
        cases = session.scalars(select(AgentTestCase).order_by(AgentTestCase.agent_key)).all()

    assert dict(mappings) == hashes
    assert draft_hashes == hashes
    assert {case.agent_key for case in cases} == set(GRAPH_V1_AGENT_KEYS)
    assert len(cases) == 7
    assert all(case.name == f"{case.agent_key}_required_smoke_v1" for case in cases)
    assert all(case.version == 1 and case.is_active and case.is_required for case in cases)
    assert {case.agent_key: case.synthetic_payload for case in cases} == (
        EXPECTED_REQUIRED_SMOKE_PAYLOADS
    )
    assert all(
        case.assembly_context == {"design_system_active": False} for case in cases
    )
    assert REQUIRED_SMOKE_PAYLOADS == EXPECTED_REQUIRED_SMOKE_PAYLOADS


def test_all_persisted_rows_use_one_database_timestamp(session_factory):
    GraphConfiguration().bootstrap_v1(session_factory)
    with session_factory() as session:
        timestamps = {
            *session.scalars(select(AgentDefinitionRevision.created_at)).all(),
            *session.scalars(select(GraphRelease.published_at)).all(),
            *session.scalars(select(GraphRelease.effective_from)).all(),
            *session.scalars(select(GraphDraft.updated_at)).all(),
            *session.scalars(select(AgentTestCase.created_at)).all(),
            *session.scalars(select(AgentTestCase.updated_at)).all(),
        }
    assert len(timestamps) == 1


def test_required_cases_pass_unchanged_through_current_runtime_adapter_seam(
    session_factory,
):
    GraphConfiguration().bootstrap_v1(session_factory)
    with session_factory() as session:
        cases = session.scalars(select(AgentTestCase).order_by(AgentTestCase.id)).all()

    class RecordingAdapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def invoke(self, *, configuration, schema, prompt):
            self.calls.append(
                {"configuration": asdict(configuration), "schema": schema, "prompt": prompt}
            )
            return schema.model_construct()

    adapter = RecordingAdapter()
    runtime = AgentRuntime.compatibility(
        definition_source=CodeOwnedAgentDefinitionSource(), model_adapter=adapter
    )
    for case in cases:
        before = json.loads(json.dumps(case.synthetic_payload))
        runtime.run(
            case.agent_key,
            case.synthetic_payload,
            AgentAssemblyContext(**case.assembly_context),
        )
        assert case.synthetic_payload == before
        assert adapter.calls[-1]["prompt"].endswith(
            json.dumps(before, indent=2, default=str)
        )

    assert len(adapter.calls) == 7


def test_second_bootstrap_neither_loads_manifest_nor_rewrites_rows(
    session_factory, monkeypatch
):
    service = GraphConfiguration()
    first = service.bootstrap_v1(session_factory)
    before = _all_artifact_identities(session_factory)
    sys.modules.pop("src.services.agent_definition_manifest_v1", None)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "src.services.agent_definition_manifest_v1":
            raise AssertionError("generated manifest imported on existing-release path")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    second = service.bootstrap_v1(
        session_factory,
        manifest_loader=lambda: (_ for _ in ()).throw(AssertionError("manifest loaded")),
    )

    assert second == BootstrapResult(False, first.release_id, 1)
    assert _all_artifact_identities(session_factory) == before
    assert "src.services.agent_definition_manifest_v1" not in sys.modules


def test_importing_service_directly_does_not_import_generated_snapshot():
    root = Path(__file__).resolve().parents[2]
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import src.services.graph_configuration; "
            "assert 'src.services.agent_definition_manifest_v1' not in sys.modules",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr


def test_existing_active_v2_validates_all_history_without_loading_v1_manifest(
    session_factory, monkeypatch
):
    GraphConfiguration().bootstrap_v1(session_factory)
    active_v2_id = _create_active_v2(session_factory)
    before = _all_artifact_identities(session_factory)
    sys.modules.pop("src.services.agent_definition_manifest_v1", None)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "src.services.agent_definition_manifest_v1":
            raise AssertionError("generated manifest imported for valid v2 state")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = GraphConfiguration().bootstrap_v1(
        session_factory,
        manifest_loader=lambda: (_ for _ in ()).throw(AssertionError("manifest loaded")),
    )

    assert result == BootstrapResult(False, active_v2_id, 2)
    assert _all_artifact_identities(session_factory) == before
    assert "src.services.agent_definition_manifest_v1" not in sys.modules


class InjectedBootstrapError(RuntimeError):
    pass


@pytest.mark.parametrize("reuse_revision", [False, True], ids=["fresh", "reusable-revision"])
def test_mid_transaction_failure_rolls_back_attempted_graph_artifacts(
    session_factory, monkeypatch, reuse_revision
):
    if reuse_revision:
        definition = load_graph_v1_manifest().definitions[0]
        reusable = GraphConfiguration._revision_from_definition(
            definition, actor="preexisting", timestamp=GraphConfiguration._now()
        )
        with session_factory.begin() as session:
            session.add(reusable)
            session.flush()
            reusable_id = reusable.id
        before = _all_artifact_identities(session_factory)
    else:
        reusable_id = None
        before = {
            "revisions": [],
            "releases": [],
            "mappings": [],
            "drafts": [],
            "draft_agents": [],
            "test_cases": [],
        }

    executed = False

    def fail_after_flushed_mappings(self, session, *args, **kwargs):
        nonlocal executed
        session.flush()
        assert session.scalar(select(func.count()).select_from(GraphReleaseAgent)) == 7
        executed = True
        raise InjectedBootstrapError("after flushed release mappings")

    monkeypatch.setattr(GraphConfiguration, "_insert_draft_and_cases", fail_after_flushed_mappings)
    with pytest.raises(InjectedBootstrapError, match="flushed release mappings"):
        GraphConfiguration().bootstrap_v1(session_factory)

    assert executed is True
    assert _all_artifact_identities(session_factory) == before
    if reusable_id is not None:
        assert before["revisions"][0][0] == reusable_id


def test_valid_unreferenced_revision_is_reused(session_factory):
    definition = load_graph_v1_manifest().definitions[0]
    reusable = GraphConfiguration._revision_from_definition(
        definition, actor="preexisting", timestamp=GraphConfiguration._now()
    )
    with session_factory.begin() as session:
        session.add(reusable)
        session.flush()
        reusable_id = reusable.id

    result = GraphConfiguration().bootstrap_v1(session_factory)
    with session_factory() as session:
        mapping_id = session.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.graph_release_id == result.release_id,
                GraphReleaseAgent.agent_key == "architect",
            )
        )
        revision_count = session.scalar(
            select(func.count()).select_from(AgentDefinitionRevision)
        )
    assert mapping_id == reusable_id
    assert revision_count == 7


@pytest.mark.parametrize(
    ("artifact", "insert_sql"),
    [
        (
            "release mapping",
            "INSERT INTO graph_release_agent "
            "(graph_release_id, agent_key, agent_definition_revision_id) "
            "VALUES (999, 'architect', 999)",
        ),
        (
            "draft",
            "INSERT INTO graph_draft (id, base_release_id, updated_by) "
            "VALUES (1, 999, 'partial')",
        ),
        (
            "draft agent",
            "INSERT INTO graph_draft_agent "
            "(graph_draft_id, agent_key, candidate_hash, definition_version, "
            "prompt_text, endpoint_name, temperature, max_tokens, top_p, "
            "schema_overlay, assembly_rules, protected_assembly_version, "
            "protected_assembly_digest, schema_contract_version, schema_contract_digest) "
            "VALUES (1, 'architect', '" + "a" * 64 + "', 2, 'p', 'e', 0.7, 1, 0.95, "
            "'{}', '{}', 1, '" + "b" * 64 + "', 1, '" + "c" * 64 + "')",
        ),
        (
            "test case",
            "INSERT INTO agent_test_case "
            "(agent_key, name, version, synthetic_payload, assembly_context, "
            "created_by, updated_by) VALUES "
            "('architect', 'orphan', 1, '{}', '{}', 'partial', 'partial')",
        ),
    ],
)
def test_no_release_rejects_each_partial_artifact_class(
    session_factory, artifact, insert_sql
):
    engine = session_factory.kw["bind"]
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(text(insert_sql))
        connection.commit()

    with pytest.raises(GraphConfigurationIntegrityError, match="without a release"):
        GraphConfiguration().bootstrap_v1(session_factory)


@pytest.mark.parametrize(
    "corrupt",
    [
        "historical_release_mapping",
        "draft_agent",
        "required_case",
        "revision_hash",
        "orphan_release_mapping",
        "orphan_draft_agent",
    ],
)
def test_existing_state_detects_corruption_across_complete_aggregate(
    session_factory, corrupt
):
    service = GraphConfiguration()
    service.bootstrap_v1(session_factory)
    if corrupt == "historical_release_mapping":
        _create_active_v2(session_factory)
    if corrupt in {"orphan_release_mapping", "orphan_draft_agent"}:
        engine = session_factory.kw["bind"]
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            if corrupt == "orphan_release_mapping":
                connection.execute(
                    text(
                        "INSERT INTO graph_release_agent "
                        "(graph_release_id, agent_key, agent_definition_revision_id) "
                        "SELECT 999, agent_key, agent_definition_revision_id "
                        "FROM graph_release_agent WHERE agent_key = 'architect'"
                    )
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO graph_draft_agent "
                        "SELECT 2, agent_key, candidate_hash, definition_version, "
                        "prompt_text, endpoint_name, temperature, max_tokens, top_p, "
                        "schema_overlay, assembly_rules, protected_assembly_version, "
                        "protected_assembly_digest, schema_contract_version, "
                        "schema_contract_digest FROM graph_draft_agent "
                        "WHERE agent_key = 'architect'"
                    )
                )
            connection.commit()
    else:
        with session_factory.begin() as session:
            if corrupt == "historical_release_mapping":
                release_id = session.scalar(
                    select(GraphRelease.id).where(GraphRelease.version_number == 1)
                )
                row = session.scalar(
                    select(GraphReleaseAgent).where(
                        GraphReleaseAgent.graph_release_id == release_id,
                        GraphReleaseAgent.agent_key == "architect",
                    )
                )
                session.delete(row)
            elif corrupt == "draft_agent":
                row = session.get(GraphDraftAgent, (1, "architect"))
                session.delete(row)
            elif corrupt == "required_case":
                row = session.scalar(
                    select(AgentTestCase).where(AgentTestCase.agent_key == "architect")
                )
                row.is_active = False
            else:
                row = session.scalar(
                    select(AgentDefinitionRevision).where(
                        AgentDefinitionRevision.agent_key == "architect"
                    )
                )
                row.prompt_text = f"{row.prompt_text}\ncorrupt"

    with pytest.raises(GraphConfigurationIntegrityError):
        service.bootstrap_v1(
            session_factory,
            manifest_loader=lambda: (_ for _ in ()).throw(AssertionError("manifest loaded")),
        )
