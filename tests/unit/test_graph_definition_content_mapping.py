from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone

from src.api.schemas.agent_definitions import (
    DraftDefinitionResponse,
    PublishedDefinitionResponse,
)
from src.database.models.graph_configuration import (
    DEFINITION_CONTENT_COLUMN_NAMES,
    AgentDefinitionRevision,
    DefinitionContentColumns,
    GraphDraftAgent,
)
from src.services.graph_configuration_content import (
    definition_content_from_row,
    definition_content_values,
    draft_from_definition,
    revision_from_definition,
)
from src.services.graph_configuration_workbench import (
    DraftDefinitionSnapshot,
    PublishedDefinitionSnapshot,
)
from src.services.graph_definition_manifest import load_graph_v1_manifest


def test_one_mapping_round_trips_every_semantic_field_through_both_row_types() -> None:
    definition = load_graph_v1_manifest().definitions[0]
    timestamp = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)

    revision = revision_from_definition(
        definition,
        actor="test:content-mapping",
        timestamp=timestamp,
    )
    draft = draft_from_definition(definition, draft_id=1)

    assert isinstance(revision, DefinitionContentColumns)
    assert isinstance(draft, DefinitionContentColumns)
    assert definition_content_from_row(revision) == definition
    assert definition_content_from_row(draft) == definition
    assert definition_content_values(definition) == {
        column_name: getattr(revision, column_name)
        for column_name in DEFINITION_CONTENT_COLUMN_NAMES
    }
    assert definition_content_values(definition) == {
        column_name: getattr(draft, column_name)
        for column_name in DEFINITION_CONTENT_COLUMN_NAMES
    }
    assert list(AgentDefinitionRevision.__table__.columns.keys()) == [
        "id",
        *DEFINITION_CONTENT_COLUMN_NAMES[:2],
        "content_hash",
        *DEFINITION_CONTENT_COLUMN_NAMES[2:],
        "created_by",
        "created_at",
    ]
    assert list(GraphDraftAgent.__table__.columns.keys()) == [
        "graph_draft_id",
        DEFINITION_CONTENT_COLUMN_NAMES[0],
        "candidate_hash",
        *DEFINITION_CONTENT_COLUMN_NAMES[1:],
    ]


def test_snapshots_keep_one_content_record_and_responses_flatten_it_in_wire_order() -> None:
    content = load_graph_v1_manifest().definitions[0]
    published = PublishedDefinitionSnapshot(
        revision_id=17,
        content_hash="a" * 64,
        content=content,
    )
    draft = DraftDefinitionSnapshot(
        base_revision_id=17,
        candidate_hash="a" * 64,
        content=content,
    )

    assert [field.name for field in fields(PublishedDefinitionSnapshot)] == [
        "revision_id",
        "content_hash",
        "content",
    ]
    assert [field.name for field in fields(DraftDefinitionSnapshot)] == [
        "base_revision_id",
        "candidate_hash",
        "content",
    ]
    assert published.prompt_text == draft.prompt_text == content.prompt_text
    assert published.model is draft.model is content.model

    published_body = PublishedDefinitionResponse.model_validate(
        published, from_attributes=True
    ).model_dump(mode="json")
    draft_body = DraftDefinitionResponse.model_validate(
        draft, from_attributes=True
    ).model_dump(mode="json")
    semantic_fields = [
        "definition_version",
        "prompt_text",
        "model",
        "schema_overlay",
        "assembly_rules",
        "protected_assembly",
        "schema_contract",
    ]
    assert set(semantic_fields) == set(type(content).model_fields) - {"agent_key"}
    assert list(published_body) == ["revision_id", "content_hash", *semantic_fields]
    assert list(draft_body) == ["base_revision_id", "candidate_hash", *semantic_fields]
    assert {name: published_body[name] for name in semantic_fields} == (
        content.model_dump(mode="json", exclude={"agent_key"})
    )
    assert {name: draft_body[name] for name in semantic_fields} == (
        content.model_dump(mode="json", exclude={"agent_key"})
    )
    assert (
        PublishedDefinitionResponse.model_validate(published_body).model_dump(mode="json")
        == published_body
    )
    assert DraftDefinitionResponse.model_validate(draft_body).model_dump(mode="json") == (
        draft_body
    )
