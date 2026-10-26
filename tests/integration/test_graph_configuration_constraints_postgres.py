from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from src.core.database import _run_migrations
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    AgentTestRun,
    GraphDraft,
    GraphRelease,
    GraphReleaseAgent,
    GraphReleaseTestRun,
)

pytestmark = pytest.mark.postgres


def _revision_values(agent_key: str, *, digest_char: str = "a") -> dict[str, object]:
    return {
        "agent_key": agent_key,
        "definition_version": 2,
        "content_hash": digest_char * 64,
        "prompt_text": f"prompt for {agent_key}",
        "endpoint_name": "databricks-claude-opus-4-6",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
        "schema_overlay": {"field_overrides": {}, "additional_optional_fields": []},
        "assembly_rules": {"format_version": 1, "blocks": []},
        "protected_assembly_version": 1,
        "protected_assembly_digest": "b" * 64,
        "schema_contract_version": 1,
        "schema_contract_digest": "c" * 64,
        "created_by": "test:postgres",
    }


def _release_values(version_number: int, *, active: bool = True) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "version_number": version_number,
        "previous_release_id": None,
        "restored_from_release_id": None,
        "release_note": f"release {version_number}",
        "published_by": "test:postgres",
        "published_at": now,
        "effective_from": now,
        "effective_to": None if active else now + timedelta(seconds=1),
    }


def _insert_revision(conn, agent_key: str, digest_char: str = "a") -> int:
    return conn.execute(
        AgentDefinitionRevision.__table__.insert()
        .values(**_revision_values(agent_key, digest_char=digest_char))
        .returning(AgentDefinitionRevision.id)
    ).scalar_one()


def _insert_release(conn, version_number: int, *, active: bool = True) -> int:
    return conn.execute(
        GraphRelease.__table__.insert()
        .values(**_release_values(version_number, active=active))
        .returning(GraphRelease.id)
    ).scalar_one()


def _expect_integrity_error(engine, statement) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(statement)


def test_postgres_rejects_unknown_role_duplicate_hash_and_cross_role_mapping(
    postgres_engine,
) -> None:
    with postgres_engine.begin() as conn:
        architect_revision_id = _insert_revision(conn, "architect")
        release_id = _insert_release(conn, 1)

    _expect_integrity_error(
        postgres_engine,
        AgentDefinitionRevision.__table__.insert().values(
            **_revision_values("foreman", digest_char="f")
        ),
    )
    _expect_integrity_error(
        postgres_engine,
        AgentDefinitionRevision.__table__.insert().values(**_revision_values("architect")),
    )
    _expect_integrity_error(
        postgres_engine,
        GraphReleaseAgent.__table__.insert().values(
            graph_release_id=release_id,
            agent_key="builder",
            agent_definition_revision_id=architect_revision_id,
        ),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalar(select(GraphReleaseAgent.graph_release_id)) is None
        assert (
            conn.scalar(
                select(AgentDefinitionRevision.id).where(
                    AgentDefinitionRevision.agent_key == "foreman"
                )
            )
            is None
        )
        assert conn.scalars(select(AgentDefinitionRevision.id)).all() == [architect_revision_id]


def test_postgres_enforces_one_active_release_valid_intervals_and_singleton_draft(
    postgres_engine,
) -> None:
    with postgres_engine.begin() as conn:
        closed_id = _insert_release(conn, 1, active=False)
        active_id = _insert_release(conn, 2, active=True)

    _expect_integrity_error(
        postgres_engine,
        GraphRelease.__table__.insert().values(**_release_values(3, active=True)),
    )
    invalid_interval = _release_values(4, active=False)
    invalid_interval["effective_to"] = invalid_interval["effective_from"]
    _expect_integrity_error(
        postgres_engine,
        GraphRelease.__table__.insert().values(**invalid_interval),
    )

    with postgres_engine.begin() as conn:
        conn.execute(
            GraphDraft.__table__.insert().values(
                id=1,
                base_release_id=active_id,
                lock_version=0,
                updated_by="test:postgres",
            )
        )
    _expect_integrity_error(
        postgres_engine,
        GraphDraft.__table__.insert().values(
            id=2,
            base_release_id=closed_id,
            lock_version=0,
            updated_by="test:postgres",
        ),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalars(
            select(GraphRelease.version_number).order_by(GraphRelease.version_number)
        ).all() == [1, 2]
        assert conn.scalars(select(GraphDraft.id)).all() == [1]


def test_postgres_rejects_commit_that_closes_the_sole_active_release(
    postgres_engine,
) -> None:
    with postgres_engine.begin() as conn:
        release_id = _insert_release(conn, 1)

    closed_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    with pytest.raises(IntegrityError, match="exactly one active release"):
        with postgres_engine.begin() as conn:
            result = conn.execute(
                update(GraphRelease)
                .where(GraphRelease.id == release_id)
                .values(effective_to=closed_at)
            )
            assert result.rowcount == 1
            assert conn.scalar(
                select(GraphRelease.effective_to).where(GraphRelease.id == release_id)
            ) == closed_at

    with postgres_engine.connect() as conn:
        assert conn.scalar(
            select(GraphRelease.effective_to).where(GraphRelease.id == release_id)
        ) is None
        assert conn.scalar(
            select(func.count())
            .select_from(GraphRelease)
            .where(GraphRelease.effective_to.is_(None))
        ) == 1


def test_postgres_allows_atomic_close_and_successor_publication(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        first_release_id = _insert_release(conn, 1)

    closed_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    successor_values = _release_values(2)
    successor_values["previous_release_id"] = first_release_id
    successor_values["published_at"] = closed_at
    successor_values["effective_from"] = closed_at
    with postgres_engine.begin() as conn:
        assert (
            conn.execute(
                update(GraphRelease)
                .where(GraphRelease.id == first_release_id)
                .values(effective_to=closed_at)
            ).rowcount
            == 1
        )
        successor_id = conn.execute(
            GraphRelease.__table__.insert()
            .values(**successor_values)
            .returning(GraphRelease.id)
        ).scalar_one()

    with postgres_engine.connect() as conn:
        assert conn.execute(
            select(
                GraphRelease.id,
                GraphRelease.version_number,
                GraphRelease.effective_to,
            ).order_by(GraphRelease.version_number)
        ).all() == [
            (first_release_id, 1, closed_at),
            (successor_id, 2, None),
        ]
        assert conn.scalar(
            select(func.count())
            .select_from(GraphRelease)
            .where(GraphRelease.effective_to.is_(None))
        ) == 1


def test_postgres_restricts_deletion_of_referenced_release_and_revision(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        revision_id = _insert_revision(conn, "architect")
        release_id = _insert_release(conn, 1)
        conn.execute(
            GraphReleaseAgent.__table__.insert().values(
                graph_release_id=release_id,
                agent_key="architect",
                agent_definition_revision_id=revision_id,
            )
        )

    _expect_integrity_error(
        postgres_engine,
        delete(AgentDefinitionRevision).where(AgentDefinitionRevision.id == revision_id),
    )
    _expect_integrity_error(
        postgres_engine,
        delete(GraphRelease).where(GraphRelease.id == release_id),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalar(select(AgentDefinitionRevision.id)) == revision_id
        assert conn.scalar(select(GraphRelease.id)) == release_id


def test_postgres_mutation_guards_execute_trigger_bodies_and_allow_only_first_close(
    postgres_engine,
) -> None:
    with postgres_engine.begin() as conn:
        revision_id = _insert_revision(conn, "architect")
        release_id = _insert_release(conn, 1)
        conn.execute(
            GraphReleaseAgent.__table__.insert().values(
                graph_release_id=release_id,
                agent_key="architect",
                agent_definition_revision_id=revision_id,
            )
        )

    forbidden = (
        update(AgentDefinitionRevision)
        .where(AgentDefinitionRevision.id == revision_id)
        .values(prompt_text="mutated"),
        delete(AgentDefinitionRevision).where(AgentDefinitionRevision.id == revision_id),
        update(GraphReleaseAgent)
        .where(GraphReleaseAgent.graph_release_id == release_id)
        .values(agent_key="builder"),
        delete(GraphReleaseAgent).where(GraphReleaseAgent.graph_release_id == release_id),
        update(GraphRelease).where(GraphRelease.id == release_id).values(release_note="mutated"),
        delete(GraphRelease).where(GraphRelease.id == release_id),
    )
    for statement in forbidden:
        _expect_integrity_error(postgres_engine, statement)

    closed_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    successor_values = _release_values(2)
    successor_values["previous_release_id"] = release_id
    successor_values["published_at"] = closed_at
    successor_values["effective_from"] = closed_at
    with postgres_engine.begin() as conn:
        assert (
            conn.execute(
                update(GraphRelease)
                .where(GraphRelease.id == release_id)
                .values(effective_to=closed_at)
            ).rowcount
            == 1
        )
        conn.execute(GraphRelease.__table__.insert().values(**successor_values))

    _expect_integrity_error(
        postgres_engine,
        update(GraphRelease).where(GraphRelease.id == release_id).values(effective_to=None),
    )
    _expect_integrity_error(
        postgres_engine,
        update(GraphRelease)
        .where(GraphRelease.id == release_id)
        .values(effective_to=closed_at + timedelta(seconds=1)),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalar(select(AgentDefinitionRevision.prompt_text)) == "prompt for architect"
        assert conn.scalar(
            select(GraphRelease.release_note).where(GraphRelease.id == release_id)
        ) == "release 1"
        assert conn.scalar(
            select(GraphRelease.effective_to).where(GraphRelease.id == release_id)
        ) == closed_at
        assert conn.scalar(select(GraphReleaseAgent.agent_key)) == "architect"


def test_postgres_mutation_guard_migration_is_idempotent_and_schema_objects_are_active(
    postgres_engine,
) -> None:
    _run_migrations(postgres_engine)
    _run_migrations(postgres_engine)

    with postgres_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT c.relname, t.tgname, t.tgdeferrable, t.tginitdeferred "
                "FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal AND c.relname IN "
                "('agent_definition_revision', 'graph_release_agent', 'graph_release', "
                "'agent_test_run') "
                "ORDER BY c.relname, t.tgname"
            )
        ).all()
    assert triggers == [
        (
            "agent_definition_revision",
            "trg_agent_definition_revision_immutable",
            False,
            False,
        ),
        ("agent_test_run", "trg_agent_test_run_evidence_immutable", False, False),
        # #269 C14/C30: the linked-verdict freeze coexists with #267's trigger.
        ("agent_test_run", "trg_agent_test_run_linked_verdict_immutable", False, False),
        ("graph_release", "trg_graph_release_exactly_one_active", True, True),
        ("graph_release", "trg_graph_release_immutable", False, False),
        (
            "graph_release_agent",
            "trg_graph_release_agent_immutable",
            False,
            False,
        ),
    ]

    with postgres_engine.begin() as conn:
        release_id = _insert_release(conn, 1)
    _run_migrations(postgres_engine)
    with postgres_engine.connect() as conn:
        assert conn.scalar(
            select(GraphRelease.id).where(GraphRelease.effective_to.is_(None))
        ) == release_id

    with postgres_engine.begin() as conn:
        revision_id = _insert_revision(conn, "builder")
    _expect_integrity_error(
        postgres_engine,
        update(AgentDefinitionRevision)
        .where(AgentDefinitionRevision.id == revision_id)
        .values(prompt_text="body disabled"),
    )
    # The evidence trigger body also survives a re-run of the migration.
    with postgres_engine.begin() as conn:
        architect_revision_id = _insert_revision(conn, "architect", "e")
        case_id = _insert_case(conn)
        run_id = _insert_run(
            conn,
            {"revision_id": architect_revision_id, "release_id": release_id, "case_id": case_id},
        )
    _expect_sqlstate(
        postgres_engine,
        update(AgentTestRun).where(AgentTestRun.id == run_id).values(error_detail="rewritten"),
        "23514",
        None,
    )
    with postgres_engine.connect() as conn:
        # Exactly once and enabled (``O``) after both migration runs (#269 C14).
        assert conn.execute(
            text(
                "SELECT t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relname = 'agent_test_run' "
                "AND t.tgname = 'trg_agent_test_run_linked_verdict_immutable'"
            )
        ).scalars().all() == ["O"]
    # The linked-verdict body survives a re-run: an unlinked run's verdict still
    # changes, and once linked it cannot.
    with postgres_engine.begin() as conn:
        conn.execute(
            text("UPDATE agent_test_run SET verdict_notes = 'unlinked' WHERE id = :id"),
            {"id": run_id},
        )
        conn.execute(
            text(
                "INSERT INTO graph_release_test_run "
                "(graph_release_id, agent_test_run_id, evidence_kind, source_release_id) "
                "VALUES (:release_id, :run_id, 'approval', NULL)"
            ),
            {"release_id": release_id, "run_id": run_id},
        )
    _expect_sqlstate(
        postgres_engine,
        update(AgentTestRun).where(AgentTestRun.id == run_id).values(verdict_notes="linked"),
        "23514",
        None,
    )


# ---------------------------------------------------------------------------
# #267 Task 0: agent_test_run and graph_release_test_run DDL
# ---------------------------------------------------------------------------

AGENT_TEST_RUN_FK_NAMES = (
    "fk_agent_test_run_test_case",
    "fk_agent_test_run_release",
    "fk_agent_test_run_compatible_revision",
)
GRAPH_RELEASE_TEST_RUN_FK_NAMES = (
    "fk_graph_release_test_run_release",
    "fk_graph_release_test_run_run",
    "fk_graph_release_test_run_source",
)
AGENT_TEST_RUN_NOT_NULL_COLUMNS = (
    "test_case_id",
    "test_case_version",
    "agent_key",
    "run_kind",
    "candidate_hash",
    "compared_release_id",
    "compared_definition_revision_id",
    "model_payload",
    "deterministic_check_results",
    "deterministic_checks_passed",
    "execution_status",
    "run_by",
)
EVIDENCE_COLUMN_REWRITES = {
    "test_case_version": 2,
    "run_kind": "published_baseline",
    "candidate_hash": "f" * 64,
    "model_payload": {"rewritten": True},
    "assembled_prompt": "rewritten",
    "candidate_raw_output": {"rewritten": True},
    "candidate_structured_output": {"rewritten": True},
    "baseline_raw_output": {"rewritten": True},
    "baseline_structured_output": {"rewritten": True},
    "deterministic_check_results": [],
    "deterministic_checks_passed": False,
    "execution_status": "model_error",
    "error_detail": "rewritten",
    "latency_ms": 1.5,
    "input_tokens": 7,
    "output_tokens": 9,
    "run_by": "someone-else",
    # Rewrites resolved against a second, valid set of parents at run time, so the
    # FK and check would both accept the new value and only the trigger can raise.
    "id": "fresh_id",
    "test_case_id": "other_case_id",
    "compared_release_id": "other_release_id",
    "compared_definition_revision_id": "other_revision_id",
    "run_at": "other_run_at",
    # Check-valid. No architect revision can also be a builder one, so the composite
    # FK cannot be satisfied; it is an AFTER row trigger, so this BEFORE trigger
    # fires first, and the asserted message proves the trigger is what raised.
    "agent_key": "builder",
}
VERDICT_COLUMNS = frozenset({"verdict", "verdict_reviewer", "verdict_at", "verdict_notes"})
_RESOLVED_REWRITES = frozenset(
    {"id", "test_case_id", "compared_release_id", "compared_definition_revision_id", "run_at"}
)


def _insert_case(conn) -> int:
    return conn.execute(
        AgentTestCase.__table__.insert()
        .values(
            agent_key="architect",
            name="required smoke",
            version=1,
            synthetic_payload={"user_request": "synthetic"},
            assembly_context={"design_system_active": False},
            created_by="test:postgres",
            updated_by="test:postgres",
        )
        .returning(AgentTestCase.id)
    ).scalar_one()


def _seed_run_parents(conn) -> dict:
    """One architect revision, one active release and one architect case."""
    return {
        "revision_id": _insert_revision(conn, "architect"),
        "release_id": _insert_release(conn, 1),
        "case_id": _insert_case(conn),
    }


def _run_values(parents: dict, **overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "test_case_id": parents["case_id"],
        "test_case_version": 1,
        "agent_key": "architect",
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


def _insert_run(conn, parents: dict, **overrides) -> int:
    return conn.execute(
        AgentTestRun.__table__.insert()
        .values(**_run_values(parents, **overrides))
        .returning(AgentTestRun.id)
    ).scalar_one()


def _expect_sqlstate(engine, statement, pgcode: str, constraint_name: str | None):
    with pytest.raises(IntegrityError) as caught:
        with engine.begin() as conn:
            conn.execute(statement)
    assert caught.value.orig.pgcode == pgcode
    if constraint_name is not None:
        assert caught.value.orig.diag.constraint_name == constraint_name
    return caught.value


def test_postgres_create_all_builds_both_evidence_tables_with_jsonb_and_indexes(
    postgres_engine,
) -> None:
    with postgres_engine.connect() as conn:
        tables = set(
            conn.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        )
        json_types = dict(
            conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'agent_test_run' "
                    "AND data_type IN ('json', 'jsonb')"
                )
            ).all()
        )
        indexes = dict(
            conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename IN ('agent_test_run', 'graph_release_test_run') "
                    "AND indexname LIKE 'ix_%'"
                )
            ).all()
        )
    assert {"agent_test_run", "graph_release_test_run"} <= tables
    assert json_types == {
        "model_payload": "jsonb",
        "candidate_raw_output": "jsonb",
        "candidate_structured_output": "jsonb",
        "baseline_raw_output": "jsonb",
        "baseline_structured_output": "jsonb",
        "deterministic_check_results": "jsonb",
    }
    assert set(indexes) == {"ix_agent_test_run_case_run_at", "ix_graph_release_test_run_run"}
    assert indexes["ix_agent_test_run_case_run_at"].endswith("(test_case_id, run_at)")
    assert indexes["ix_graph_release_test_run_run"].endswith("(agent_test_run_id)")


def test_postgres_accepts_well_formed_agent_test_run_and_release_link(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        run_id = _insert_run(
            conn,
            parents,
            verdict="approved",
            verdict_reviewer="reviewer@example.com",
            verdict_at=datetime.now(timezone.utc),
        )
        conn.execute(
            GraphReleaseTestRun.__table__.insert().values(
                graph_release_id=parents["release_id"],
                agent_test_run_id=run_id,
                evidence_kind="approval",
                source_release_id=None,
            )
        )
        conn.execute(
            GraphReleaseTestRun.__table__.insert().values(
                graph_release_id=parents["release_id"],
                agent_test_run_id=_insert_run(conn, parents),
                evidence_kind="historical_restore",
                source_release_id=parents["release_id"],
            )
        )

        incomplete_id = _insert_run(
            conn,
            parents,
            execution_status="incomplete",
            assembled_prompt=None,
            candidate_raw_output=None,
            candidate_structured_output=None,
            deterministic_checks_passed=False,
        )

    with postgres_engine.connect() as conn:
        # Python None is SQL NULL on every evidence JSON column, not JSON 'null'.
        assert conn.scalar(
            text(
                "SELECT count(*) FROM agent_test_run WHERE id = :id "
                "AND candidate_raw_output IS NULL AND candidate_structured_output IS NULL "
                "AND baseline_raw_output IS NULL AND baseline_structured_output IS NULL"
            ),
            {"id": incomplete_id},
        ) == 1
        stored = conn.execute(select(AgentTestRun).where(AgentTestRun.id == run_id)).one()
        assert stored.run_at is not None
        assert stored.verdict == "approved"
        assert stored.model_payload == {"user_request": "synthetic"}
        assert conn.scalar(select(func.count()).select_from(GraphReleaseTestRun)) == 2


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
            "execution_status": "model_error",
            "candidate_structured_output": None,
            "deterministic_checks_passed": True,
            "verdict": "approved",
            "verdict_reviewer": "r",
            "verdict_at": datetime.now(timezone.utc),
        },
    ),
    ("ck_agent_test_run_completed_has_output", {"candidate_structured_output": None}),
    ("ck_agent_test_run_candidate_hash_len", {"candidate_hash": "d" * 63}),
    ("ck_agent_test_run_run_by_nonblank", {"run_by": "   "}),
]


@pytest.mark.parametrize(
    ("constraint_name", "overrides"),
    AGENT_TEST_RUN_CHECK_VIOLATIONS,
    ids=[f"{name}-{index}" for index, (name, _) in enumerate(AGENT_TEST_RUN_CHECK_VIOLATIONS)],
)
def test_postgres_rejects_each_agent_test_run_check_violation(
    postgres_engine, constraint_name: str, overrides: dict
) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
    _expect_sqlstate(
        postgres_engine,
        AgentTestRun.__table__.insert().values(**_run_values(parents, **overrides)),
        "23514",
        constraint_name,
    )
    with postgres_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(AgentTestRun)) == 0


@pytest.mark.parametrize("column_name", AGENT_TEST_RUN_NOT_NULL_COLUMNS)
def test_postgres_rejects_null_in_each_required_agent_test_run_column(
    postgres_engine, column_name: str
) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
    values = _run_values(parents)
    values[column_name] = None
    error = _expect_sqlstate(
        postgres_engine, AgentTestRun.__table__.insert().values(**values), "23502", None
    )
    assert error.orig.diag.column_name == column_name


@pytest.mark.parametrize(
    ("constraint_name", "evidence_kind", "use_source"),
    [
        ("ck_graph_release_test_run_evidence_kind", "rollback", False),
        ("ck_graph_release_test_run_source_paired", "historical_restore", False),
        ("ck_graph_release_test_run_source_paired", "approval", True),
    ],
)
def test_postgres_rejects_each_release_link_check_violation(
    postgres_engine, constraint_name: str, evidence_kind: str, use_source: bool
) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        run_id = _insert_run(conn, parents)
    _expect_sqlstate(
        postgres_engine,
        GraphReleaseTestRun.__table__.insert().values(
            graph_release_id=parents["release_id"],
            agent_test_run_id=run_id,
            evidence_kind=evidence_kind,
            source_release_id=parents["release_id"] if use_source else None,
        ),
        "23514",
        constraint_name,
    )


def test_postgres_run_revision_fk_is_role_compatible(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        builder_revision_id = _insert_revision(conn, "builder", "b")
    _expect_sqlstate(
        postgres_engine,
        AgentTestRun.__table__.insert().values(
            **_run_values(parents, compared_definition_revision_id=builder_revision_id)
        ),
        "23503",
        "fk_agent_test_run_compatible_revision",
    )
    _expect_sqlstate(
        postgres_engine,
        AgentTestRun.__table__.insert().values(
            **_run_values(parents, test_case_id=parents["case_id"] + 1000)
        ),
        "23503",
        "fk_agent_test_run_test_case",
    )


def test_postgres_restricts_deleting_a_test_case_referenced_by_a_run(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        _insert_run(conn, parents)
    # agent_test_case has no mutation trigger, so this is the FK itself (23503).
    _expect_sqlstate(
        postgres_engine,
        delete(AgentTestCase).where(AgentTestCase.id == parents["case_id"]),
        "23503",
        "fk_agent_test_run_test_case",
    )
    with postgres_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(AgentTestCase)) == 1
        assert conn.scalar(select(func.count()).select_from(AgentTestRun)) == 1


def test_postgres_restricts_deleting_a_run_linked_to_a_release(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        linked_id = _insert_run(conn, parents)
        unlinked_id = _insert_run(conn, parents)
        # Raw SQL: #267 writes no link rows; #269 owns the publication insert.
        conn.execute(
            text(
                "INSERT INTO graph_release_test_run "
                "(graph_release_id, agent_test_run_id, evidence_kind) "
                "VALUES (:release_id, :run_id, 'approval')"
            ),
            {"release_id": parents["release_id"], "run_id": linked_id},
        )
    _expect_sqlstate(
        postgres_engine,
        delete(AgentTestRun).where(AgentTestRun.id == linked_id),
        "23503",
        "fk_graph_release_test_run_run",
    )
    # An unlinked run stays deletable (#268's bounded cleanup).
    with postgres_engine.begin() as conn:
        assert (
            conn.execute(delete(AgentTestRun).where(AgentTestRun.id == unlinked_id)).rowcount
            == 1
        )
    with postgres_engine.connect() as conn:
        assert conn.scalars(select(AgentTestRun.id)).all() == [linked_id]


def test_postgres_every_evidence_fk_is_restrict_on_delete_in_pg_constraint(
    postgres_engine,
) -> None:
    # graph_release rows are also guarded by a 23514 delete trigger, so a delete
    # attempt cannot prove these FKs; read the catalogue instead (C21).
    with postgres_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conname, conrelid::regclass::text, confrelid::regclass::text, "
                "confdeltype, confupdtype "
                "FROM pg_constraint WHERE contype = 'f' "
                "AND conrelid::regclass::text IN ('agent_test_run', 'graph_release_test_run') "
                "ORDER BY conname"
            )
        ).all()
    assert rows == sorted(
        [
            ("fk_agent_test_run_compatible_revision", "agent_test_run",
             "agent_definition_revision", "r", "a"),
            ("fk_agent_test_run_release", "agent_test_run", "graph_release", "r", "a"),
            ("fk_agent_test_run_test_case", "agent_test_run", "agent_test_case", "r", "a"),
            ("fk_graph_release_test_run_release", "graph_release_test_run",
             "graph_release", "r", "a"),
            ("fk_graph_release_test_run_run", "graph_release_test_run",
             "agent_test_run", "r", "a"),
            ("fk_graph_release_test_run_source", "graph_release_test_run",
             "graph_release", "r", "a"),
        ]
    )


def test_evidence_rewrites_cover_every_non_verdict_agent_test_run_column() -> None:
    # Read from the table metadata, so a column added later cannot be silently exempt.
    assert set(EVIDENCE_COLUMN_REWRITES) == (
        set(AgentTestRun.__table__.columns.keys()) - VERDICT_COLUMNS
    )


@pytest.mark.parametrize("column_name", sorted(EVIDENCE_COLUMN_REWRITES))
def test_postgres_agent_test_run_evidence_columns_are_immutable(
    postgres_engine, column_name: str
) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        run_id = _insert_run(conn, parents)
        before = conn.execute(select(AgentTestRun).where(AgentTestRun.id == run_id)).one()
        resolved = {
            "fresh_id": run_id + 1000,
            "other_case_id": conn.execute(
                AgentTestCase.__table__.insert()
                .values(
                    agent_key="architect",
                    name="second case",
                    version=1,
                    synthetic_payload={},
                    assembly_context={"design_system_active": False},
                    created_by="test:postgres",
                    updated_by="test:postgres",
                )
                .returning(AgentTestCase.id)
            ).scalar_one(),
            "other_release_id": _insert_release(conn, 2, active=False),
            "other_revision_id": _insert_revision(conn, "architect", "e"),
            "other_run_at": before.run_at - timedelta(days=1),
        }
    rewrite = EVIDENCE_COLUMN_REWRITES[column_name]
    if column_name in _RESOLVED_REWRITES:
        rewrite = resolved[rewrite]
    error = _expect_sqlstate(
        postgres_engine,
        update(AgentTestRun)
        .where(AgentTestRun.id == run_id)
        .values(**{column_name: rewrite}),
        "23514",
        None,
    )
    assert "agent_test_run evidence is immutable" in str(error.orig)
    with postgres_engine.connect() as conn:
        assert conn.execute(select(AgentTestRun).where(AgentTestRun.id == run_id)).one() == before


def test_postgres_agent_test_run_verdict_columns_stay_writable(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        run_id = _insert_run(conn, parents)
        before = conn.execute(select(AgentTestRun).where(AgentTestRun.id == run_id)).one()
    verdict_at = datetime.now(timezone.utc)
    with postgres_engine.begin() as conn:
        assert (
            conn.execute(
                update(AgentTestRun)
                .where(AgentTestRun.id == run_id)
                .values(
                    verdict="approved",
                    verdict_reviewer="reviewer@example.com",
                    verdict_at=verdict_at,
                    verdict_notes="looks right",
                )
            ).rowcount
            == 1
        )
    with postgres_engine.connect() as conn:
        after = conn.execute(select(AgentTestRun).where(AgentTestRun.id == run_id)).one()
    assert (after.verdict, after.verdict_reviewer, after.verdict_at, after.verdict_notes) == (
        "approved",
        "reviewer@example.com",
        verdict_at,
        "looks right",
    )
    verdict_columns = {"verdict", "verdict_reviewer", "verdict_at", "verdict_notes"}
    for column_name in AgentTestRun.__table__.columns.keys():
        if column_name not in verdict_columns:
            assert getattr(after, column_name) == getattr(before, column_name)


def test_postgres_rejects_null_evidence_kind_on_a_release_link(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        parents = _seed_run_parents(conn)
        run_id = _insert_run(conn, parents)
    error = _expect_sqlstate(
        postgres_engine,
        GraphReleaseTestRun.__table__.insert().values(
            graph_release_id=parents["release_id"],
            agent_test_run_id=run_id,
            evidence_kind=None,
        ),
        "23502",
        None,
    )
    assert error.orig.diag.column_name == "evidence_kind"
