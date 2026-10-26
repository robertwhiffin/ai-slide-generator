from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone

import pytest

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
from src.services.graph_definition_manifest import (
    definition_content_hash,
    load_graph_v1_manifest,
)


def _changed_canonical_content(content, path: str):
    if path == "agent_key":
        return content.model_copy(update={"agent_key": "builder"})
    if path == "definition_version":
        return content.model_copy(update={"definition_version": 999})
    if path == "prompt_text":
        return content.model_copy(update={"prompt_text": "changed prompt"})
    if path.startswith("model."):
        field = path.removeprefix("model.")
        values = {
            "endpoint_name": "changed-endpoint",
            "temperature": 0.123,
            "max_tokens": 1234,
            "top_p": 0.456,
        }
        return content.model_copy(
            update={"model": content.model.model_copy(update={field: values[field]})}
        )
    if path == "schema_overlay":
        return content.model_copy(
            update={
                "schema_overlay": content.schema_overlay.model_copy(
                    update={"additional_optional_fields": ("changed",)}
                )
            }
        )
    if path == "assembly_rules":
        return content.model_copy(
            update={
                "assembly_rules": content.assembly_rules.model_copy(
                    update={"separator": "changed"}
                )
            }
        )
    identity_name, member = path.split(".")
    identity = getattr(content, identity_name)
    value = identity.version + 1 if member == "version" else "f" * 64
    return content.model_copy(
        update={identity_name: identity.model_copy(update={member: value})}
    )


@pytest.mark.parametrize(
    "path",
    [
        "agent_key",
        "definition_version",
        "prompt_text",
        "model.endpoint_name",
        "model.temperature",
        "model.max_tokens",
        "model.top_p",
        "schema_overlay",
        "assembly_rules",
        "protected_assembly.version",
        "protected_assembly.digest",
        "schema_contract.version",
        "schema_contract.digest",
    ],
)
def test_canonical_hash_covers_every_persisted_content_path(path: str) -> None:
    content = load_graph_v1_manifest().definitions[0]

    assert definition_content_hash(_changed_canonical_content(content, path)) != (
        definition_content_hash(content)
    )


def test_canonical_payload_has_exactly_the_thirteen_persisted_paths() -> None:
    payload = load_graph_v1_manifest().definitions[0].canonical_payload()
    leaf_paths = {
        ("agent_key",),
        ("definition_version",),
        ("prompt_text",),
        ("model", "endpoint_name"),
        ("model", "temperature"),
        ("model", "max_tokens"),
        ("model", "top_p"),
        ("schema_overlay",),
        ("assembly_rules",),
        ("protected_assembly", "version"),
        ("protected_assembly", "digest"),
        ("schema_contract", "version"),
        ("schema_contract", "digest"),
    }

    assert len(DEFINITION_CONTENT_COLUMN_NAMES) == 13
    assert set(payload) == {
        "agent_key",
        "definition_version",
        "prompt_text",
        "model",
        "schema_overlay",
        "assembly_rules",
        "protected_assembly",
        "schema_contract",
    }
    assert leaf_paths == {
        ("agent_key",),
        ("definition_version",),
        ("prompt_text",),
        *(("model", member) for member in payload["model"]),
        ("schema_overlay",),
        ("assembly_rules",),
        *(("protected_assembly", member) for member in payload["protected_assembly"]),
        *(("schema_contract", member) for member in payload["schema_contract"]),
    }


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
    # #265 appends one server-derived, read-only protected view after the flattened
    # content record, and #264 appends two more read-only display lists (the selectable
    # optional-field descriptors and the canonical-field descriptors).  None of them is
    # part of the persisted content seam.
    server_derived = [
        "protected_stage_view",
        "selectable_optional_fields",
        "canonical_fields",
    ]
    assert list(published_body) == [
        "revision_id",
        "content_hash",
        *semantic_fields,
        *server_derived,
    ]
    assert list(draft_body) == [
        "base_revision_id",
        "candidate_hash",
        *semantic_fields,
        *server_derived,
    ]
    for name in server_derived:
        assert name not in DEFINITION_CONTENT_COLUMN_NAMES
        assert name not in type(content).model_fields
    assert published_body["protected_stage_view"] == draft_body["protected_stage_view"]
    assert all(
        row["locked"] is True for row in published_body["protected_stage_view"]
    )
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
