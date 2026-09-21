from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

import src.database.models  # noqa: F401 -- exercises public ORM registration
from src.core.database import Base, _run_migrations
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_definition_manifest import (
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)

EXPECTED_TABLES = {
    "agent_definition_revision",
    "graph_release",
    "graph_release_agent",
    "graph_draft",
    "graph_draft_agent",
    "agent_test_case",
}
ROLE_TABLES = {
    "agent_definition_revision",
    "graph_release_agent",
    "graph_draft_agent",
    "agent_test_case",
}
ROLE_CHECK_SQL = (
    "agent_key IN ('architect', 'data_analyst', 'builder', 'build_reviewer', "
    "'fixer', 'fix_reviewer', 'deck_reviewer')"
)
EXPECTED_CHECKS = {
    "agent_definition_revision": {
        "ck_agent_definition_revision_agent_key",
        "ck_agent_definition_revision_content_hash_length",
        "ck_agent_definition_revision_created_by_nonblank",
        "ck_agent_definition_revision_definition_version_positive",
        "ck_agent_definition_revision_endpoint_nonblank",
        "ck_agent_definition_revision_max_tokens_positive",
        "ck_agent_definition_revision_prompt_nonblank",
        "ck_agent_definition_revision_protected_digest_length",
        "ck_agent_definition_revision_protected_version_positive",
        "ck_agent_definition_revision_schema_digest_length",
        "ck_agent_definition_revision_schema_version_positive",
        "ck_agent_definition_revision_temperature_range",
        "ck_agent_definition_revision_top_p_range",
    },
    "graph_release": {
        "ck_graph_release_interval",
        "ck_graph_release_note_nonblank",
        "ck_graph_release_published_by_nonblank",
        "ck_graph_release_version_positive",
    },
    "graph_release_agent": {"ck_graph_release_agent_agent_key"},
    "graph_draft": {
        "ck_graph_draft_lock_version_nonnegative",
        "ck_graph_draft_singleton",
        "ck_graph_draft_updated_by_nonblank",
    },
    "graph_draft_agent": {
        "ck_graph_draft_agent_agent_key",
        "ck_graph_draft_agent_candidate_hash_length",
        "ck_graph_draft_agent_definition_version_positive",
        "ck_graph_draft_agent_endpoint_nonblank",
        "ck_graph_draft_agent_max_tokens_positive",
        "ck_graph_draft_agent_prompt_nonblank",
        "ck_graph_draft_agent_protected_digest_length",
        "ck_graph_draft_agent_protected_version_positive",
        "ck_graph_draft_agent_schema_digest_length",
        "ck_graph_draft_agent_schema_version_positive",
        "ck_graph_draft_agent_temperature_range",
        "ck_graph_draft_agent_top_p_range",
    },
    "agent_test_case": {
        "ck_agent_test_case_agent_key",
        "ck_agent_test_case_created_by_nonblank",
        "ck_agent_test_case_name_nonblank",
        "ck_agent_test_case_updated_by_nonblank",
        "ck_agent_test_case_version_positive",
    },
}


def _sqlite_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    _run_migrations(engine)
    return engine


def _release_values(version_number: int, *, active: bool) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "version_number": version_number,
        "previous_release_id": None,
        "restored_from_release_id": None,
        "release_note": f"release {version_number}",
        "published_by": "test:unit",
        "published_at": now,
        "effective_from": now,
        "effective_to": None if active else now + timedelta(seconds=1),
    }


def _row_to_definition(row: AgentDefinitionRevision) -> DefinitionContent:
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


def test_graph_configuration_tables_and_public_models_are_registered() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    for name in (
        "AgentDefinitionRevision",
        "GraphRelease",
        "GraphReleaseAgent",
        "GraphDraft",
        "GraphDraftAgent",
        "AgentTestCase",
    ):
        assert name in src.database.models.__all__
        assert getattr(src.database.models, name) is not None


def test_tables_expose_exact_named_checks_and_identical_closed_role_sql() -> None:
    for table_name, expected_names in EXPECTED_CHECKS.items():
        table = Base.metadata.tables[table_name]
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        }
        assert set(checks) == expected_names
        if table_name in ROLE_TABLES:
            assert checks[f"ck_{table_name}_agent_key"] == ROLE_CHECK_SQL


def test_semantic_columns_use_json_variants_numeric_decimals_and_database_timestamps() -> None:
    for table_name in ("agent_definition_revision", "graph_draft_agent"):
        table = Base.metadata.tables[table_name]
        assert str(table.c.temperature.type) == "NUMERIC(7, 6)"
        assert str(table.c.top_p.type) == "NUMERIC(7, 6)"
        assert (
            table.c.schema_overlay.type._variant_mapping["postgresql"].__class__.__name__ == "JSONB"
        )
        assert (
            table.c.assembly_rules.type._variant_mapping["postgresql"].__class__.__name__ == "JSONB"
        )

    for table_name, timestamp_names in {
        "agent_definition_revision": ("created_at",),
        "graph_release": ("published_at", "effective_from", "effective_to"),
        "graph_draft": ("updated_at",),
        "agent_test_case": ("created_at", "updated_at"),
    }.items():
        table = Base.metadata.tables[table_name]
        for column_name in timestamp_names:
            column = table.c[column_name]
            assert column.type.timezone is True
            if column_name != "effective_to":
                assert column.server_default is not None


def test_every_graph_foreign_key_is_named_and_restrictive_without_orm_delete_cascades() -> None:
    foreign_keys = []
    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        for constraint in table.foreign_key_constraints:
            foreign_keys.append((table_name, constraint))
            assert constraint.name
            assert constraint.ondelete == "RESTRICT"
    assert len(foreign_keys) == 6

    compatible = next(
        constraint
        for constraint in GraphReleaseAgent.__table__.foreign_key_constraints
        if constraint.name == "fk_graph_release_agent_compatible_revision"
    )
    assert tuple(compatible.column_keys) == (
        "agent_definition_revision_id",
        "agent_key",
    )
    assert tuple(element.target_fullname for element in compatible.elements) == (
        "agent_definition_revision.id",
        "agent_definition_revision.agent_key",
    )

    for mapper in (
        AgentDefinitionRevision,
        GraphRelease,
        GraphReleaseAgent,
        GraphDraft,
        GraphDraftAgent,
        AgentTestCase,
    ):
        for relationship in inspect(mapper).relationships:
            assert "delete" not in relationship.cascade
            assert "delete-orphan" not in relationship.cascade


def test_one_active_release_index_has_both_partial_dialect_predicates() -> None:
    index = next(
        index
        for index in GraphRelease.__table__.indexes
        if index.name == "uq_graph_release_one_active"
    )
    assert index.unique is True
    assert str(index.expressions[0]) == "(1)"
    assert str(index.dialect_options["postgresql"]["where"]) == "effective_to IS NULL"
    assert str(index.dialect_options["sqlite"]["where"]) == "effective_to IS NULL"
    sqlite_ddl = str(CreateIndex(index).compile(dialect=create_engine("sqlite://").dialect))
    assert "WHERE effective_to IS NULL" in sqlite_ddl


def test_sqlite_allows_closed_plus_active_release_but_rejects_second_active() -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as conn:
            conn.execute(GraphRelease.__table__.insert(), _release_values(1, active=False))
            conn.execute(GraphRelease.__table__.insert(), _release_values(2, active=True))
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(GraphRelease.__table__.insert(), _release_values(3, active=True))
        with engine.connect() as conn:
            assert conn.execute(
                select(GraphRelease.version_number).order_by(GraphRelease.version_number)
            ).scalars().all() == [1, 2]
    finally:
        engine.dispose()


def test_manifest_numeric_content_round_trips_as_decimal_without_hash_drift() -> None:
    definition = load_graph_v1_manifest().definitions[0]
    payload = definition.model_dump(mode="json")
    engine = _sqlite_engine()
    try:
        with engine.begin() as conn:
            revision_id = conn.execute(
                AgentDefinitionRevision.__table__.insert()
                .values(
                    agent_key=payload["agent_key"],
                    definition_version=payload["definition_version"],
                    content_hash=definition_content_hash(definition),
                    prompt_text=payload["prompt_text"],
                    endpoint_name=payload["model"]["endpoint_name"],
                    temperature=payload["model"]["temperature"],
                    max_tokens=payload["model"]["max_tokens"],
                    top_p=payload["model"]["top_p"],
                    schema_overlay=payload["schema_overlay"],
                    assembly_rules=payload["assembly_rules"],
                    protected_assembly_version=payload["protected_assembly"]["version"],
                    protected_assembly_digest=payload["protected_assembly"]["digest"],
                    schema_contract_version=payload["schema_contract"]["version"],
                    schema_contract_digest=payload["schema_contract"]["digest"],
                    created_by="test:roundtrip",
                )
                .returning(AgentDefinitionRevision.id)
            ).scalar_one()

        from sqlalchemy.orm import Session

        with Session(engine) as session:
            row = session.get(AgentDefinitionRevision, revision_id)
            assert row is not None
            assert row.temperature == Decimal("0.700000")
            assert row.top_p == Decimal("0.950000")
            assert definition_content_hash(_row_to_definition(row)) == row.content_hash
    finally:
        engine.dispose()


def test_agent_test_case_raw_insert_receives_true_database_defaults() -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as conn:
            # Literal SQL bypasses SQLAlchemy's Python-side Column.default. This
            # test therefore fails if either database default is removed.
            test_id = conn.execute(
                text(
                    "INSERT INTO agent_test_case "
                    "(agent_key, name, version, synthetic_payload, assembly_context, "
                    "created_by, updated_by) VALUES "
                    "('architect', 'required smoke', 1, '{}', '{}', "
                    "'test:unit', 'test:unit') RETURNING id"
                )
            ).scalar_one()
            stored = (
                conn.execute(select(AgentTestCase).where(AgentTestCase.id == test_id))
                .one()
                ._mapping
            )
            assert stored["is_active"] is True
            assert stored["is_required"] is True
            assert stored["created_at"] is not None
            assert stored["updated_at"] is not None
    finally:
        engine.dispose()
