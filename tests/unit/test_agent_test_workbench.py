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
