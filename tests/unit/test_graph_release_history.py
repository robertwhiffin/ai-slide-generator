"""#270 Task 1: the immutable, lock-free Graph Release history read model.

SQLite builds its own in-memory engine per test; releases after v1 are appended by
``append_release``, which follows the ``_publish_v2`` recipe in
``tests/integration/test_conversation_pin_acceptance_postgres.py`` (close the active
interval, insert the next version, map new revisions only for changed roles).  The
same helpers drive the PostgreSQL suite, where the mutation guards are installed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, delete, event, select, text, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401
import src.services.graph_release_history as history_module
from src.core.database import Base
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    AgentTestRun,
    GraphRelease,
    GraphReleaseAgent,
    GraphReleaseTestRun,
)
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_configuration_content import (
    GraphConfigurationIntegrityError,
    definition_content_from_row,
    revision_from_definition,
    validate_definition_hash,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.graph_release_history import (
    GraphVersionNotFound,
    ReleaseEvidence,
    ReleaseRef,
    list_release_history,
    read_release_detail,
)

ACTOR = "release-history@example.com"


# ---------------------------------------------------------------------------
# Shared builders (also imported by the PostgreSQL suite)
# ---------------------------------------------------------------------------


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def append_release(
    factory,
    *,
    note: str,
    prompt_suffixes: dict[str, str] | None = None,
    restored_from: int | None = None,
    actor: str = ACTOR,
    lock_timeout: str | None = None,
) -> int:
    """Publish the next Graph Version in one transaction and return its id.

    With ``restored_from`` the new release reuses that release's seven revision ids
    verbatim; otherwise it reuses the active mapping and maps a new revision for
    each role named in ``prompt_suffixes``.  ``lock_timeout`` (PostgreSQL only)
    bounds every lock wait, so a regression that makes a concurrent reader hold a
    row lock fails fast instead of hanging an in-process publisher.
    """
    with factory.begin() as db:
        if lock_timeout is not None:
            db.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
        active = db.scalars(
            select(GraphRelease).where(GraphRelease.effective_to.is_(None))
        ).one()
        closed_at = max(
            datetime.now(timezone.utc),
            _aware(active.effective_from) + timedelta(microseconds=1),
        )
        source_id = active.id if restored_from is None else restored_from
        target = dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == source_id)
            ).all()
        )
        assert set(target) == set(GRAPH_V1_AGENT_KEYS)
        for agent_key, suffix in (prompt_suffixes or {}).items():
            prior = db.get(AgentDefinitionRevision, target[agent_key])
            content = definition_content_from_row(prior)
            changed = content.model_copy(
                update={
                    "definition_version": content.definition_version + 1,
                    "prompt_text": content.prompt_text + suffix,
                }
            )
            revision = revision_from_definition(changed, actor=actor, timestamp=closed_at)
            db.add(revision)
            db.flush()
            target[agent_key] = revision.id

        # Close first: the one-active partial unique index is not deferrable.
        active.effective_to = closed_at
        db.flush()
        release = GraphRelease(
            version_number=active.version_number + 1,
            previous_release_id=active.id,
            restored_from_release_id=restored_from,
            release_note=note,
            published_by=actor,
            published_at=closed_at,
            effective_from=closed_at,
        )
        db.add(release)
        db.flush()
        for agent_key in GRAPH_V1_AGENT_KEYS:
            db.add(
                GraphReleaseAgent(
                    graph_release_id=release.id,
                    agent_key=agent_key,
                    agent_definition_revision_id=target[agent_key],
                )
            )
        return release.id


def seed_case(factory, *, agent_key: str, name: str) -> int:
    with factory.begin() as db:
        case = AgentTestCase(
            agent_key=agent_key,
            name=name,
            version=1,
            synthetic_payload={},
            assembly_context={"design_system_active": False},
            created_by=ACTOR,
            updated_by=ACTOR,
        )
        db.add(case)
        db.flush()
        return case.id


def seed_run(
    factory,
    *,
    case_id: int,
    agent_key: str,
    release_id: int,
    run_kind: str = "candidate",
) -> int:
    with factory.begin() as db:
        revision_id = db.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.graph_release_id == release_id,
                GraphReleaseAgent.agent_key == agent_key,
            )
        )
        run = AgentTestRun(
            test_case_id=case_id,
            test_case_version=1,
            agent_key=agent_key,
            run_kind=run_kind,
            candidate_hash="d" * 64,
            compared_release_id=release_id,
            compared_definition_revision_id=revision_id,
            model_payload={"user_request": "synthetic"},
            assembled_prompt="assembled",
            candidate_raw_output={"reply": "ok"},
            candidate_structured_output={"reply": "ok"},
            deterministic_check_results=[{"name": "output_contract", "passed": True}],
            deterministic_checks_passed=True,
            execution_status="completed",
            run_by=ACTOR,
            verdict="approved",
            verdict_reviewer=ACTOR,
            verdict_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()
        return run.id


def link_run(
    factory,
    *,
    release_id: int,
    run_id: int,
    evidence_kind: str = "approval",
    source_release_id: int | None = None,
) -> None:
    with factory.begin() as db:
        db.add(
            GraphReleaseTestRun(
                graph_release_id=release_id,
                agent_test_run_id=run_id,
                evidence_kind=evidence_kind,
                source_release_id=source_release_id,
            )
        )


def lineage_fixture(factory) -> dict[str, int]:
    """v1 bootstrap; v2 changes architect; v3 changes builder; v4 restores v2."""
    v1 = GraphConfiguration().bootstrap_v1(factory).release_id
    v2 = append_release(factory, note="v2", prompt_suffixes={"architect": "\n\nv2 architect"})
    v3 = append_release(factory, note="v3", prompt_suffixes={"builder": "\n\nv3 builder"})
    v4 = append_release(factory, note="Roll back to Graph Version 2.", restored_from=v2)
    return {"v1": v1, "v2": v2, "v3": v3, "v4": v4}


def assert_lineage(factory, ids: dict[str, int], entries) -> None:
    refs = {name: ReleaseRef(rid, int(name[1:])) for name, rid in ids.items()}
    assert [e.version_number for e in entries] == [4, 3, 2, 1]
    by_version = {e.version_number: e for e in entries}
    v1, v2, v3, v4 = (by_version[n] for n in (1, 2, 3, 4))

    assert [e.release_id for e in entries] == [ids["v4"], ids["v3"], ids["v2"], ids["v1"]]
    assert v4.previous == refs["v3"]
    assert v4.restored_from == refs["v2"]
    assert v4.changed_agent_keys == ("builder",)
    assert v4.restored_by == ()
    assert v3.previous == refs["v2"] and v3.restored_from is None
    assert v3.changed_agent_keys == ("builder",)
    assert v2.previous == refs["v1"] and v2.restored_from is None
    assert v2.restored_by == (refs["v4"],)
    assert v2.changed_agent_keys == ("architect",)
    assert v1.previous is None and v1.restored_from is None
    assert v1.restored_by == ()
    assert v1.changed_agent_keys == GRAPH_V1_AGENT_KEYS
    assert [e.is_active for e in entries] == [True, False, False, False]
    assert v4.effective_to is None

    with factory() as db:
        rows = {
            r.id: r
            for r in db.scalars(select(GraphRelease).execution_options(populate_existing=True))
        }
    for entry in entries:
        row = rows[entry.release_id]
        assert entry.release_note == row.release_note
        assert entry.published_by == row.published_by
        assert entry.published_at == row.published_at
        assert entry.effective_from == row.effective_from
        assert entry.effective_to == row.effective_to
    for older, newer in ((v1, v2), (v2, v3), (v3, v4)):
        assert older.effective_to == newer.effective_from


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda conn, _record: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# History list
# ---------------------------------------------------------------------------


def test_history_lists_every_version_newest_first_with_exact_lineage(factory):
    ids = lineage_fixture(factory)
    with factory() as db:
        entries = list_release_history(db)
    assert isinstance(entries, tuple)
    assert_lineage(factory, ids, entries)


def test_history_refreshes_a_release_already_loaded_in_the_session(factory):
    """Correction 11: the first statement overwrites stale identity-map state."""
    v1 = GraphConfiguration().bootstrap_v1(factory).release_id
    with factory() as db:
        stale_v1 = db.get(GraphRelease, v1)
        assert stale_v1.effective_to is None
        db.commit()  # expire_on_commit=False: v1 stays loaded with effective_to=None
        v2 = append_release(factory, note="v2", prompt_suffixes={"architect": "\n\nv2"})
        entries = list_release_history(db)
        assert stale_v1.effective_to is not None
    assert [(e.release_id, e.is_active) for e in entries] == [(v2, True), (v1, False)]


def test_history_with_no_release_is_an_integrity_error(factory):
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="no release"):
            list_release_history(db)


def test_no_active_release_is_an_integrity_error(factory):
    """Two active rows are unrepresentable (partial unique index); zero are not."""
    ids = lineage_fixture(factory)
    with factory.begin() as db:
        db.execute(
            update(GraphRelease)
            .where(GraphRelease.id == ids["v4"])
            .values(effective_to=datetime.now(timezone.utc) + timedelta(days=1))
            .execution_options(synchronize_session=False)
        )
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="exactly one active"):
            list_release_history(db)


def test_restored_from_outside_the_release_set_is_an_integrity_error(factory):
    ids = lineage_fixture(factory)
    with factory() as db:
        conn = db.connection()
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            update(GraphRelease)
            .where(GraphRelease.id == ids["v4"])
            .values(restored_from_release_id=9999)
        )
        db.commit()
        conn = db.connection()
        conn.execute(text("PRAGMA foreign_keys=ON"))
        db.commit()
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="outside"):
            list_release_history(db)


# ---------------------------------------------------------------------------
# Release detail
# ---------------------------------------------------------------------------


def _run_row(factory, run_id: int) -> AgentTestRun:
    with factory() as db:
        return db.get(AgentTestRun, run_id)


def _expected_evidence(factory, run_id, *, evidence_kind, source) -> ReleaseEvidence:
    run = _run_row(factory, run_id)
    return ReleaseEvidence(
        agent_test_run_id=run.id,
        agent_key=run.agent_key,
        test_case_id=run.test_case_id,
        test_case_version=run.test_case_version,
        evidence_kind=evidence_kind,
        source=source,
        verdict=run.verdict,
        verdict_reviewer=run.verdict_reviewer,
        verdict_at=run.verdict_at,
        execution_status=run.execution_status,
        deterministic_checks_passed=run.deterministic_checks_passed,
        run_at=run.run_at,
    )


def test_detail_has_exact_seven_definitions_and_ordered_evidence(factory):
    ids = lineage_fixture(factory)
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    run_id = seed_run(factory, case_id=case_id, agent_key="architect", release_id=ids["v1"])
    link_run(factory, release_id=ids["v2"], run_id=run_id)
    link_run(
        factory,
        release_id=ids["v4"],
        run_id=run_id,
        evidence_kind="historical_restore",
        source_release_id=ids["v2"],
    )

    with factory() as db:
        detail = read_release_detail(db, version_number=2)
        list_entry = {e.version_number: e for e in list_release_history(db)}[2]
    assert detail.entry == list_entry

    with factory() as db:
        mapping = dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == ids["v2"])
            ).all()
        )
        revisions = {key: db.get(AgentDefinitionRevision, rid) for key, rid in mapping.items()}
    assert tuple(detail.definitions) == GRAPH_V1_AGENT_KEYS
    with pytest.raises(TypeError):
        detail.definitions["architect"] = detail.definitions["builder"]  # type: ignore[index]
    for key in GRAPH_V1_AGENT_KEYS:
        definition = detail.definitions[key]
        revision = revisions[key]
        assert definition.agent_key == key
        assert definition.agent_definition_revision_id == revision.id
        assert definition.content_hash == revision.content_hash
        assert definition.content == validate_definition_hash(
            revision, expected_hash=revision.content_hash, label="expected"
        )
    assert detail.evidence == (
        _expected_evidence(factory, run_id, evidence_kind="approval", source=None),
    )
    assert detail.evidence[0].test_case_version == 1
    assert detail.evidence[0].verdict == "approved"

    with factory() as db:
        v4 = read_release_detail(db, version_number=4)
    assert v4.evidence == (
        _expected_evidence(
            factory,
            run_id,
            evidence_kind="historical_restore",
            source=ReleaseRef(ids["v2"], 2),
        ),
    )
    assert {k: d.agent_definition_revision_id for k, d in v4.definitions.items()} == mapping


def test_detail_orders_evidence_by_role_then_case_then_run(factory):
    ids = lineage_fixture(factory)
    builder_case = seed_case(factory, agent_key="builder", name="builder smoke")
    arch_x = seed_case(factory, agent_key="architect", name="architect x")
    arch_y = seed_case(factory, agent_key="architect", name="architect y")
    r_arch_y = seed_run(factory, case_id=arch_y, agent_key="architect", release_id=ids["v1"])
    r_builder = seed_run(factory, case_id=builder_case, agent_key="builder", release_id=ids["v1"])
    r_arch_x1 = seed_run(factory, case_id=arch_x, agent_key="architect", release_id=ids["v1"])
    r_arch_x2 = seed_run(factory, case_id=arch_x, agent_key="architect", release_id=ids["v1"])
    for run_id in (r_arch_x2, r_builder, r_arch_y, r_arch_x1):
        link_run(factory, release_id=ids["v3"], run_id=run_id)

    with factory() as db:
        detail = read_release_detail(db, version_number=3)
    assert [(e.agent_key, e.test_case_id, e.agent_test_run_id) for e in detail.evidence] == [
        ("architect", arch_x, r_arch_x1),
        ("architect", arch_x, r_arch_x2),
        ("architect", arch_y, r_arch_y),
        ("builder", builder_case, r_builder),
    ]


def test_detail_of_a_release_without_links_has_no_evidence(factory):
    ids = lineage_fixture(factory)
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    run_id = seed_run(factory, case_id=case_id, agent_key="architect", release_id=ids["v1"])
    link_run(factory, release_id=ids["v2"], run_id=run_id)
    with factory() as db:
        assert read_release_detail(db, version_number=1).evidence == ()
        assert read_release_detail(db, version_number=3).evidence == ()


@pytest.mark.parametrize("version_number", [0, 99])
def test_unknown_version_raises_not_found(factory, version_number):
    lineage_fixture(factory)
    with factory() as db:
        with pytest.raises(GraphVersionNotFound) as caught:
            read_release_detail(db, version_number=version_number)
    assert caught.value.version_number == version_number
    assert isinstance(caught.value, LookupError)


def test_linked_non_candidate_run_is_an_integrity_error(factory):
    ids = lineage_fixture(factory)
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    candidate = seed_run(factory, case_id=case_id, agent_key="architect", release_id=ids["v1"])
    baseline = seed_run(
        factory,
        case_id=case_id,
        agent_key="architect",
        release_id=ids["v1"],
        run_kind="published_baseline",
    )
    link_run(factory, release_id=ids["v2"], run_id=candidate)
    link_run(factory, release_id=ids["v2"], run_id=baseline)
    with factory() as db:
        with pytest.raises(
            GraphConfigurationIntegrityError,
            match="release evidence references a non-candidate run",
        ):
            read_release_detail(db, version_number=2)


def test_restore_link_source_outside_the_release_set_is_an_integrity_error(factory):
    ids = lineage_fixture(factory)
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    run_id = seed_run(factory, case_id=case_id, agent_key="architect", release_id=ids["v1"])
    with factory() as db:
        conn = db.connection()
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            GraphReleaseTestRun.__table__.insert().values(
                graph_release_id=ids["v4"],
                agent_test_run_id=run_id,
                evidence_kind="historical_restore",
                source_release_id=9999,
            )
        )
        db.commit()
        db.connection().execute(text("PRAGMA foreign_keys=ON"))
        db.commit()
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="outside"):
            read_release_detail(db, version_number=4)


def test_incomplete_mapping_is_an_integrity_error(factory):
    ids = lineage_fixture(factory)
    with factory.begin() as db:
        db.execute(
            delete(GraphReleaseAgent).where(
                GraphReleaseAgent.graph_release_id == ids["v2"],
                GraphReleaseAgent.agent_key == "fixer",
            )
        )
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="incomplete"):
            read_release_detail(db, version_number=2)
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="incomplete"):
            list_release_history(db)


def test_tampered_revision_content_is_an_integrity_error(factory):
    ids = lineage_fixture(factory)
    with factory() as db:
        revision_id = db.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.graph_release_id == ids["v2"],
                GraphReleaseAgent.agent_key == "architect",
            )
        )
    with factory.begin() as db:
        db.execute(
            update(AgentDefinitionRevision)
            .where(AgentDefinitionRevision.id == revision_id)
            .values(prompt_text="tampered")
        )
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="content hash"):
            read_release_detail(db, version_number=2)


def test_mapping_to_another_roles_revision_is_an_integrity_error(factory):
    ids = lineage_fixture(factory)
    with factory() as db:
        builder_revision = db.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.graph_release_id == ids["v2"],
                GraphReleaseAgent.agent_key == "builder",
            )
        )
        conn = db.connection()
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            update(GraphReleaseAgent)
            .where(
                GraphReleaseAgent.graph_release_id == ids["v2"],
                GraphReleaseAgent.agent_key == "architect",
            )
            .values(agent_definition_revision_id=builder_revision)
        )
        db.commit()
        db.connection().execute(text("PRAGMA foreign_keys=ON"))
        db.commit()
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="role"):
            read_release_detail(db, version_number=2)


# ---------------------------------------------------------------------------
# Boundary rules: no log content, no model or runtime collaborator
# ---------------------------------------------------------------------------


def test_history_reads_emit_no_application_log_record(factory, caplog):
    ids = lineage_fixture(factory)
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    run_id = seed_run(factory, case_id=case_id, agent_key="architect", release_id=ids["v1"])
    link_run(factory, release_id=ids["v2"], run_id=run_id)
    caplog.set_level(logging.DEBUG)
    with factory() as db:
        list_release_history(db)
        read_release_detail(db, version_number=2)
        with pytest.raises(GraphVersionNotFound):
            read_release_detail(db, version_number=99)
    assert [r for r in caplog.records if r.name.startswith("src")] == []


def test_history_module_has_no_model_or_runtime_collaborator():
    forbidden = (
        "src.services.agent_runtime",
        "src.services.agent_test_workbench",
        "src.services.agent_model_adapter",
        "src.services.endpoint_catalog",
        "src.services.graph_configuration_publication",
        "src.services.graph_configuration_draft",
    )
    imported = {
        getattr(value, "__module__", None) or getattr(value, "__name__", "")
        for value in vars(history_module).values()
    }
    assert not {name for name in imported if name and name.startswith(forbidden)}
