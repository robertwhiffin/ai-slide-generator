"""#270 Task 1 on real PostgreSQL: the history read model is lock-free and coherent.

The mutation guards (``_run_migrations``) are installed by ``postgres_engine``, so
every release here is appended the only way the guards allow: first close of the
active interval, then an insert, in one transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.database.models.graph_configuration import GraphRelease
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_release_history import (
    ReleaseRef,
    list_release_history,
    read_release_detail,
)
from tests.integration.test_graph_release_publication_postgres import (
    _drop_commit_failure,
    _install_commit_failure,
    _NoEvidenceGate,
    _save_prompt,
)
from tests.unit.test_graph_release_history import (
    append_release,
    assert_lineage,
    lineage_fixture,
    link_run,
    seed_case,
    seed_run,
)

pytestmark = pytest.mark.postgres

_FIRST_STATEMENT = "FROM GRAPH_RELEASE ORDER BY GRAPH_RELEASE.VERSION_NUMBER DESC"


def _normalized(statement: str) -> str:
    return " ".join(statement.upper().split())


@pytest.fixture
def factory(postgres_engine):
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)


def _publish_between_first_and_second_statement(connection, factory, published: list[int]):
    """After the history read's first statement, commit v3 on another connection."""
    statements: list[str] = []

    def after_cursor_execute(_conn, _cursor, statement, _params, _context, _many):
        normalized = _normalized(statement)
        statements.append(normalized)
        if not published and _FIRST_STATEMENT in normalized:
            published.append(
                append_release(
                    factory,
                    note="v3",
                    prompt_suffixes={"builder": "\n\nv3"},
                    lock_timeout="5s",
                )
            )

    event.listen(connection, "after_cursor_execute", after_cursor_execute)
    return statements


@pytest.mark.parametrize("reader", ["list", "detail"])
def test_history_is_coherent_when_a_release_commits_between_statements(
    postgres_engine, factory, reader
):
    v1 = GraphConfiguration().bootstrap_v1(factory).release_id
    v2 = append_release(factory, note="v2", prompt_suffixes={"architect": "\n\nv2"})

    published: list[int] = []
    with postgres_engine.connect() as connection:
        statements = _publish_between_first_and_second_statement(
            connection, factory, published
        )
        with Session(bind=connection) as db:
            assert db.scalar(text("SHOW transaction_isolation")) == "read committed"
            if reader == "list":
                entries = list_release_history(db)
            else:
                detail = read_release_detail(db, version_number=2)
                entries = (detail.entry,)
            # Same transaction, later statement: v3 is visible, so the commit
            # really landed between the history read's statements.
            visible = db.scalar(select(func.count()).select_from(GraphRelease))

    assert len(published) == 1, "the publication must fire exactly once"
    first = next(i for i, s in enumerate(statements) if _FIRST_STATEMENT in s)
    assert any("GRAPH_RELEASE_AGENT" in s for s in statements[first + 1 :]), (
        "a mapping statement must run after the concurrent commit"
    )
    assert visible == 3

    if reader == "list":
        assert [(e.release_id, e.version_number, e.is_active) for e in entries] == [
            (v2, 2, True),
            (v1, 1, False),
        ]
        assert entries[0].effective_to is None
        assert entries[0].restored_by == ()
        assert entries[0].changed_agent_keys == ("architect",)
    else:
        (entry,) = entries
        assert (entry.release_id, entry.is_active, entry.effective_to) == (v2, True, None)
        with factory() as db:
            v1_builder = read_release_detail(db, version_number=1).definitions["builder"]
        # v3 changed builder; v2's detail still maps v1's builder revision.
        assert detail.definitions["builder"].agent_definition_revision_id == (
            v1_builder.agent_definition_revision_id
        )

    with factory() as db:
        after = list_release_history(db)
    assert [(e.release_id, e.is_active) for e in after] == [
        (published[0], True),
        (v2, False),
        (v1, False),
    ]


def test_history_takes_no_row_lock(postgres_engine, factory):
    ids = lineage_fixture(factory)
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    run_id = seed_run(factory, case_id=case_id, agent_key="architect", release_id=ids["v1"])
    link_run(factory, release_id=ids["v2"], run_id=run_id)

    statements: list[str] = []

    def before_cursor_execute(_conn, _cursor, statement, _params, _context, _many):
        statements.append(_normalized(statement))

    event.listen(postgres_engine, "before_cursor_execute", before_cursor_execute)
    try:
        with factory() as db:
            list_release_history(db)
            detail = read_release_detail(db, version_number=2)
    finally:
        event.remove(postgres_engine, "before_cursor_execute", before_cursor_execute)

    assert len(detail.evidence) == 1
    assert sum(_FIRST_STATEMENT in s for s in statements) == 2
    assert any("AGENT_TEST_RUN" in s for s in statements)
    assert [s for s in statements if " FOR " in f" {s} "] == []


def test_history_reads_under_guards_and_restored_lineage_is_exact(factory):
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
        entries = list_release_history(db)
        v4 = read_release_detail(db, version_number=4)
    assert_lineage(factory, ids, entries)
    assert all(e.effective_from.tzinfo is not None for e in entries)
    assert [
        (e.agent_test_run_id, e.evidence_kind, e.source) for e in v4.evidence
    ] == [(run_id, "historical_restore", ReleaseRef(ids["v2"], 2))]


def _lock(factory) -> int:
    with factory() as db:
        snapshot = GraphConfiguration().read_workbench(db)
        db.rollback()
    return snapshot.draft.lock_version


def _publish(factory, note: str):
    with factory() as db:
        return GraphConfiguration().publish_draft(
            db,
            expected_lock_version=_lock(factory),
            release_note=note,
            actor="publisher@example.com",
            evidence_gate=_NoEvidenceGate(),
        )


def test_ids_diverging_from_versions_resolve_by_version_everywhere(postgres_engine, factory):
    """#270 Task 2 fix round 1 (I-1): a rolled-back publication burns a release id.

    The failed publication's INSERT consumed ``graph_release.id`` 2 before the
    deferred trigger rolled it back, so the releases are (id, version) =
    (1, 1), (3, 2), (4, 3).  Every read resolves by version number.
    """
    GraphConfiguration().bootstrap_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=_lock(factory))
    _install_commit_failure(postgres_engine)
    with pytest.raises(IntegrityError, match="injected commit failure"):
        _publish(factory, "burned")
    assert _drop_commit_failure(postgres_engine) == 1
    assert _publish(factory, "v2").release.version_number == 2
    _save_prompt(factory, "builder", "\n\nTune B.", lock=_lock(factory))
    assert _publish(factory, "v3").release.version_number == 3
    with factory() as db:
        rows = db.execute(
            select(GraphRelease.id, GraphRelease.version_number).order_by(
                GraphRelease.version_number
            )
        ).all()
    assert [tuple(r) for r in rows] == [(1, 1), (3, 2), (4, 3)]

    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    run_id = seed_run(factory, case_id=case_id, agent_key="architect", release_id=1)
    link_run(factory, release_id=3, run_id=run_id)

    with factory() as db:
        entries = list_release_history(db)
        detail = read_release_detail(db, version_number=2)
    assert [(e.release_id, e.version_number) for e in entries] == [(4, 3), (3, 2), (1, 1)]
    assert entries[0].previous == ReleaseRef(3, 2)
    assert entries[1].previous == ReleaseRef(1, 1)
    assert (detail.entry.release_id, detail.entry.version_number) == (3, 2)
    assert [e.agent_test_run_id for e in detail.evidence] == [run_id]

    with factory() as db:
        comparison = GraphConfiguration().compare_with_active(db, version_number=2)
    assert (comparison.active, comparison.historical) == (ReleaseRef(4, 3), ReleaseRef(3, 2))

    with factory() as db:
        preview = GraphConfiguration().preview_rollback(db, version_number=2)
    assert preview.source == ReleaseRef(3, 2)
    assert preview.active == ReleaseRef(4, 3)
    assert preview.next_version_number == 4
    assert preview.default_release_note == "Roll back to Graph Version 2."
    assert [(e.agent_test_run_id, e.source_release_id) for e in preview.evidence] == [
        (run_id, 3)
    ]
    assert preview.blocked is None
