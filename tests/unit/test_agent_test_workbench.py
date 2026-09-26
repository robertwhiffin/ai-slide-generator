"""Agent Test Case create/read/update/retire service (#267 Task 2).

Binding corrections: C9 (refuse to remove a role's last active required case,
ordered issues, L2 ``FOR UPDATE`` without an ``is_active`` filter) and C22
(an update supersedes atomically; ``name`` is immutable; no sentinel;
``assembly_context`` is strictly ``{"design_system_active": bool}``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
import src.services.agent_test_workbench as workbench_module
from src.core.database import Base
from src.database.models.graph_configuration import AgentTestCase
from src.services.agent_test_workbench import (
    AgentTestWorkbench,
    TestCaseIssue,
    TestCaseNotFound,
    TestCaseRejected,
    TestCaseStale,
    TestCaseVersion,
)
from src.services.graph_configuration import BootstrapResult, GraphConfiguration
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS

ACTOR = "admin@example.com"
CONTEXT = {"design_system_active": False}
PAYLOAD = {"message": "Synthetic smoke input."}

UNKNOWN_AGENT = TestCaseIssue(
    "agent_key", "unknown_agent", "Agent key must identify an editable model role."
)
BLANK_NAME = TestCaseIssue("name", "blank", "Test case name must not be blank.")
LAST_REQUIRED_ACTIVE = TestCaseIssue(
    "is_active",
    "last_required_case",
    "A role must keep at least one active required test case. "
    "Add its replacement before retiring this one.",
)
LAST_REQUIRED_REQUIRED = TestCaseIssue(
    "is_required",
    "last_required_case",
    "A role must keep at least one active required test case. "
    "Add its replacement before retiring this one.",
)
NAME_IMMUTABLE = TestCaseIssue(
    "name", "name_immutable", "A test case name cannot be changed."
)


@pytest.fixture
def factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(session_factory)
    try:
        yield session_factory
    finally:
        engine.dispose()


def _rows(factory: sessionmaker) -> list[tuple[object, ...]]:
    with factory() as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    AgentTestCase.id,
                    AgentTestCase.agent_key,
                    AgentTestCase.name,
                    AgentTestCase.version,
                    AgentTestCase.is_active,
                    AgentTestCase.is_required,
                    AgentTestCase.synthetic_payload,
                    AgentTestCase.assembly_context,
                    AgentTestCase.created_by,
                    AgentTestCase.created_at,
                    AgentTestCase.updated_by,
                    AgentTestCase.updated_at,
                ).order_by(AgentTestCase.id)
            )
        ]


def _seed_case_id(factory: sessionmaker, agent_key: str = "architect") -> int:
    with factory() as session:
        return session.scalar(
            select(AgentTestCase.id).where(
                AgentTestCase.agent_key == agent_key,
                AgentTestCase.name == f"{agent_key}_required_smoke_v1",
            )
        )


def _create(factory: sessionmaker, **overrides: object) -> TestCaseVersion:
    arguments: dict[str, object] = {
        "agent_key": "architect",
        "name": "architect_extra",
        "synthetic_payload": PAYLOAD,
        "assembly_context": CONTEXT,
        "is_required": False,
        "actor": ACTOR,
    }
    arguments.update(overrides)
    with factory() as session:
        return AgentTestWorkbench().create_test_case(session, **arguments)


def _update(factory: sessionmaker, test_case_id: int, **overrides: object) -> TestCaseVersion:
    arguments: dict[str, object] = {
        "synthetic_payload": {"message": "revised"},
        "assembly_context": {"design_system_active": True},
        "is_required": True,
        "actor": "editor@example.com",
    }
    arguments.update(overrides)
    with factory() as session:
        return AgentTestWorkbench().update_test_case(
            session, test_case_id=test_case_id, **arguments
        )


def _deactivate(factory: sessionmaker, test_case_id: int, actor: str = "retirer@example.com"):
    with factory() as session:
        return AgentTestWorkbench().deactivate_test_case(
            session, test_case_id=test_case_id, actor=actor
        )


def _bootstrap_ok(factory: sessionmaker) -> BootstrapResult:
    result = GraphConfiguration().bootstrap_v1(factory)
    assert isinstance(result, BootstrapResult)
    assert result.created is False
    return result


# --- create -----------------------------------------------------------------


@pytest.mark.parametrize("agent_key", ["unknown", "foreman", "", "ARCHITECT"])
def test_create_rejects_an_agent_key_outside_the_editable_roles(factory, agent_key):
    """Catches a writer that trusts the caller's role or admits the deterministic foreman."""
    before = _rows(factory)
    with pytest.raises(ValueError) as caught:
        _create(factory, agent_key=agent_key)
    assert isinstance(caught.value, TestCaseRejected)
    assert caught.value.issues == (UNKNOWN_AGENT,)
    assert _rows(factory) == before


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_create_rejects_a_blank_name(factory, name):
    before = _rows(factory)
    with pytest.raises(ValueError) as caught:
        _create(factory, name=name)
    assert caught.value.issues == (BLANK_NAME,)
    assert _rows(factory) == before


def test_create_rejects_a_name_longer_than_200_characters_after_trimming(factory):
    with pytest.raises(TestCaseRejected) as caught:
        _create(factory, name="n" * 201)
    assert caught.value.issues == (
        TestCaseIssue("name", "too_long", "Test case name must be at most 200 characters."),
    )
    created = _create(factory, name="  " + "n" * 200 + "  ")
    assert created.name == "n" * 200


def test_create_inserts_version_one_active_with_the_exact_actor(factory):
    before = _rows(factory)
    created = _create(factory, name="  architect_extra  ", is_required=True)

    assert isinstance(created, TestCaseVersion)
    assert (
        created.agent_key,
        created.name,
        created.version,
        created.is_active,
        created.is_required,
        created.synthetic_payload,
        created.assembly_context,
        created.created_by,
        created.updated_by,
    ) == (
        "architect",
        "architect_extra",
        1,
        True,
        True,
        PAYLOAD,
        CONTEXT,
        ACTOR,
        ACTOR,
    )
    after = _rows(factory)
    assert after[: len(before)] == before
    assert len(after) == len(before) + 1
    assert after[-1][0] == created.id


def test_create_rejects_a_name_already_used_by_the_role_even_when_retired(factory):
    """Catches a second lineage starting at version 1 under an existing name."""
    extra = _create(factory)
    _deactivate(factory, extra.id)
    before = _rows(factory)
    for name in ("architect_extra", "architect_required_smoke_v1"):
        with pytest.raises(TestCaseRejected) as caught:
            _create(factory, name=name)
        assert caught.value.issues == (
            TestCaseIssue(
                "name", "duplicate_name", "This role already has a test case with this name."
            ),
        )
    assert _rows(factory) == before
    # The same name under another role is a different case.
    assert _create(factory, agent_key="builder", name="architect_extra").version == 1


@pytest.mark.parametrize(
    "payload",
    [[], "text", 1, None, True],
)
def test_create_requires_the_synthetic_payload_to_be_a_json_object(factory, payload):
    with pytest.raises(TestCaseRejected) as caught:
        _create(factory, synthetic_payload=payload)
    assert caught.value.issues == (
        TestCaseIssue(
            "synthetic_payload", "strict_type", "Synthetic payload must be a JSON object."
        ),
    )


def test_create_bounds_the_serialized_synthetic_payload_at_64_kib(factory):
    at_limit = {"k": "x" * (65536 - len('{"k":""}'))}
    assert len(json.dumps(at_limit, separators=(",", ":")).encode()) == 65536
    assert _create(factory, name="at_limit", synthetic_payload=at_limit).synthetic_payload == (
        at_limit
    )
    over = {"k": "x" * (65537 - len('{"k":""}'))}
    with pytest.raises(TestCaseRejected) as caught:
        _create(factory, name="over_limit", synthetic_payload=over)
    assert caught.value.issues == (
        TestCaseIssue(
            "synthetic_payload",
            "too_large",
            "Synthetic payload must be at most 65536 bytes as JSON.",
        ),
    )


@pytest.mark.parametrize(
    "payload",
    [{"x": float("nan")}, {"x": float("inf")}, {"x": object()}],
)
def test_create_rejects_a_payload_that_is_not_strict_json(factory, payload):
    with pytest.raises(TestCaseRejected) as caught:
        _create(factory, synthetic_payload=payload)
    assert caught.value.issues == (
        TestCaseIssue(
            "synthetic_payload",
            "invalid_json",
            "Synthetic payload must contain only JSON values.",
        ),
    )


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"design_system_active": "false"},
        {"design_system_active": 0},
        {"design_system_active": False, "root_session_id": "s"},
        [False],
        None,
    ],
)
def test_create_requires_the_assembly_context_to_be_exactly_design_system_active(
    factory, context
):
    """Catches an assembly context the runtime would not read (C22)."""
    with pytest.raises(TestCaseRejected) as caught:
        _create(factory, assembly_context=context)
    assert caught.value.issues == (
        TestCaseIssue(
            "assembly_context",
            "strict_type",
            'Assembly context must be exactly {"design_system_active": true or false}.',
        ),
    )


def test_create_orders_every_issue_by_field(factory):
    with pytest.raises(TestCaseRejected) as caught:
        _create(factory, name=" ", synthetic_payload=[], assembly_context={})
    assert [(issue.field, issue.code) for issue in caught.value.issues] == [
        ("name", "blank"),
        ("synthetic_payload", "strict_type"),
        ("assembly_context", "strict_type"),
    ]


@pytest.mark.parametrize("actor", ["", "   ", None])
def test_every_write_requires_a_nonblank_trusted_actor(factory, actor):
    seed_id = _seed_case_id(factory)
    before = _rows(factory)
    expected = TestCaseIssue("actor", "blank", "Actor must not be blank.")
    for write in (
        lambda: _create(factory, actor=actor),
        lambda: _update(factory, seed_id, actor=actor),
        lambda: _deactivate(factory, seed_id, actor=actor),
    ):
        with pytest.raises(TestCaseRejected) as caught:
            write()
        assert caught.value.issues[0] == expected
    assert _rows(factory) == before


# --- update (supersede) ----------------------------------------------------


def test_update_supersedes_the_old_row_and_inserts_the_next_version(factory):
    """Catches an in-place mutation or two active versions of one case (C22)."""
    seed_id = _seed_case_id(factory)
    before = {row[0]: row for row in _rows(factory)}

    updated = _update(factory, seed_id)

    assert updated.id != seed_id
    assert (updated.name, updated.version, updated.is_active, updated.is_required) == (
        "architect_required_smoke_v1",
        2,
        True,
        True,
    )
    assert updated.synthetic_payload == {"message": "revised"}
    assert updated.assembly_context == {"design_system_active": True}
    assert (updated.created_by, updated.updated_by) == (
        "editor@example.com",
        "editor@example.com",
    )
    after = {row[0]: row for row in _rows(factory)}
    old_before, old_after = before[seed_id], after[seed_id]
    # Only the retirement columns (is_active, updated_by, updated_at) changed.
    assert old_after[:4] == old_before[:4]
    assert old_after[5:10] == old_before[5:10]
    assert (old_after[4], old_after[10]) == (False, "editor@example.com")
    assert {key: row for key, row in after.items() if key not in {seed_id, updated.id}} == {
        key: row for key, row in before.items() if key != seed_id
    }
    with factory() as session:
        active = session.scalars(
            select(AgentTestCase.version).where(
                AgentTestCase.agent_key == "architect",
                AgentTestCase.name == "architect_required_smoke_v1",
                AgentTestCase.is_active.is_(True),
            )
        ).all()
    assert active == [2]
    _bootstrap_ok(factory)


def test_a_historical_row_is_never_modified_after_its_own_retirement(factory):
    seed_id = _seed_case_id(factory)
    v2 = _update(factory, seed_id)
    v1_after_retirement = next(row for row in _rows(factory) if row[0] == seed_id)
    v3 = _update(factory, v2.id, synthetic_payload={"message": "third"})
    assert v3.version == 3
    rows = {row[0]: row for row in _rows(factory)}
    assert rows[seed_id] == v1_after_retirement
    assert rows[v2.id][4] is False


def test_update_accepts_the_unchanged_name_and_rejects_a_rename(factory):
    seed_id = _seed_case_id(factory)
    before = _rows(factory)
    with pytest.raises(TestCaseRejected) as caught:
        _update(factory, seed_id, name="architect_renamed")
    assert caught.value.issues == (NAME_IMMUTABLE,)
    assert _rows(factory) == before
    same = _update(factory, seed_id, name="  architect_required_smoke_v1 ")
    assert same.name == "architect_required_smoke_v1"


def test_update_of_a_superseded_or_retired_version_is_stale(factory):
    seed_id = _seed_case_id(factory)
    _update(factory, seed_id)
    extra = _create(factory)
    _deactivate(factory, extra.id)
    before = _rows(factory)
    for stale_id in (seed_id, extra.id):
        with pytest.raises(TestCaseStale) as caught:
            _update(factory, stale_id)
        assert caught.value.test_case_id == stale_id
    assert _rows(factory) == before


def test_update_and_deactivate_of_an_unknown_id_is_not_found(factory):
    before = _rows(factory)
    with pytest.raises(TestCaseNotFound):
        _update(factory, 999_999)
    with pytest.raises(TestCaseNotFound):
        _deactivate(factory, 999_999)
    assert _rows(factory) == before


def test_update_validates_the_payload_and_context_like_create(factory):
    seed_id = _seed_case_id(factory)
    with pytest.raises(TestCaseRejected) as caught:
        _update(factory, seed_id, synthetic_payload=[], assembly_context={"x": 1})
    assert [(issue.field, issue.code) for issue in caught.value.issues] == [
        ("synthetic_payload", "strict_type"),
        ("assembly_context", "strict_type"),
    ]


def test_a_unique_constraint_loss_is_reported_as_stale(factory, monkeypatch):
    """Catches a concurrent supersede surfacing as a 500 instead of 409 (C22)."""
    seed_id = _seed_case_id(factory)
    _update(factory, seed_id)  # version 2 now exists
    original = workbench_module._reread_role_rows

    def _stale_view(session, agent_key):
        rows = original(session, agent_key)
        # Pretend version 2 was committed after this writer's snapshot and is
        # invisible, while the retired version 1 still reads as active.
        visible = [row for row in rows if row.version != 2]
        for row in visible:
            if row.id == seed_id:
                row.is_active = True
        return visible

    monkeypatch.setattr(workbench_module, "_reread_role_rows", _stale_view)
    with pytest.raises(TestCaseStale) as caught:
        _update(factory, seed_id)
    assert caught.value.test_case_id == seed_id


# --- deactivate (retire) ----------------------------------------------------


def test_deactivate_retires_without_deleting_and_is_idempotent(factory):
    extra = _create(factory)
    before = {row[0]: row for row in _rows(factory)}

    retired = _deactivate(factory, extra.id)

    assert (retired.id, retired.is_active, retired.updated_by) == (
        extra.id,
        False,
        "retirer@example.com",
    )
    after = {row[0]: row for row in _rows(factory)}
    assert set(after) == set(before)
    assert after[extra.id][:4] == before[extra.id][:4]
    assert after[extra.id][5:10] == before[extra.id][5:10]
    assert after[extra.id][4] is False

    again = _deactivate(factory, extra.id, actor="someone-else@example.com")
    assert again == retired
    assert {row[0]: row for row in _rows(factory)} == after


# --- the last-required guard (C9) ------------------------------------------


@pytest.mark.parametrize("agent_key", GRAPH_V1_AGENT_KEYS)
def test_deactivating_a_roles_last_active_required_case_is_refused(factory, agent_key):
    """Catches the one admin click that makes the next boot exit (C9)."""
    seed_id = _seed_case_id(factory, agent_key)
    before = _rows(factory)
    with pytest.raises(TestCaseRejected) as caught:
        _deactivate(factory, seed_id)
    assert caught.value.issues == (LAST_REQUIRED_ACTIVE,)
    assert _rows(factory) == before
    _bootstrap_ok(factory)


def test_unrequiring_the_last_active_required_case_is_refused(factory):
    seed_id = _seed_case_id(factory)
    before = _rows(factory)
    with pytest.raises(TestCaseRejected) as caught:
        _update(factory, seed_id, is_required=False)
    assert caught.value.issues == (LAST_REQUIRED_REQUIRED,)
    assert _rows(factory) == before
    _bootstrap_ok(factory)


def test_a_refused_supersede_reports_every_issue_in_field_order(factory):
    seed_id = _seed_case_id(factory)
    with pytest.raises(TestCaseRejected) as caught:
        _update(
            factory,
            seed_id,
            name="renamed",
            synthetic_payload=[],
            assembly_context={},
            is_required=False,
        )
    assert caught.value.issues == (
        NAME_IMMUTABLE,
        TestCaseIssue(
            "synthetic_payload", "strict_type", "Synthetic payload must be a JSON object."
        ),
        TestCaseIssue(
            "assembly_context",
            "strict_type",
            'Assembly context must be exactly {"design_system_active": true or false}.',
        ),
        LAST_REQUIRED_REQUIRED,
    )


def test_superseding_the_last_required_case_as_required_is_allowed(factory):
    seed_id = _seed_case_id(factory)
    assert _update(factory, seed_id, is_required=True).is_required is True
    _bootstrap_ok(factory)


def test_replacing_the_only_required_case_is_add_then_retire(factory):
    """P3: the replacement must be added before the old case can be retired."""
    seed_id = _seed_case_id(factory)
    with pytest.raises(TestCaseRejected):
        _deactivate(factory, seed_id)
    replacement = _create(factory, name="architect_replacement", is_required=True)
    retired = _deactivate(factory, seed_id)
    assert retired.is_active is False
    with pytest.raises(TestCaseRejected) as caught:
        _deactivate(factory, replacement.id)
    assert caught.value.issues == (LAST_REQUIRED_ACTIVE,)
    _bootstrap_ok(factory)


def test_optional_and_inactive_rows_do_not_count_as_required_coverage(factory):
    seed_id = _seed_case_id(factory)
    optional = _create(factory, name="architect_optional", is_required=False)
    required = _create(factory, name="architect_second", is_required=True)
    _deactivate(factory, required.id)  # allowed: the seed still covers the role
    with pytest.raises(TestCaseRejected):
        _deactivate(factory, seed_id)
    assert _deactivate(factory, optional.id).is_active is False
    # The other roles are untouched by architect's coverage.
    builder_extra = _create(factory, agent_key="builder", name="b2", is_required=True)
    assert _deactivate(factory, builder_extra.id).is_active is False
    _bootstrap_ok(factory)


def test_the_role_lock_statement_is_for_update_over_every_row_of_the_role():
    """Catches an is_active filter or a missing FOR UPDATE on the L2 lock (C9)."""
    statement = workbench_module._role_lock_statement("architect")
    compiled = " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).split()
    )
    assert compiled.endswith(
        "FROM agent_test_case WHERE agent_test_case.agent_key = 'architect' "
        "ORDER BY agent_test_case.id FOR UPDATE"
    )
    assert "is_active" not in compiled.split("FROM", 1)[1]


# --- list -------------------------------------------------------------------


def test_list_returns_active_versions_in_role_order_by_default(factory):
    seed_id = _seed_case_id(factory)
    v2 = _update(factory, seed_id)
    extra = _create(factory, agent_key="builder", name="aaa_builder")
    with factory() as session:
        listed = AgentTestWorkbench().list_test_cases(session)
    assert [(case.agent_key, case.name, case.version) for case in listed] == [
        ("architect", "architect_required_smoke_v1", 2),
        ("data_analyst", "data_analyst_required_smoke_v1", 1),
        ("builder", "aaa_builder", 1),
        ("builder", "builder_required_smoke_v1", 1),
        ("build_reviewer", "build_reviewer_required_smoke_v1", 1),
        ("fixer", "fixer_required_smoke_v1", 1),
        ("fix_reviewer", "fix_reviewer_required_smoke_v1", 1),
        ("deck_reviewer", "deck_reviewer_required_smoke_v1", 1),
    ]
    assert listed[0].id == v2.id
    assert listed[2].id == extra.id


def test_list_filters_by_role_and_can_include_inactive_versions(factory):
    seed_id = _seed_case_id(factory)
    _update(factory, seed_id)
    with factory() as session:
        listed = AgentTestWorkbench().list_test_cases(
            session, agent_key="architect", include_inactive=True
        )
    assert [(case.version, case.is_active) for case in listed] == [(1, False), (2, True)]


def test_list_rejects_an_unknown_role_filter(factory):
    with factory() as session, pytest.raises(TestCaseRejected) as caught:
        AgentTestWorkbench().list_test_cases(session, agent_key="foreman")
    assert caught.value.issues == (UNKNOWN_AGENT,)


# --- fix round 1: identical saves, atomic supersede, optional rows ------------


def _case_count(factory: sessionmaker) -> int:
    return len(_rows(factory))


def test_an_identical_update_is_a_no_op_returning_the_current_version(factory):
    """Catches an unchanged save orphaning the current version's approvals (I1)."""
    created = _create(
        factory,
        synthetic_payload={"b": [1, 2.5, True, None], "a": {"y": "z"}},
        assembly_context={"design_system_active": True},
        is_required=False,
    )
    before = _rows(factory)

    same = _update(
        factory,
        created.id,
        name="architect_extra",
        # Different key order, same content.
        synthetic_payload={"a": {"y": "z"}, "b": [1, 2.5, True, None]},
        assembly_context={"design_system_active": True},
        is_required=False,
        actor="someone-else@example.com",
    )

    assert same == created
    assert _rows(factory) == before


@pytest.mark.parametrize(
    ("stored", "submitted"),
    [(1, True), (1, 1.0), (True, 1), (0, False), (1.0, 1)],
    ids=["int-to-bool", "int-to-float", "bool-to-int", "zero-to-false", "float-to-int"],
)
def test_a_type_only_payload_change_is_a_real_new_version(factory, stored, submitted):
    """Catches Python == equating 1, 1.0 and True and dropping a real edit (I1)."""
    created = _create(factory, synthetic_payload={"a": stored})
    updated = _update(
        factory,
        created.id,
        synthetic_payload={"a": submitted},
        assembly_context=CONTEXT,
        is_required=False,
    )
    assert (updated.version, updated.id != created.id) == (2, True)
    assert type(updated.synthetic_payload["a"]) is type(submitted)


@pytest.mark.parametrize(
    "change",
    [
        {"is_required": True},
        {"assembly_context": {"design_system_active": True}},
        {"synthetic_payload": {"message": "Synthetic smoke input!"}},
    ],
    ids=["is_required", "assembly_context", "synthetic_payload"],
)
def test_any_single_field_change_is_a_real_new_version(factory, change):
    created = _create(factory)
    arguments = {
        "synthetic_payload": PAYLOAD,
        "assembly_context": CONTEXT,
        "is_required": False,
        **change,
    }
    assert _update(factory, created.id, **arguments).version == 2


def test_an_update_commits_exactly_once(factory):
    """Catches a supersede split across commits (I2)."""
    seed_id = _seed_case_id(factory)
    commits: list[str] = []
    with factory() as session:
        event.listen(session, "after_commit", lambda _s: commits.append("commit"))
        AgentTestWorkbench().update_test_case(
            session,
            test_case_id=seed_id,
            synthetic_payload={"message": "revised"},
            assembly_context=CONTEXT,
            is_required=True,
            actor=ACTOR,
        )
    assert commits == ["commit"]


def test_a_failed_successor_insert_leaves_the_old_version_active(factory):
    """Catches a retirement committed without its successor (I2)."""
    seed_id = _seed_case_id(factory)
    before = _rows(factory)
    engine = factory.kw["bind"]

    def _fail_successor_insert(_conn, _cursor, statement, _params, _context, _many):
        if " ".join(statement.upper().split()).startswith("INSERT INTO AGENT_TEST_CASE"):
            raise RuntimeError("injected successor insert failure")

    event.listen(engine, "before_cursor_execute", _fail_successor_insert)
    try:
        with pytest.raises(RuntimeError, match="injected successor insert failure"):
            _update(factory, seed_id)
    finally:
        event.remove(engine, "before_cursor_execute", _fail_successor_insert)

    assert _rows(factory) == before
    seed = next(row for row in _rows(factory) if row[0] == seed_id)
    assert (seed[4], seed[5]) == (True, True)
    _bootstrap_ok(factory)


def test_a_failed_retirement_leaves_no_successor_behind(factory):
    """Catches a successor committed before the old version is retired (I2)."""
    seed_id = _seed_case_id(factory)
    before = _rows(factory)
    engine = factory.kw["bind"]

    def _fail_retirement(_conn, _cursor, statement, _params, _context, _many):
        if " ".join(statement.upper().split()).startswith("UPDATE AGENT_TEST_CASE"):
            raise RuntimeError("injected retirement failure")

    event.listen(engine, "before_cursor_execute", _fail_retirement)
    try:
        with pytest.raises(RuntimeError, match="injected retirement failure"):
            _update(factory, seed_id)
    finally:
        event.remove(engine, "before_cursor_execute", _fail_retirement)

    assert _rows(factory) == before
    with factory() as session:
        assert session.scalars(
            select(AgentTestCase.version).where(
                AgentTestCase.agent_key == "architect",
                AgentTestCase.name == "architect_required_smoke_v1",
                AgentTestCase.is_active.is_(True),
            )
        ).all() == [1]
    _bootstrap_ok(factory)


def test_an_active_optional_case_does_not_stop_the_unrequire_refusal(factory):
    """Catches a last-required count that ignores is_required on the update path (I3)."""
    seed_id = _seed_case_id(factory)
    _create(factory, name="architect_optional", is_required=False)
    before = _rows(factory)
    with pytest.raises(TestCaseRejected) as caught:
        _update(factory, seed_id, is_required=False)
    assert caught.value.issues == (LAST_REQUIRED_REQUIRED,)
    assert _rows(factory) == before
    _bootstrap_ok(factory)


# --- fix round 2: the inactive-row 409 precedes the no-op -----------------------


@pytest.mark.parametrize("state", ["superseded", "retired"])
def test_an_identical_save_to_an_inactive_version_is_still_stale(factory, state):
    """Catches the no-op check running before the inactive-row 409 (fix round 2)."""
    if state == "superseded":
        target = _seed_case_id(factory)
        _update(factory, target)
    else:
        target = _create(factory, name="architect_to_retire").id
        _deactivate(factory, target)
    with factory() as session:
        row = session.get(AgentTestCase, target)
        stored = (row.name, row.synthetic_payload, row.assembly_context, row.is_required)
        assert row.is_active is False
    before = _rows(factory)

    with pytest.raises(TestCaseStale) as caught:
        _update(
            factory,
            target,
            name=stored[0],
            synthetic_payload=stored[1],
            assembly_context=stored[2],
            is_required=stored[3],
        )

    assert caught.value.test_case_id == target
    assert _rows(factory) == before


# ===========================================================================
# #267 Task 4: test run execution and persistence
#
# Binding corrections: C8/C32 (no transaction or lock across the model call;
# the saved-candidate read is #266's probe read; a stale lock is the 409 with no
# model call), C10/C37 (every role's model sees the production projection),
# C15/C16/C17 (raw output from the runtime's observer, the exact status map, no
# exception text, checks from the runtime's single validation), C20 (the
# baseline is the newest completed published-baseline run for this case row
# and revision, copied in; reruns go through ``run``), C27/M-1 (identity from
# the transaction-1 snapshot, never a ``-1`` sentinel).
# ===========================================================================

import logging  # noqa: E402

from sqlalchemy import update  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from src.database.models.graph_configuration import (  # noqa: E402
    AgentTestRun,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.agent_model_payload import (  # noqa: E402
    MODEL_PAYLOAD_KEYS,
    model_payload_for,
)
from src.services.agent_runtime import (  # noqa: E402
    MODEL_DRIVEN_AGENT_KEYS,
    AgentRuntime,
)
from src.services.agent_runtime_identity import (  # noqa: E402
    RecordingAgentInvocationIdentitySink,
)
from src.services.agent_test_workbench import (  # noqa: E402
    DeterministicCheckIssue,
    DeterministicCheckResult,
    TestRunCaseInactive,
    TestRunCaseRoleMismatch,
    TestRunEvidence,
    TestRunNotFound,
    TestRunUnavailable,
)
from src.services.graph_configuration import (  # noqa: E402
    DraftContentRejected,
    DraftSaveConflict,
    EditableModelDraft,
)
from src.services.graph_configuration_content import (  # noqa: E402
    GraphConfigurationIntegrityError,
    definition_content_from_row,
    definition_content_values,
)
from src.services.graph_configuration_seed import REQUIRED_SMOKE_PAYLOADS  # noqa: E402
from src.services.graph_definition_manifest import (  # noqa: E402
    ContentIdentity,
    definition_content_hash,
)
from src.services.persisted_graph_release import (  # noqa: E402
    PersistedGraphReleaseLoader,
)
from tests.fixtures.deterministic_model_adapter import (  # noqa: E402
    DeterministicFakeModelAdapter,
    fake_output,
)

RUNNER = "runner@example.com"
_SEEDED_IDENTIFIERS = (
    "synthetic-architect",
    "synthetic-data-analyst",
    "synthetic-builder",
    "synthetic-turn",
    "system:bootstrap",
    "synthetic-deck-reviewer",
)
_PASSED_CONTRACT = DeterministicCheckResult(
    name="output_contract", passed=True, message=None, issues=()
)


class _HookedFakeAdapter(DeterministicFakeModelAdapter):
    """The deterministic fake, plus a hook run inside ``invoke`` (C8 proofs)."""

    def __init__(self, *, on_invoke=None, raise_error: Exception | None = None, **kwargs):
        super().__init__(**kwargs)
        self.on_invoke = on_invoke
        self.raise_error = raise_error

    def invoke(self, *, agent_key, configuration, schema, prompt):
        if self.on_invoke is not None:
            self.on_invoke()
        if self.raise_error is not None:
            self.calls.append(None)  # type: ignore[arg-type]
            raise self.raise_error
        return super().invoke(
            agent_key=agent_key, configuration=configuration, schema=schema, prompt=prompt
        )


class _SpyRuntime(AgentRuntime):
    """The real runtime, recording the arguments of its two public entry points."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.candidate_calls: list[tuple] = []
        self.run_calls: list[tuple] = []
        self.baseline_calls: list[tuple] = []

    def run_candidate(
        self,
        agent_key,
        candidate_content,
        candidate_hash,
        payload,
        assembly_context,
        *,
        observation=None,
    ):
        self.candidate_calls.append(
            (agent_key, candidate_content, candidate_hash, payload, assembly_context)
        )
        return super().run_candidate(
            agent_key,
            candidate_content,
            candidate_hash,
            payload,
            assembly_context,
            observation=observation,
        )

    def run(self, agent_key, graph_release_id, payload, assembly_context):
        self.run_calls.append((agent_key, graph_release_id, payload, assembly_context))
        return super().run(agent_key, graph_release_id, payload, assembly_context)

    def run_published_baseline(
        self, agent_key, graph_release_id, payload, assembly_context, *, observation=None
    ):
        self.baseline_calls.append((agent_key, graph_release_id, payload, assembly_context))
        return super().run_published_baseline(
            agent_key, graph_release_id, payload, assembly_context, observation=observation
        )


def _runtime(factory: sessionmaker, adapter) -> _SpyRuntime:
    return _SpyRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=adapter,
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )


def _executor(factory: sessionmaker, adapter=None, **kwargs):
    adapter = adapter if adapter is not None else DeterministicFakeModelAdapter()
    runtime = _runtime(factory, adapter)
    return AgentTestWorkbench(runtime=runtime, **kwargs), runtime, adapter


def _lock_version(factory: sessionmaker) -> int:
    with factory() as session:
        return session.scalar(select(GraphDraft.lock_version))


def _run_candidate(factory, workbench, agent_key="architect", test_case_id=None, **kwargs):
    arguments = {
        "agent_key": agent_key,
        "test_case_id": test_case_id
        if test_case_id is not None
        else _seed_case_id(factory, agent_key),
        "expected_lock_version": _lock_version(factory),
        "actor": RUNNER,
    }
    arguments.update(kwargs)
    with factory() as session:
        return workbench.execute_candidate_run(session, **arguments)


def _run_baseline(factory, workbench, agent_key="architect", test_case_id=None, **kwargs):
    arguments = {
        "agent_key": agent_key,
        "test_case_id": test_case_id
        if test_case_id is not None
        else _seed_case_id(factory, agent_key),
        "actor": RUNNER,
    }
    arguments.update(kwargs)
    with factory() as session:
        return workbench.execute_baseline_rerun(session, **arguments)


def _run_rows(factory: sessionmaker) -> list[AgentTestRun]:
    with factory() as session:
        return list(session.scalars(select(AgentTestRun).order_by(AgentTestRun.id)))


def _identity(factory: sessionmaker, agent_key: str = "architect") -> dict[str, object]:
    """The real identity a run must record, read straight from the tables."""
    with factory() as session:
        release_id = session.scalar(
            select(GraphRelease.id).where(GraphRelease.effective_to.is_(None))
        )
        revision_id = session.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.graph_release_id == release_id,
                GraphReleaseAgent.agent_key == agent_key,
            )
        )
        draft_row = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        from src.database.models.graph_configuration import AgentDefinitionRevision

        revision_hash = session.scalar(
            select(AgentDefinitionRevision.content_hash).where(
                AgentDefinitionRevision.id == revision_id
            )
        )
        return {
            "release_id": release_id,
            "revision_id": revision_id,
            "revision_hash": revision_hash,
            "draft_hash": draft_row.candidate_hash,
            "draft_content": definition_content_from_row(draft_row),
        }


def _rewrite_draft(factory: sessionmaker, agent_key: str, **content_update) -> str:
    """Store a changed draft candidate directly, with its matching hash."""
    with factory() as session:
        row = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        content = definition_content_from_row(row).model_copy(update=content_update)
        for column, value in definition_content_values(content).items():
            setattr(row, column, value)
        row.candidate_hash = definition_content_hash(content)
        session.commit()
        return row.candidate_hash


def _saver(prompt_text: str):
    def _save(factory: sessionmaker, agent_key: str = "architect") -> None:
        content = _identity(factory, agent_key)["draft_content"]
        with factory() as session:
            outcome = GraphConfiguration().save_editable_model_draft(
                session,
                agent_key=agent_key,
                expected_lock_version=_lock_version(factory),
                candidate=EditableModelDraft(
                    prompt_text=prompt_text,
                    endpoint_name=content.model.endpoint_name,
                    temperature=float(content.model.temperature),
                    max_tokens=content.model.max_tokens,
                    top_p=float(content.model.top_p),
                ),
                actor="saver@example.com",
            )
        assert not isinstance(outcome, DraftSaveConflict)

    return _save


# --- the call, and the completed evidence ----------------------------------


def test_a_candidate_run_hands_run_candidate_the_saved_draft_content_and_hash(factory):
    workbench, runtime, _adapter = _executor(factory)
    identity = _identity(factory)

    _run_candidate(factory, workbench)

    assert len(runtime.candidate_calls) == 1
    agent_key, content, candidate_hash, payload, context = runtime.candidate_calls[0]
    assert agent_key == "architect"
    assert content == identity["draft_content"]
    assert candidate_hash == identity["draft_hash"]
    assert payload == model_payload_for("architect", REQUIRED_SMOKE_PAYLOADS["architect"])
    assert (context.design_system_active, context.root_session_id, context.actor_session_id) == (
        False,
        "",
        "",
    )
    assert runtime.run_calls == []


def test_a_completed_candidate_run_returns_exact_evidence(factory):
    workbench, _runtime_, adapter = _executor(factory)
    identity = _identity(factory)
    case_id = _seed_case_id(factory)

    evidence = _run_candidate(factory, workbench)

    assert isinstance(evidence, TestRunEvidence)
    assert evidence.run_kind == "candidate"
    assert evidence.execution_status == "completed"
    assert evidence.error_detail is None
    assert evidence.deterministic_checks_passed is True
    assert evidence.deterministic_check_results == (_PASSED_CONTRACT,)
    assert (evidence.test_case_id, evidence.test_case_version) == (case_id, 1)
    assert evidence.agent_key == "architect"
    assert evidence.candidate_hash == identity["draft_hash"]
    assert evidence.compared_release_id == identity["release_id"]
    assert evidence.compared_definition_revision_id == identity["revision_id"]
    assert evidence.synthetic_payload == REQUIRED_SMOKE_PAYLOADS["architect"]
    assert evidence.model_payload == model_payload_for(
        "architect", REQUIRED_SMOKE_PAYLOADS["architect"]
    )
    assert evidence.assembled_prompt == adapter.calls[0].prompt
    assert evidence.candidate_raw_output == fake_output("architect")
    assert evidence.candidate_structured_output["intent"] == "discuss"
    assert evidence.candidate_structured_output["message"] == "an answer"
    assert (evidence.baseline_raw_output, evidence.baseline_structured_output) == (None, None)
    assert isinstance(evidence.latency_ms, float) and evidence.latency_ms > 0
    assert (evidence.input_tokens, evidence.output_tokens) == (None, None)
    assert evidence.run_by == RUNNER
    assert evidence.run_at is not None
    assert (evidence.candidate_is_current, evidence.base_release_is_current) == (True, True)


def test_a_completed_run_persists_one_row_with_null_verdict_columns(factory):
    workbench, _runtime_, _adapter = _executor(factory)
    identity = _identity(factory)

    evidence = _run_candidate(factory, workbench)

    rows = _run_rows(factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == evidence.run_id
    assert (
        row.agent_key,
        row.run_kind,
        row.candidate_hash,
        row.test_case_id,
        row.test_case_version,
        row.compared_release_id,
        row.compared_definition_revision_id,
        row.execution_status,
        row.deterministic_checks_passed,
        row.run_by,
    ) == (
        "architect",
        "candidate",
        identity["draft_hash"],
        _seed_case_id(factory),
        1,
        identity["release_id"],
        identity["revision_id"],
        "completed",
        True,
        RUNNER,
    )
    assert row.deterministic_check_results == [
        {"name": "output_contract", "passed": True, "message": None, "issues": []}
    ]
    assert row.model_payload == evidence.model_payload
    assert row.assembled_prompt == evidence.assembled_prompt
    assert row.candidate_raw_output == evidence.candidate_raw_output
    assert row.candidate_structured_output == evidence.candidate_structured_output
    assert row.latency_ms == evidence.latency_ms
    assert (row.verdict, row.verdict_reviewer, row.verdict_at, row.verdict_notes) == (
        None,
        None,
        None,
        None,
    )


def test_no_candidate_sentinel_reaches_the_evidence_or_its_row(factory):
    """M-1: identity comes from the transaction-1 snapshot, never ``-1``."""
    workbench, _runtime_, _adapter = _executor(factory)

    evidence = _run_candidate(factory, workbench)

    assert evidence.compared_release_id > 0
    assert evidence.compared_definition_revision_id > 0
    for name, value in dataclasses_asdict(evidence).items():
        assert value != -1, name
    row = _run_rows(factory)[0]
    for column in AgentTestRun.__table__.columns:
        assert getattr(row, column.key) != -1, column.key


def dataclasses_asdict(value) -> dict[str, object]:
    import dataclasses

    return {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}


# --- the status map (C16/C33), checks (C17), raw output (C15) ---------------


@pytest.mark.parametrize(
    ("mode", "detail"),
    [
        ("provider_unavailable", "endpoint_unavailable:{endpoint}"),
        ("structured_output_unsupported", "structured_output_unsupported:{endpoint}"),
    ],
)
def test_a_model_failure_is_a_persisted_model_error_with_a_code_only(factory, mode, detail):
    workbench, _runtime_, adapter = _executor(
        factory, DeterministicFakeModelAdapter(mode=mode)
    )
    endpoint = _identity(factory)["draft_content"].model.endpoint_name

    evidence = _run_candidate(factory, workbench)

    assert evidence.execution_status == "model_error"
    assert evidence.error_detail == detail.format(endpoint=endpoint)
    assert evidence.deterministic_checks_passed is False
    assert evidence.deterministic_check_results == (
        DeterministicCheckResult(
            name="execution",
            passed=False,
            message="The run produced no model output to check.",
            issues=(),
        ),
    )
    assert (evidence.candidate_raw_output, evidence.candidate_structured_output) == (None, None)
    # The prompt was assembled and sent, so the Input view still has it.
    assert evidence.assembled_prompt == adapter.calls[0].prompt
    assert len(_run_rows(factory)) == 1


def test_an_unexpected_failure_persists_its_class_name_and_never_its_text(factory):
    secret = "provider echoed SECRET-PROMPT-TEXT"
    workbench, _runtime_, _adapter = _executor(
        factory, _HookedFakeAdapter(raise_error=KeyError(secret))
    )

    evidence = _run_candidate(factory, workbench)

    assert evidence.execution_status == "model_error"
    assert evidence.error_detail == "unexpected_error:KeyError"
    row = _run_rows(factory)[0]
    stored = json.dumps(
        {column.key: str(getattr(row, column.key)) for column in AgentTestRun.__table__.columns}
    )
    assert "SECRET-PROMPT-TEXT" not in stored
    assert "SECRET-PROMPT-TEXT" not in json.dumps(dataclasses_asdict(evidence), default=str)


def test_an_undeclared_output_field_is_incomplete_with_its_raw_keys_and_issue(factory):
    workbench, _runtime_, _adapter = _executor(
        factory, DeterministicFakeModelAdapter(mode="invalid_optional_field")
    )

    evidence = _run_candidate(factory, workbench)

    assert evidence.execution_status == "incomplete"
    assert evidence.error_detail == "invalid_output:AgentOutputValidationError"
    assert evidence.candidate_structured_output is None
    assert evidence.candidate_raw_output == fake_output(
        "architect", diagnostic_notes=["  "]
    )
    assert evidence.deterministic_checks_passed is False
    assert evidence.deterministic_check_results == (
        DeterministicCheckResult(
            name="output_contract",
            passed=False,
            message="The model output does not satisfy the output contract.",
            issues=(
                DeterministicCheckIssue(
                    code="output_undeclared_top_level_field", field="diagnostic_notes"
                ),
            ),
        ),
    )
    row = _run_rows(factory)[0]
    assert row.deterministic_check_results == [
        {
            "name": "output_contract",
            "passed": False,
            "message": "The model output does not satisfy the output contract.",
            "issues": [
                {"code": "output_undeclared_top_level_field", "field": "diagnostic_notes"}
            ],
        }
    ]
    assert row.candidate_structured_output is None


def test_a_provider_parse_failure_is_incomplete_without_raw_output(factory):
    workbench, _runtime_, _adapter = _executor(
        factory, DeterministicFakeModelAdapter(mode="provider_parse_error")
    )

    evidence = _run_candidate(factory, workbench)

    assert evidence.execution_status == "incomplete"
    assert evidence.error_detail == "invalid_output:ValidationError"
    assert evidence.candidate_raw_output is None
    assert evidence.deterministic_check_results == (
        DeterministicCheckResult(
            name="output_contract",
            passed=False,
            message="The model output does not satisfy the output contract.",
            issues=(),
        ),
    )


class _NotedAdapter(DeterministicFakeModelAdapter):
    """Answer with the role's output plus one valid diagnostic note."""

    def invoke(self, *, agent_key, configuration, schema, prompt):
        super().invoke(
            agent_key=agent_key, configuration=configuration, schema=schema, prompt=prompt
        )
        return schema.model_validate(fake_output(agent_key, diagnostic_notes=["a note"]))


def test_a_v2_overlay_candidates_structured_output_keeps_its_optional_fields(factory):
    """C15: structured output is the canonical dump merged with the validated
    optional fields the overlay declared."""
    from src.services.agent_schema_registry import AgentSchemaRegistry
    from src.services.agent_schema_types import SchemaOverlay

    _rewrite_draft(
        factory,
        "architect",
        schema_contract=ContentIdentity(
            version=2, digest=AgentSchemaRegistry().identity_for("architect", 2).digest
        ),
        schema_overlay=SchemaOverlay(
            field_overrides={}, additional_optional_fields=("diagnostic_notes",)
        ),
    )
    workbench, _runtime_, _adapter = _executor(factory, _NotedAdapter())

    evidence = _run_candidate(factory, workbench)

    assert evidence.execution_status == "completed", evidence.error_detail
    assert evidence.candidate_structured_output["diagnostic_notes"] == ["a note"]
    assert evidence.candidate_raw_output["diagnostic_notes"] == ["a note"]


def test_an_unassemblable_candidate_is_an_assembly_error_before_the_model(factory):
    _rewrite_draft(
        factory,
        "architect",
        protected_assembly=ContentIdentity(version=999, digest="0" * 64),
    )
    workbench, _runtime_, adapter = _executor(factory)

    evidence = _run_candidate(factory, workbench)

    assert evidence.execution_status == "assembly_error"
    assert evidence.error_detail == "protected_bundle_unavailable"
    assert evidence.assembled_prompt is None
    assert evidence.latency_ms is None
    assert adapter.calls == []
    assert evidence.deterministic_check_results[0].name == "execution"
    assert len(_run_rows(factory)) == 1


# --- C8: no transaction across the model call -------------------------------


def test_the_model_is_called_with_no_open_transaction(factory):
    observed: list[bool] = []
    holder: dict[str, object] = {}

    def _check() -> None:
        observed.append(holder["session"].in_transaction())

    workbench, _runtime_, _adapter = _executor(factory, _HookedFakeAdapter(on_invoke=_check))
    with factory() as session:
        holder["session"] = session
        workbench.execute_candidate_run(
            session,
            agent_key="architect",
            test_case_id=_seed_case_id(factory),
            expected_lock_version=_lock_version(factory),
            actor=RUNNER,
        )

    assert observed == [False]


def test_the_baseline_model_is_called_with_no_open_transaction(factory):
    observed: list[bool] = []
    holder: dict[str, object] = {}

    def _check() -> None:
        observed.append(holder["session"].in_transaction())

    workbench, _runtime_, _adapter = _executor(factory, _HookedFakeAdapter(on_invoke=_check))
    with factory() as session:
        holder["session"] = session
        workbench.execute_baseline_rerun(
            session,
            agent_key="architect",
            test_case_id=_seed_case_id(factory),
            actor=RUNNER,
        )

    assert observed == [False]


@pytest.mark.parametrize("method", ["candidate", "baseline"])
def test_an_executor_refuses_a_session_already_in_a_transaction(factory, method):
    workbench, _runtime_, adapter = _executor(factory)
    case_id = _seed_case_id(factory)
    with factory() as session:
        session.execute(select(1))
        assert session.in_transaction()
        with pytest.raises(RuntimeError):
            if method == "candidate":
                workbench.execute_candidate_run(
                    session,
                    agent_key="architect",
                    test_case_id=case_id,
                    expected_lock_version=0,
                    actor=RUNNER,
                )
            else:
                workbench.execute_baseline_rerun(
                    session, agent_key="architect", test_case_id=case_id, actor=RUNNER
                )
    assert adapter.calls == []
    assert _run_rows(factory) == []


def test_a_draft_saved_during_the_call_is_recorded_as_not_current(factory):
    """C8.5: the run records exactly what ran, and says the draft moved on."""
    before = _identity(factory)["draft_hash"]
    save = _saver("changed while the model was running")
    workbench, _runtime_, _adapter = _executor(
        factory, _HookedFakeAdapter(on_invoke=lambda: save(factory))
    )

    evidence = _run_candidate(factory, workbench)

    assert _identity(factory)["draft_hash"] != before
    assert evidence.candidate_hash == before
    assert (evidence.candidate_is_current, evidence.base_release_is_current) == (False, True)
    assert _run_rows(factory)[0].candidate_hash == before


def test_a_case_retired_during_the_call_is_recorded_as_not_current(factory):
    extra = _create(factory, name="architect_retired_mid_run")
    workbench, _runtime_, _adapter = _executor(
        factory, _HookedFakeAdapter(on_invoke=lambda: _deactivate(factory, extra.id))
    )

    evidence = _run_candidate(factory, workbench, test_case_id=extra.id)

    assert evidence.execution_status == "completed"
    assert (evidence.candidate_is_current, evidence.base_release_is_current) == (False, True)
    assert _run_rows(factory)[0].test_case_id == extra.id


def _publish_same_content(factory: sessionmaker) -> int:
    """Stand in for #269's publication on SQLite: close v1, open v2, rebase."""
    with factory() as session:
        v1 = session.scalar(select(GraphRelease).where(GraphRelease.effective_to.is_(None)))
        from datetime import timedelta

        now = v1.effective_from + timedelta(minutes=1)
        v1.effective_to = now
        session.flush()
        v2 = GraphRelease(
            version_number=v1.version_number + 1,
            previous_release_id=v1.id,
            release_note="published during a test run",
            published_by="publisher@example.com",
            published_at=now,
            effective_from=now,
            effective_to=None,
        )
        session.add(v2)
        session.flush()
        for mapping in session.scalars(
            select(GraphReleaseAgent).where(GraphReleaseAgent.graph_release_id == v1.id)
        ).all():
            session.add(
                GraphReleaseAgent(
                    graph_release_id=v2.id,
                    agent_key=mapping.agent_key,
                    agent_definition_revision_id=mapping.agent_definition_revision_id,
                )
            )
        session.execute(update(GraphDraft).values(base_release_id=v2.id))
        session.commit()
        return v2.id


def test_a_publication_during_the_call_keeps_the_run_on_its_base_release(factory):
    """C8.5 publication-first: the run records v1 and says the base moved."""
    v1 = _identity(factory)["release_id"]
    published: list[int] = []
    workbench, _runtime_, _adapter = _executor(
        factory,
        _HookedFakeAdapter(on_invoke=lambda: published.append(_publish_same_content(factory))),
    )

    evidence = _run_candidate(factory, workbench)

    assert published and published[0] != v1
    assert evidence.compared_release_id == v1
    assert evidence.base_release_is_current is False
    assert _run_rows(factory)[0].compared_release_id == v1


# --- C8.6: the one retry, and 503 with no run ---------------------------------


class _FlakyParents(GraphConfiguration):
    """``_lock_current_parents`` raises the handoff diagnosis ``failures`` times
    once armed (the executor arms it after the model call)."""

    def __init__(self, failures: int, message: str) -> None:
        super().__init__()
        self.failures = failures
        self.message = message
        self.armed = False
        self.raised = 0

    def _lock_current_parents(self, session, *, exclusive):
        if self.armed and self.raised < self.failures:
            self.raised += 1
            raise GraphConfigurationIntegrityError(self.message)
        return super()._lock_current_parents(session, exclusive=exclusive)


_HANDOFF = "graph configuration parent snapshot is inconsistent"


def test_a_handoff_race_in_transaction_two_is_retried_once(factory):
    parents = _FlakyParents(1, _HANDOFF)
    adapter = _HookedFakeAdapter(on_invoke=lambda: setattr(parents, "armed", True))
    workbench, _runtime_, _adapter = _executor(factory, adapter, graph_configuration=parents)

    evidence = _run_candidate(factory, workbench)

    assert parents.raised == 1
    assert evidence.execution_status == "completed"
    assert len(adapter.calls) == 1
    assert len(_run_rows(factory)) == 1


@pytest.mark.parametrize(
    ("failures", "message"),
    [(2, _HANDOFF), (1, "graph configuration must have exactly one active release")],
)
def test_a_second_handoff_race_or_another_integrity_failure_is_unavailable(
    factory, failures, message
):
    parents = _FlakyParents(failures, message)
    adapter = _HookedFakeAdapter(on_invoke=lambda: setattr(parents, "armed", True))
    workbench, _runtime_, _adapter = _executor(factory, adapter, graph_configuration=parents)

    with pytest.raises(TestRunUnavailable):
        _run_candidate(factory, workbench)

    assert len(adapter.calls) == 1, "the model must never be re-invoked"
    assert _run_rows(factory) == []


class _UnavailableReads(GraphConfiguration):
    def read_workbench(self, session):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_a_database_failure_before_the_call_is_unavailable_with_no_call(factory):
    workbench, _runtime_, adapter = _executor(
        factory, graph_configuration=_UnavailableReads()
    )

    with pytest.raises(TestRunUnavailable):
        _run_candidate(factory, workbench)

    assert adapter.calls == []
    assert _run_rows(factory) == []


def test_a_database_failure_at_the_insert_is_unavailable_with_no_row(factory, monkeypatch):
    from sqlalchemy.orm import Session as OrmSession

    workbench, _runtime_, adapter = _executor(factory)
    original_flush = OrmSession.flush

    def _failing_flush(self, *args, **kwargs):
        if any(isinstance(obj, AgentTestRun) for obj in self.new):
            raise OperationalError("INSERT", {}, Exception("connection reset"))
        return original_flush(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "flush", _failing_flush)

    with pytest.raises(TestRunUnavailable):
        _run_candidate(factory, workbench)

    monkeypatch.undo()
    assert len(adapter.calls) == 1
    assert _run_rows(factory) == []


# --- C32: the lock pin and the saved endpoint policy ------------------------


def test_a_stale_lock_is_the_null_candidate_conflict_with_no_call_and_no_row(factory):
    workbench, _runtime_, adapter = _executor(factory)
    _saver("moved the lock on")(factory)

    outcome = _run_candidate(factory, workbench, expected_lock_version=0)

    assert isinstance(outcome, DraftSaveConflict)
    assert (outcome.expected_lock_version, outcome.current_lock_version) == (0, 1)
    assert outcome.client_candidate is None
    assert adapter.calls == []
    assert _run_rows(factory) == []


def test_a_url_shaped_stored_endpoint_is_refused_before_any_call(factory):
    content = _identity(factory)["draft_content"]
    _rewrite_draft(
        factory,
        "architect",
        model=content.model.model_copy(update={"endpoint_name": "https://example.com/x"}),
    )
    workbench, _runtime_, adapter = _executor(factory)

    with pytest.raises(DraftContentRejected) as caught:
        _run_candidate(factory, workbench)

    assert [issue.field for issue in caught.value.issues] == ["candidate.model.endpoint_name"]
    assert adapter.calls == []
    assert _run_rows(factory) == []


def _rewrite_published(factory: sessionmaker, agent_key: str, endpoint_name: str) -> None:
    """Store a URL-shaped endpoint on the active revision (SQLite has no guard)."""
    from src.database.models.graph_configuration import AgentDefinitionRevision

    with factory() as session:
        revision_id = session.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id)
            .join(GraphRelease, GraphRelease.id == GraphReleaseAgent.graph_release_id)
            .where(
                GraphRelease.effective_to.is_(None),
                GraphReleaseAgent.agent_key == agent_key,
            )
        )
        row = session.get(AgentDefinitionRevision, revision_id)
        content = definition_content_from_row(row)
        content = content.model_copy(
            update={"model": content.model.model_copy(update={"endpoint_name": endpoint_name})}
        )
        for column, value in definition_content_values(content).items():
            setattr(row, column, value)
        row.content_hash = definition_content_hash(content)
        session.commit()


def test_a_url_shaped_published_endpoint_is_refused_before_a_baseline_call(factory):
    """I-2: the baseline twin of the candidate path's stored-name refusal."""
    url = "https://example.com/serving-endpoints/x"
    _rewrite_published(factory, "architect", url)
    workbench, runtime, adapter = _executor(factory)

    with pytest.raises(DraftContentRejected) as caught:
        _run_baseline(factory, workbench)

    assert [(issue.field, issue.code) for issue in caught.value.issues] == [
        ("published.model.endpoint_name", "endpoint_url_not_allowed")
    ]
    assert url not in str(caught.value)
    assert all(url not in issue.message for issue in caught.value.issues)
    assert adapter.calls == []
    assert runtime.baseline_calls == []
    assert _run_rows(factory) == []


@pytest.mark.parametrize("case_state", ["missing", "other_role", "inactive"])
def test_a_baseline_refuses_the_published_endpoint_before_the_case(factory, case_state):
    """Fix round 1 (I-1): endpoint 422 precedes case 404 / 422 / 409, as for a candidate."""
    _rewrite_published(factory, "architect", "https://example.com/serving-endpoints/x")
    workbench, runtime, adapter = _executor(factory)
    if case_state == "missing":
        test_case_id = 424242
    elif case_state == "other_role":
        test_case_id = _seed_case_id(factory, "builder")
    else:
        test_case_id = _seed_case_id(factory)
        _update(factory, test_case_id)

    with pytest.raises(DraftContentRejected) as caught:
        _run_baseline(factory, workbench, test_case_id=test_case_id)

    assert [(issue.field, issue.code) for issue in caught.value.issues] == [
        ("published.model.endpoint_name", "endpoint_url_not_allowed")
    ]
    assert adapter.calls == []
    assert runtime.baseline_calls == []
    assert _run_rows(factory) == []


# --- the case: found, same role, active (C22) -------------------------------


def test_an_unknown_case_is_not_found_with_no_call(factory):
    workbench, _runtime_, adapter = _executor(factory)

    with pytest.raises(TestCaseNotFound):
        _run_candidate(factory, workbench, test_case_id=987654)
    with pytest.raises(TestCaseNotFound):
        _run_baseline(factory, workbench, test_case_id=987654)

    assert adapter.calls == []
    assert _run_rows(factory) == []


def test_a_case_of_another_role_is_refused_with_no_call(factory):
    workbench, _runtime_, adapter = _executor(factory)
    builder_case = _seed_case_id(factory, "builder")

    with pytest.raises(TestRunCaseRoleMismatch):
        _run_candidate(factory, workbench, agent_key="architect", test_case_id=builder_case)
    with pytest.raises(TestRunCaseRoleMismatch):
        _run_baseline(factory, workbench, agent_key="architect", test_case_id=builder_case)

    assert adapter.calls == []
    assert _run_rows(factory) == []


def test_an_inactive_case_version_is_refused_with_no_call(factory):
    seed = _seed_case_id(factory)
    _update(factory, seed)  # supersede: the seed row is now inactive
    workbench, _runtime_, adapter = _executor(factory)

    with pytest.raises(TestRunCaseInactive):
        _run_candidate(factory, workbench, test_case_id=seed)
    with pytest.raises(TestRunCaseInactive):
        _run_baseline(factory, workbench, test_case_id=seed)

    assert adapter.calls == []
    assert _run_rows(factory) == []


@pytest.mark.parametrize("actor", ["", "   ", None])
def test_a_run_requires_a_nonblank_actor(factory, actor):
    workbench, _runtime_, adapter = _executor(factory)

    with pytest.raises(TestCaseRejected):
        _run_candidate(factory, workbench, actor=actor)
    with pytest.raises(TestCaseRejected):
        _run_baseline(factory, workbench, actor=actor)

    assert adapter.calls == []


def test_a_baseline_for_an_unknown_role_is_refused(factory):
    workbench, _runtime_, adapter = _executor(factory)

    with pytest.raises(TestCaseRejected):
        _run_baseline(factory, workbench, agent_key="foreman")

    assert adapter.calls == []


# --- C20: the published baseline -------------------------------------------


def test_a_baseline_rerun_goes_through_the_published_entry_on_the_active_release(factory):
    workbench, runtime, adapter = _executor(factory)
    identity = _identity(factory)

    evidence = _run_baseline(factory, workbench)

    assert runtime.candidate_calls == []
    assert len(runtime.baseline_calls) == 1
    agent_key, release_id, payload, context = runtime.baseline_calls[0]
    assert (agent_key, release_id) == ("architect", identity["release_id"])
    assert payload == model_payload_for("architect", REQUIRED_SMOKE_PAYLOADS["architect"])
    assert (context.root_session_id, context.actor_session_id) == ("", "")
    assert evidence.run_kind == "published_baseline"
    assert evidence.execution_status == "completed"
    assert evidence.candidate_hash == identity["revision_hash"]
    assert evidence.compared_release_id == identity["release_id"]
    assert evidence.compared_definition_revision_id == identity["revision_id"]
    assert (evidence.baseline_raw_output, evidence.baseline_structured_output) == (None, None)
    assert evidence.candidate_raw_output == fake_output("architect")
    assert evidence.assembled_prompt == adapter.calls[0].prompt
    row = _run_rows(factory)[0]
    assert (row.run_kind, row.compared_release_id, row.candidate_hash) == (
        "published_baseline",
        identity["release_id"],
        identity["revision_hash"],
    )


def test_a_baseline_rerun_records_the_published_revision_not_the_edited_draft(factory):
    """C19/C20: a baseline's candidate_hash is its revision's hash, whatever the draft."""
    _saver("an edited draft the baseline must ignore")(factory)
    identity = _identity(factory)
    assert identity["draft_hash"] != identity["revision_hash"]
    workbench, _runtime_, adapter = _executor(factory)

    evidence = _run_baseline(factory, workbench)

    assert evidence.candidate_hash == identity["revision_hash"]
    assert "an edited draft the baseline must ignore" not in adapter.calls[0].prompt
    assert (evidence.candidate_is_current, evidence.base_release_is_current) == (True, True)


def test_a_failed_baseline_rerun_is_persisted_with_the_same_status_map(factory):
    workbench, _runtime_, _adapter = _executor(
        factory, DeterministicFakeModelAdapter(mode="provider_unavailable")
    )
    endpoint = _identity(factory)["draft_content"].model.endpoint_name

    evidence = _run_baseline(factory, workbench)

    assert evidence.execution_status == "model_error"
    assert evidence.error_detail == f"endpoint_unavailable:{endpoint}"
    assert _run_rows(factory)[0].run_kind == "published_baseline"


def test_no_baseline_is_shown_before_one_is_run(factory):
    workbench, _runtime_, _adapter = _executor(factory)

    first = _run_candidate(factory, workbench)
    second = _run_candidate(factory, workbench)

    # A candidate run is never anyone's baseline, including its own successor's.
    assert (second.baseline_raw_output, second.baseline_structured_output) == (None, None)
    assert first.run_id != second.run_id


class _NumberedAdapter(DeterministicFakeModelAdapter):
    """Answer the architect with a message numbered by call, so runs differ."""

    def invoke(self, *, agent_key, configuration, schema, prompt):
        super().invoke(
            agent_key=agent_key, configuration=configuration, schema=schema, prompt=prompt
        )
        return schema.model_validate(
            fake_output(agent_key, message=f"answer {len(self.calls)}")
        )


def test_a_candidate_run_copies_the_newest_completed_baseline_outputs(factory):
    workbench, _runtime_, _adapter = _executor(factory, _NumberedAdapter())
    oldest = _run_baseline(factory, workbench)
    newest = _run_baseline(factory, workbench)
    assert oldest.candidate_structured_output != newest.candidate_structured_output

    evidence = _run_candidate(factory, workbench)

    assert evidence.baseline_raw_output == newest.candidate_raw_output
    assert evidence.baseline_structured_output == newest.candidate_structured_output
    row = next(row for row in _run_rows(factory) if row.id == evidence.run_id)
    assert row.baseline_raw_output == newest.candidate_raw_output
    assert row.baseline_structured_output == newest.candidate_structured_output


def test_a_failed_baseline_is_never_the_stored_baseline(factory):
    good, _r, _a = _executor(factory)
    completed = _run_baseline(factory, good)
    failing, _r2, _a2 = _executor(
        factory, DeterministicFakeModelAdapter(mode="provider_unavailable")
    )
    _run_baseline(factory, failing)

    evidence = _run_candidate(factory, good)

    assert evidence.baseline_structured_output == completed.candidate_structured_output


def test_a_baseline_for_another_case_version_is_not_this_cases_baseline(factory):
    workbench, _runtime_, _adapter = _executor(factory)
    seed = _seed_case_id(factory)
    _run_baseline(factory, workbench, test_case_id=seed)
    successor = _update(factory, seed)

    evidence = _run_candidate(factory, workbench, test_case_id=successor.id)

    assert (evidence.baseline_raw_output, evidence.baseline_structured_output) == (None, None)


def test_a_baseline_for_another_revision_is_not_this_candidates_baseline(factory):
    workbench, _runtime_, _adapter = _executor(factory)
    _run_baseline(factory, workbench)
    # Re-point the stored baseline at another revision of the same role.
    with factory() as session:
        other_revision = session.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.agent_key == "architect"
            )
        )
        from src.database.models.graph_configuration import AgentDefinitionRevision

        clone = session.get(AgentDefinitionRevision, other_revision)
        copy = AgentDefinitionRevision(
            **{
                column.key: getattr(clone, column.key)
                for column in AgentDefinitionRevision.__table__.columns
                if column.key not in {"id", "created_at"}
            }
        )
        copy.content_hash = "f" * 64
        session.add(copy)
        session.flush()
        session.execute(
            update(AgentTestRun)
            .where(AgentTestRun.run_kind == "published_baseline")
            .values(compared_definition_revision_id=copy.id)
        )
        session.commit()

    evidence = _run_candidate(factory, workbench)

    assert (evidence.baseline_raw_output, evidence.baseline_structured_output) == (None, None)


# --- C10/C37: what every role's model sees ----------------------------------


def _prompt_payload_object(prompt: str, expected_keys: set[str]) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(prompt):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(prompt, index)
        except ValueError:
            continue
        if isinstance(value, dict) and set(value) == expected_keys:
            return value
    raise AssertionError(f"no payload object with keys {sorted(expected_keys)} in the prompt")


@pytest.mark.parametrize("role", MODEL_DRIVEN_AGENT_KEYS)
def test_every_role_model_sees_exactly_the_projected_seed_keys(factory, role):
    workbench, _runtime_, adapter = _executor(factory)
    seed = REQUIRED_SMOKE_PAYLOADS[role]
    expected = set(seed) & set(MODEL_PAYLOAD_KEYS[role])

    evidence = _run_candidate(factory, workbench, agent_key=role)

    assert evidence.execution_status == "completed", evidence.error_detail
    assert set(evidence.model_payload) == expected
    prompt = adapter.calls[0].prompt
    assert _prompt_payload_object(prompt, expected) == evidence.model_payload
    for identifier in _SEEDED_IDENTIFIERS:
        assert identifier not in prompt, (role, identifier)


@pytest.mark.parametrize("role", MODEL_DRIVEN_AGENT_KEYS)
def test_every_role_baseline_model_sees_exactly_the_projected_seed_keys(factory, role):
    workbench, _runtime_, adapter = _executor(factory)
    expected = set(REQUIRED_SMOKE_PAYLOADS[role]) & set(MODEL_PAYLOAD_KEYS[role])

    evidence = _run_baseline(factory, workbench, agent_key=role)

    assert evidence.execution_status == "completed", evidence.error_detail
    prompt = adapter.calls[0].prompt
    assert _prompt_payload_object(prompt, expected) == evidence.model_payload
    for identifier in _SEEDED_IDENTIFIERS:
        assert identifier not in prompt, (role, identifier)


def test_the_builder_prompt_carries_no_seeded_session_identifier(factory):
    workbench, _runtime_, adapter = _executor(factory)

    _run_candidate(factory, workbench, agent_key="builder")

    prompt = adapter.calls[0].prompt
    assert "synthetic-builder" not in prompt
    assert "synthetic-turn" not in prompt
    assert "system:bootstrap" not in prompt
    assert "design_system_id" not in prompt


# --- logging ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["success", "invalid_optional_field", "provider_unavailable"])
def test_the_executor_logs_no_payload_prompt_or_output(factory, caplog, mode):
    workbench, _runtime_, adapter = _executor(factory, DeterministicFakeModelAdapter(mode=mode))
    caplog.set_level(logging.DEBUG)

    _run_candidate(factory, workbench)
    _run_baseline(factory, workbench)

    forbidden = [
        "Create a three-slide demo roadmap",
        "Synthetic demo style",
        "an answer",
        adapter.calls[0].prompt[:200],
    ]
    for record in caplog.records:
        text = record.getMessage() + json.dumps(
            {key: str(value) for key, value in vars(record).items()}
        )
        for value in forbidden:
            assert value not in text, (record.name, record.getMessage())


# --- reads ------------------------------------------------------------------


def test_get_test_run_returns_the_persisted_evidence(factory):
    workbench, _runtime_, _adapter = _executor(factory)
    evidence = _run_candidate(factory, workbench)

    with factory() as session:
        read = workbench.get_test_run(session, run_id=evidence.run_id)

    expected = dataclasses_asdict(evidence)
    expected.update(candidate_is_current=None, base_release_is_current=None)
    assert dataclasses_asdict(read) == expected


def test_get_test_run_of_an_unknown_id_is_not_found(factory):
    workbench, _runtime_, _adapter = _executor(factory)

    with factory() as session, pytest.raises(TestRunNotFound):
        workbench.get_test_run(session, run_id=424242)


def test_list_test_runs_returns_a_cases_runs_newest_first_and_bounded(factory):
    workbench, _runtime_, _adapter = _executor(factory)
    first = _run_candidate(factory, workbench)
    second = _run_baseline(factory, workbench)
    third = _run_candidate(factory, workbench)
    _run_candidate(factory, workbench, agent_key="builder")

    with factory() as session:
        runs = workbench.list_test_runs(session, test_case_id=_seed_case_id(factory))
        limited = workbench.list_test_runs(
            session, test_case_id=_seed_case_id(factory), limit=2
        )

    assert [run.run_id for run in runs] == [third.run_id, second.run_id, first.run_id]
    assert [run.run_id for run in limited] == [third.run_id, second.run_id]


def test_list_test_runs_of_an_unknown_case_is_not_found(factory):
    """Catches an unknown case listing as an empty history (Task 5's 404)."""
    workbench, _runtime_, _adapter = _executor(factory)

    with factory() as session, pytest.raises(TestCaseNotFound):
        workbench.list_test_runs(session, test_case_id=424242)


def test_list_test_runs_of_a_case_with_no_runs_is_empty(factory):
    workbench, _runtime_, _adapter = _executor(factory)

    with factory() as session:
        assert workbench.list_test_runs(session, test_case_id=_seed_case_id(factory)) == []


@pytest.mark.parametrize("limit", [0, -1, 101, True])
def test_list_test_runs_rejects_an_out_of_range_limit(factory, limit):
    workbench, _runtime_, _adapter = _executor(factory)

    with factory() as session, pytest.raises(ValueError):
        workbench.list_test_runs(session, test_case_id=1, limit=limit)


# --- C33: the bounded runtime -----------------------------------------------


def test_the_default_executor_uses_the_bounded_test_runtime(factory, monkeypatch):
    adapter = DeterministicFakeModelAdapter()
    runtime = _runtime(factory, adapter)
    calls: list[str] = []

    def _bounded() -> AgentRuntime:
        calls.append("get_agent_test_runtime")
        return runtime

    monkeypatch.setattr(workbench_module, "get_agent_test_runtime", _bounded)
    workbench = AgentTestWorkbench()
    assert calls == [], "the runtime is resolved lazily, not at construction"

    _run_candidate(factory, workbench)

    assert calls == ["get_agent_test_runtime"]
    assert len(runtime.candidate_calls) == 1


# ---------------------------------------------------------------------------
# #267 whole-branch fix I-1: token usage is persisted when the provider
# reports it (AC5, spec §5.5), and stays NULL when it does not (P9).  The REAL
# ``ChatDatabricks`` runs over an ``httpx.MockTransport`` through the bounded
# test-runtime adapter, so the counts cross the real provider parsing.
# ---------------------------------------------------------------------------


def _real_provider_executor(factory: sessionmaker, usage):
    from src.services.agent_runtime import (
        TEST_RUN_MAX_RETRIES,
        TEST_RUN_TIMEOUT_SECONDS,
        DatabricksModelAdapter,
    )
    from tests.fixtures.mock_chat_completions import MockChatCompletionsWorkspace

    workspace = MockChatCompletionsWorkspace(fake_output("architect"), usage=usage)
    adapter = DatabricksModelAdapter(
        client_factory=lambda: workspace,
        transport_options={
            "timeout": TEST_RUN_TIMEOUT_SECONDS,
            "max_retries": TEST_RUN_MAX_RETRIES,
        },
    )
    workbench, _runtime_, _adapter = _executor(factory, adapter)
    return workbench, workspace


def _persisted_tokens(factory: sessionmaker) -> list[tuple[str, int | None, int | None]]:
    return [(row.run_kind, row.input_tokens, row.output_tokens) for row in _run_rows(factory)]


def test_a_real_provider_candidate_and_baseline_run_persist_the_reported_tokens(factory):
    from tests.fixtures.mock_chat_completions import (
        MOCK_COMPLETION_TOKENS,
        MOCK_PROMPT_TOKENS,
        MOCK_USAGE,
    )

    workbench, workspace = _real_provider_executor(factory, MOCK_USAGE)

    candidate = _run_candidate(factory, workbench)
    baseline = _run_baseline(factory, workbench)

    assert len(workspace.requests) == 2
    for evidence in (candidate, baseline):
        assert evidence.execution_status == "completed"
        assert evidence.candidate_raw_output == fake_output("architect")
        assert (evidence.input_tokens, evidence.output_tokens) == (
            MOCK_PROMPT_TOKENS,
            MOCK_COMPLETION_TOKENS,
        )
    assert _persisted_tokens(factory) == [
        ("candidate", MOCK_PROMPT_TOKENS, MOCK_COMPLETION_TOKENS),
        ("published_baseline", MOCK_PROMPT_TOKENS, MOCK_COMPLETION_TOKENS),
    ]


def test_a_real_provider_run_without_usage_persists_null_tokens(factory):
    workbench, workspace = _real_provider_executor(factory, None)

    candidate = _run_candidate(factory, workbench)
    baseline = _run_baseline(factory, workbench)

    assert len(workspace.requests) == 2
    for evidence in (candidate, baseline):
        assert evidence.execution_status == "completed"
        assert (evidence.input_tokens, evidence.output_tokens) == (None, None)
    assert _persisted_tokens(factory) == [
        ("candidate", None, None),
        ("published_baseline", None, None),
    ]


def test_a_fake_adapter_reporting_usage_persists_it_for_both_run_kinds(factory):
    workbench, _runtime_, _adapter = _executor(
        factory, DeterministicFakeModelAdapter(usage=(11, 7))
    )

    candidate = _run_candidate(factory, workbench)
    baseline = _run_baseline(factory, workbench)

    assert (candidate.input_tokens, candidate.output_tokens) == (11, 7)
    assert (baseline.input_tokens, baseline.output_tokens) == (11, 7)
    assert _persisted_tokens(factory) == [
        ("candidate", 11, 7),
        ("published_baseline", 11, 7),
    ]


def test_usage_reported_before_a_rejected_output_is_still_persisted(factory):
    """The tokens were spent even when validation rejects the output (incomplete)."""
    workbench, _runtime_, _adapter = _executor(
        factory,
        DeterministicFakeModelAdapter(mode="invalid_optional_field", usage=(5, None)),
    )

    evidence = _run_candidate(factory, workbench)

    assert evidence.execution_status == "incomplete"
    assert (evidence.input_tokens, evidence.output_tokens) == (5, None)
    assert _persisted_tokens(factory) == [("candidate", 5, None)]
