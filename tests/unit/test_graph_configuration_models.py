from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

import src.database.models  # noqa: F401 -- exercises public ORM registration
from src.core.database import Base, _run_migrations
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    AgentTestRun,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
    GraphReleaseTestRun,
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
    "agent_test_run",
    "graph_release_test_run",
}
ROLE_TABLES = {
    "agent_definition_revision",
    "graph_release_agent",
    "graph_draft_agent",
    "agent_test_case",
    "agent_test_run",
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
    "agent_test_run": {
        "ck_agent_test_run_agent_key",
        "ck_agent_test_run_approved_only_if_completed_and_passing",
        "ck_agent_test_run_candidate_hash_len",
        "ck_agent_test_run_case_version_positive",
        "ck_agent_test_run_completed_has_output",
        "ck_agent_test_run_execution_status",
        "ck_agent_test_run_run_by_nonblank",
        "ck_agent_test_run_run_kind",
        "ck_agent_test_run_verdict_at_paired",
        "ck_agent_test_run_verdict_enum",
        "ck_agent_test_run_verdict_reviewer_paired",
    },
    "graph_release_test_run": {
        "ck_graph_release_test_run_evidence_kind",
        "ck_graph_release_test_run_source_paired",
    },
}

# Column name -> nullable, exactly (C19). Verdict columns are #268's to write.
AGENT_TEST_RUN_COLUMNS = {
    "id": False,
    "test_case_id": False,
    "test_case_version": False,
    "agent_key": False,
    "run_kind": False,
    "candidate_hash": False,
    "compared_release_id": False,
    "compared_definition_revision_id": False,
    "model_payload": False,
    "assembled_prompt": True,
    "candidate_raw_output": True,
    "candidate_structured_output": True,
    "baseline_raw_output": True,
    "baseline_structured_output": True,
    "deterministic_check_results": False,
    "deterministic_checks_passed": False,
    "execution_status": False,
    "error_detail": True,
    "latency_ms": True,
    "input_tokens": True,
    "output_tokens": True,
    "run_by": False,
    "run_at": False,
    "verdict": True,
    "verdict_reviewer": True,
    "verdict_at": True,
    "verdict_notes": True,
}
AGENT_TEST_RUN_JSON_COLUMNS = (
    "model_payload",
    "candidate_raw_output",
    "candidate_structured_output",
    "baseline_raw_output",
    "baseline_structured_output",
    "deterministic_check_results",
)
GRAPH_RELEASE_TEST_RUN_COLUMNS = {
    "graph_release_id": False,
    "agent_test_run_id": False,
    "evidence_kind": False,
    "source_release_id": True,
}
# FK name -> (local columns, referenced columns).
AGENT_TEST_RUN_FKS = {
    "fk_agent_test_run_test_case": (("test_case_id",), ("agent_test_case.id",)),
    "fk_agent_test_run_release": (("compared_release_id",), ("graph_release.id",)),
    "fk_agent_test_run_compatible_revision": (
        ("compared_definition_revision_id", "agent_key"),
        ("agent_definition_revision.id", "agent_definition_revision.agent_key"),
    ),
}
GRAPH_RELEASE_TEST_RUN_FKS = {
    "fk_graph_release_test_run_release": (("graph_release_id",), ("graph_release.id",)),
    "fk_graph_release_test_run_run": (("agent_test_run_id",), ("agent_test_run.id",)),
    "fk_graph_release_test_run_source": (("source_release_id",), ("graph_release.id",)),
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
        "AgentTestRun",
        "GraphReleaseTestRun",
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
        "agent_test_run": ("run_at", "verdict_at"),
    }.items():
        table = Base.metadata.tables[table_name]
        for column_name in timestamp_names:
            column = table.c[column_name]
            assert column.type.timezone is True
            if column_name in ("effective_to", "verdict_at"):
                assert column.server_default is None
            else:
                assert column.server_default is not None

    run_table = Base.metadata.tables["agent_test_run"]
    for column_name in AGENT_TEST_RUN_JSON_COLUMNS:
        column_type = run_table.c[column_name].type
        assert column_type._variant_mapping["postgresql"].__class__.__name__ == "JSONB"
        # Python None must bind as SQL NULL on both dialects, never JSON 'null'.
        assert column_type.none_as_null is True
        assert column_type._variant_mapping["postgresql"].none_as_null is True
    assert run_table.c.deterministic_check_results.server_default is None


def test_every_graph_foreign_key_is_named_and_restrictive_without_orm_delete_cascades() -> None:
    foreign_keys = []
    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        for constraint in table.foreign_key_constraints:
            foreign_keys.append((table_name, constraint))
            assert constraint.name
            assert constraint.ondelete == "RESTRICT"
    assert len(foreign_keys) == 12

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
        AgentTestRun,
        GraphReleaseTestRun,
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


def _foreign_keys(table) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    return {
        constraint.name: (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.foreign_key_constraints
    }


def _indexes(table) -> dict[str, tuple[str, ...]]:
    return {index.name: tuple(column.name for column in index.columns) for index in table.indexes}


def test_agent_test_run_model_exists() -> None:
    table = AgentTestRun.__table__
    assert table.name == "agent_test_run"
    assert {column.name: column.nullable for column in table.columns} == AGENT_TEST_RUN_COLUMNS
    assert tuple(column.name for column in table.primary_key.columns) == ("id",)
    assert _foreign_keys(table) == AGENT_TEST_RUN_FKS
    assert all(fk.ondelete == "RESTRICT" for fk in table.foreign_key_constraints)
    assert _indexes(table) == {"ix_agent_test_run_case_run_at": ("test_case_id", "run_at")}
    assert not any(column.index for column in table.columns)
    assert table.c.latency_ms.type.__class__.__name__ == "Float"
    assert str(table.c.run_kind.type) == "VARCHAR(24)"


def test_graph_release_test_run_model_exists() -> None:
    table = GraphReleaseTestRun.__table__
    assert table.name == "graph_release_test_run"
    assert {
        column.name: column.nullable for column in table.columns
    } == GRAPH_RELEASE_TEST_RUN_COLUMNS
    assert tuple(column.name for column in table.primary_key.columns) == (
        "graph_release_id",
        "agent_test_run_id",
    )
    assert _foreign_keys(table) == GRAPH_RELEASE_TEST_RUN_FKS
    assert all(fk.ondelete == "RESTRICT" for fk in table.foreign_key_constraints)
    assert _indexes(table) == {"ix_graph_release_test_run_run": ("agent_test_run_id",)}
    assert not any(column.index for column in table.columns)


def _seed_run_parents(conn) -> dict[str, int]:
    """One revision, one active release and one case: the parents a run references."""
    definition = load_graph_v1_manifest().definitions[0]
    payload = definition.model_dump(mode="json")
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
            created_by="test:unit",
        )
        .returning(AgentDefinitionRevision.id)
    ).scalar_one()
    release_id = conn.execute(
        GraphRelease.__table__.insert()
        .values(**_release_values(1, active=True))
        .returning(GraphRelease.id)
    ).scalar_one()
    case_id = conn.execute(
        AgentTestCase.__table__.insert()
        .values(
            agent_key=payload["agent_key"],
            name="required smoke",
            version=1,
            synthetic_payload={},
            assembly_context={"design_system_active": False},
            created_by="test:unit",
            updated_by="test:unit",
        )
        .returning(AgentTestCase.id)
    ).scalar_one()
    return {
        "agent_key": payload["agent_key"],
        "revision_id": revision_id,
        "release_id": release_id,
        "case_id": case_id,
    }


def _run_values(parents: dict[str, object], **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "test_case_id": parents["case_id"],
        "test_case_version": 1,
        "agent_key": parents["agent_key"],
        "run_kind": "candidate",
        "candidate_hash": "d" * 64,
        "compared_release_id": parents["release_id"],
        "compared_definition_revision_id": parents["revision_id"],
        "model_payload": {"user_request": "synthetic"},
        "assembled_prompt": "assembled",
        "candidate_raw_output": {"reply": "ok"},
        "candidate_structured_output": {"reply": "ok"},
        "deterministic_check_results": [{"name": "output_contract", "passed": True}],
        "deterministic_checks_passed": True,
        "execution_status": "completed",
        "run_by": "admin@example.com",
    }
    values.update(overrides)
    return values


# Each row violates exactly one named check on an otherwise well-formed run.
AGENT_TEST_RUN_CHECK_VIOLATIONS = [
    ("ck_agent_test_run_agent_key", {"agent_key": "foreman"}),
    ("ck_agent_test_run_case_version_positive", {"test_case_version": 0}),
    ("ck_agent_test_run_run_kind", {"run_kind": "rerun"}),
    ("ck_agent_test_run_execution_status", {"execution_status": "timeout"}),
    (
        "ck_agent_test_run_verdict_enum",
        {"verdict": "maybe", "verdict_reviewer": "r", "verdict_at": datetime.now(timezone.utc)},
    ),
    (
        "ck_agent_test_run_verdict_reviewer_paired",
        {"verdict": "rejected", "verdict_at": datetime.now(timezone.utc)},
    ),
    ("ck_agent_test_run_verdict_at_paired", {"verdict": "rejected", "verdict_reviewer": "r"}),
    (
        "ck_agent_test_run_approved_only_if_completed_and_passing",
        {
            "deterministic_checks_passed": False,
            "verdict": "approved",
            "verdict_reviewer": "r",
            "verdict_at": datetime.now(timezone.utc),
        },
    ),
    (
        "ck_agent_test_run_approved_only_if_completed_and_passing",
        {
            "execution_status": "incomplete",
            "candidate_structured_output": None,
            "deterministic_checks_passed": False,
            "verdict": "approved",
            "verdict_reviewer": "r",
            "verdict_at": datetime.now(timezone.utc),
        },
    ),
    ("ck_agent_test_run_completed_has_output", {"candidate_structured_output": None}),
    ("ck_agent_test_run_candidate_hash_len", {"candidate_hash": "d" * 63}),
    ("ck_agent_test_run_run_by_nonblank", {"run_by": "   "}),
]


def test_sqlite_accepts_well_formed_run_and_release_link_rows() -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as conn:
            parents = _seed_run_parents(conn)
            run_id = conn.execute(
                AgentTestRun.__table__.insert()
                .values(**_run_values(parents))
                .returning(AgentTestRun.id)
            ).scalar_one()
            approved_id = conn.execute(
                AgentTestRun.__table__.insert()
                .values(
                    **_run_values(
                        parents,
                        verdict="approved",
                        verdict_reviewer="reviewer@example.com",
                        verdict_at=datetime.now(timezone.utc),
                    )
                )
                .returning(AgentTestRun.id)
            ).scalar_one()
            conn.execute(
                GraphReleaseTestRun.__table__.insert().values(
                    graph_release_id=parents["release_id"],
                    agent_test_run_id=approved_id,
                    evidence_kind="approval",
                    source_release_id=None,
                )
            )
            stored = conn.execute(
                select(AgentTestRun).where(AgentTestRun.id == run_id)
            ).one()._mapping
            assert stored["run_at"] is not None
            assert stored["verdict"] is None
            assert stored["model_payload"] == {"user_request": "synthetic"}
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("constraint_name", "overrides"),
    AGENT_TEST_RUN_CHECK_VIOLATIONS,
    ids=[f"{name}-{index}" for index, (name, _) in enumerate(AGENT_TEST_RUN_CHECK_VIOLATIONS)],
)
def test_sqlite_rejects_each_agent_test_run_check_violation(
    constraint_name: str, overrides: dict[str, object]
) -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as conn:
            parents = _seed_run_parents(conn)
        with pytest.raises(IntegrityError, match=constraint_name):
            with engine.begin() as conn:
                conn.execute(
                    AgentTestRun.__table__.insert().values(**_run_values(parents, **overrides))
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("constraint_name", "evidence_kind", "use_source"),
    [
        ("ck_graph_release_test_run_evidence_kind", "rollback", False),
        ("ck_graph_release_test_run_source_paired", "historical_restore", False),
        ("ck_graph_release_test_run_source_paired", "approval", True),
    ],
)
def test_sqlite_rejects_each_release_link_check_violation(
    constraint_name: str, evidence_kind: str, use_source: bool
) -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as conn:
            parents = _seed_run_parents(conn)
            run_id = conn.execute(
                AgentTestRun.__table__.insert()
                .values(**_run_values(parents))
                .returning(AgentTestRun.id)
            ).scalar_one()
        with pytest.raises(IntegrityError, match=constraint_name):
            with engine.begin() as conn:
                conn.execute(
                    GraphReleaseTestRun.__table__.insert().values(
                        graph_release_id=parents["release_id"],
                        agent_test_run_id=run_id,
                        evidence_kind=evidence_kind,
                        source_release_id=parents["release_id"] if use_source else None,
                    )
                )
    finally:
        engine.dispose()


def test_sqlite_restricts_deleting_a_case_or_run_that_evidence_references() -> None:
    engine = _sqlite_engine()
    try:
        with engine.begin() as conn:
            parents = _seed_run_parents(conn)
            run_id = conn.execute(
                AgentTestRun.__table__.insert()
                .values(**_run_values(parents))
                .returning(AgentTestRun.id)
            ).scalar_one()
            conn.execute(
                GraphReleaseTestRun.__table__.insert().values(
                    graph_release_id=parents["release_id"],
                    agent_test_run_id=run_id,
                    evidence_kind="approval",
                )
            )
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            with engine.begin() as conn:
                conn.execute(
                    AgentTestCase.__table__.delete().where(
                        AgentTestCase.id == parents["case_id"]
                    )
                )
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            with engine.begin() as conn:
                conn.execute(AgentTestRun.__table__.delete().where(AgentTestRun.id == run_id))
        with engine.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(AgentTestRun)) == 1
            assert conn.scalar(select(func.count()).select_from(AgentTestCase)) == 1
            assert conn.scalar(select(func.count()).select_from(GraphReleaseTestRun)) == 1
    finally:
        engine.dispose()
