"""#269 Task 5: field diffs and the release preview, on SQLite.

``definition_field_diffs`` compares two definitions through ``canonical_payload()``
over a fixed field vocabulary.  ``preview_release`` reads the workbench under the
shared parent lock, collects the publication validators' issues without raising,
reads #268's readiness in the same transaction, and computes the one definition of
``publishable`` (Correction 22).  The preview is advisory: the evidence gate inside
``publish_draft`` stays authoritative (Correction 32).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.core.database import Base
from src.database.models.graph_configuration import AgentTestCase, GraphDraftAgent
from src.services.agent_runtime import AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_test_workbench import (
    AgentReadinessItem,
    AgentTestWorkbench,
    DraftReadinessResult,
)
from src.services.graph_configuration import (
    DraftSaveResult,
    DraftValidationIssue,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_configuration_publication import (
    DIFF_FIELD_NAMES,
    ChangedDefinitionPreview,
    FieldDiff,
    ReleasePreview,
    definition_field_diffs,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter

REVIEWER = "reviewer@example.com"
_OTHER_DIGEST = "0" * 64


# --- definition_field_diffs ----------------------------------------------------


def _builder() -> DefinitionContent:
    return load_graph_v1_manifest().definitions[GRAPH_V1_AGENT_KEYS.index("builder")]


def _with(content: DefinitionContent, path: tuple[str, ...], value: object) -> DefinitionContent:
    payload = content.canonical_payload()
    target = payload
    for segment in path[:-1]:
        target[segment] = dict(target[segment])
        target = target[segment]
    target[path[-1]] = value
    return DefinitionContent.model_validate(payload)


_ONE_FIELD_CHANGES = [
    (("definition_version",), 3),
    (("prompt_text",), "A different builder prompt."),
    (("model", "endpoint_name"), "databricks-other-endpoint"),
    (("model", "temperature"), 0.2),
    (("model", "max_tokens"), 1234),
    (("model", "top_p"), 0.5),
    (("schema_overlay",), {"field_overrides": {}, "additional_optional_fields": ["x"]}),
    (("assembly_rules",), {"format_version": 2, "custom_blocks": []}),
    (("protected_assembly", "version"), 2),
    (("protected_assembly", "digest"), _OTHER_DIGEST),
    (("schema_contract", "version"), 2),
    (("schema_contract", "digest"), _OTHER_DIGEST),
]


def test_the_diff_vocabulary_is_fixed_in_order():
    """Catches a reordered, renamed or missing diff field (the TS parser pins it)."""
    assert DIFF_FIELD_NAMES == (
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
    )
    # Every DefinitionContent field except the identity-constant agent_key.
    top_level = {name.split(".")[0] for name in DIFF_FIELD_NAMES}
    assert top_level == set(DefinitionContent.model_fields) - {"agent_key"}


def test_identical_definitions_have_no_diffs():
    assert definition_field_diffs(_builder(), _builder()) == ()


def test_a_float_and_its_decimal_are_not_a_diff():
    """Catches diffs computed from ``model_dump`` instead of ``canonical_payload``."""
    published = _builder()
    candidate = _with(published, ("model", "temperature"), Decimal("0.700000"))
    assert isinstance(candidate.model.temperature, Decimal)
    assert published.model.temperature == 0.7

    assert definition_field_diffs(published, candidate) == ()


@pytest.mark.parametrize(
    ("path", "value"), _ONE_FIELD_CHANGES, ids=[".".join(p) for p, _ in _ONE_FIELD_CHANGES]
)
def test_each_field_diffs_alone_with_its_canonical_values(path, value):
    published = _builder()
    candidate = _with(published, path, value)
    before = published.canonical_payload()
    for segment in path:
        before = before[segment]

    assert definition_field_diffs(published, candidate) == (
        FieldDiff(".".join(path), before, value),
    )


def test_only_differing_fields_are_returned_in_vocabulary_order():
    published = _builder()
    candidate = published
    # Applied out of vocabulary order on purpose.
    for path, value in reversed(_ONE_FIELD_CHANGES[1:8:2]):
        candidate = _with(candidate, path, value)

    diffs = definition_field_diffs(published, candidate)

    assert [diff.field for diff in diffs] == [
        "prompt_text",
        "model.temperature",
        "model.top_p",
        "assembly_rules",
    ]


def test_whole_documents_compare_as_whole_json_values():
    """``schema_overlay`` and ``assembly_rules`` are one diff each, never per key."""
    published = _builder()
    candidate = _with(
        published,
        ("assembly_rules",),
        {"format_version": 2, "custom_blocks": []},
    )

    (diff,) = definition_field_diffs(published, candidate)

    assert diff.field == "assembly_rules"
    assert diff.published == published.canonical_payload()["assembly_rules"]
    assert diff.candidate == {"format_version": 2, "custom_blocks": []}


def test_every_diff_value_is_json_and_carries_only_definition_content():
    published = _builder()
    candidate = published
    for path, value in _ONE_FIELD_CHANGES:
        candidate = _with(candidate, path, value)

    diffs = definition_field_diffs(published, candidate)

    assert [diff.field for diff in diffs] == list(DIFF_FIELD_NAMES)
    for diff in diffs:
        assert set(vars(diff)) == {"field", "published", "candidate"}
        json.dumps(diff.published, allow_nan=False)
        json.dumps(diff.candidate, allow_nan=False)


# --- preview_release ---------------------------------------------------------


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


def _save(factory, agent_key: str, prompt_text: str) -> DraftSaveResult:
    service = GraphConfiguration()
    with factory() as db:
        snap = service.read_workbench(db)
        db.rollback()
    content = next(n for n in snap.nodes if n.agent_key == agent_key).draft.content
    with factory() as db:
        out = service.save_editable_model_draft(
            db,
            agent_key=agent_key,
            expected_lock_version=snap.draft.lock_version,
            actor="editor@example.com",
            candidate=EditableModelDraft(
                prompt_text=prompt_text,
                endpoint_name=content.model.endpoint_name,
                temperature=float(content.model.temperature),
                max_tokens=content.model.max_tokens,
                top_p=float(content.model.top_p),
            ),
        )
    assert isinstance(out, DraftSaveResult)
    return out


def _seed_case_id(factory, agent_key: str) -> int:
    with factory() as db:
        return db.scalar(
            select(AgentTestCase.id).where(
                AgentTestCase.agent_key == agent_key,
                AgentTestCase.name == f"{agent_key}_required_smoke_v1",
            )
        )


def _approve_current(factory, agent_key: str) -> int:
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=DeterministicFakeModelAdapter(),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    with factory() as db:
        lock = db.scalar(text("SELECT lock_version FROM graph_draft"))
    with factory() as db:
        run = AgentTestWorkbench(runtime=runtime).execute_candidate_run(
            db,
            agent_key=agent_key,
            test_case_id=_seed_case_id(factory, agent_key),
            expected_lock_version=lock,
            actor="runner@example.com",
        )
    assert run.execution_status == "completed" and run.deterministic_checks_passed
    with factory() as db:
        AgentTestWorkbench().record_verdict(
            db, run_id=run.run_id, verdict="approved", reviewer=REVIEWER, notes=None
        )
    return run.run_id


def _deactivate_required_case(factory, agent_key: str) -> None:
    # Reachable only past #267's writers, which refuse the last required case (C43).
    with factory.begin() as db:
        db.execute(
            update(AgentTestCase)
            .where(AgentTestCase.agent_key == agent_key)
            .values(is_active=False)
        )


def _write_url_endpoint(factory, agent_key: str) -> None:
    with factory.begin() as db:
        row = db.scalar(select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key))
        row.endpoint_name = "https://x/y"
        row.candidate_hash = definition_content_hash(definition_content_from_row(row))


def _real_readiness():
    calls: list[bool] = []
    workbench = AgentTestWorkbench()

    def _readiness(session):
        calls.append(session.in_transaction())
        return workbench.readiness_under_parent_lock(session)

    return _readiness, calls


def _fake_readiness(*blocking: str):
    """A readiness that reports exactly ``blocking`` as blocking roles."""

    def _readiness(session):
        return DraftReadinessResult(
            draft_lock_version=0,
            base_release_id=1,
            all_ready=not blocking,
            blocking_agents=tuple(blocking),
            agents=tuple(
                AgentReadinessItem(
                    agent_key=key,
                    candidate_hash="a" * 64,
                    is_changed_from_base=False,
                    ready=key not in blocking,
                    missing_required_case=False,
                    cases=(),
                )
                for key in GRAPH_V1_AGENT_KEYS
            ),
        )

    return _readiness


def _preview(factory, readiness=None, service=None) -> ReleasePreview:
    readiness = readiness or _real_readiness()[0]
    service = service or GraphConfiguration()
    with factory() as db:
        return service.preview_release(db, readiness=readiness)


def _workbench(factory):
    with factory() as db:
        snapshot = GraphConfiguration().read_workbench(db)
        db.rollback()
    return snapshot


def test_an_unchanged_draft_previews_nothing_and_is_not_publishable(factory):
    readiness, calls = _real_readiness()

    preview = _preview(factory, readiness)

    snapshot = _workbench(factory)
    assert preview.draft == snapshot.draft
    assert preview.active_release == snapshot.active_release
    assert preview.next_version_number == snapshot.active_release.version_number + 1 == 2
    assert preview.changed == ()
    assert preview.validation_issues == ()
    assert preview.publishable is False
    assert calls == [True]
    assert isinstance(preview.readiness, DraftReadinessResult)
    assert preview.readiness.all_ready is True


def test_changed_roles_preview_in_role_order_with_exact_diffs(factory):
    before = _workbench(factory)
    published = {
        node.agent_key: node.published
        for node in before.nodes
        if node.execution_kind == "model"
    }
    # Saved out of role order on purpose.
    _save(factory, "builder", "A tuned builder prompt.")
    _save(factory, "architect", "A tuned architect prompt.")
    _approve_current(factory, "builder")
    _approve_current(factory, "architect")

    preview = _preview(factory)

    after = _workbench(factory)
    candidates = {
        node.agent_key: node.draft for node in after.nodes if node.execution_kind == "model"
    }
    assert preview.changed == tuple(
        ChangedDefinitionPreview(
            agent_key=key,
            published_revision_id=published[key].revision_id,
            published_content_hash=published[key].content_hash,
            candidate_hash=candidates[key].candidate_hash,
            field_diffs=(
                FieldDiff(
                    "prompt_text",
                    published[key].content.prompt_text,
                    f"A tuned {key} prompt.",
                ),
            ),
        )
        for key in ("architect", "builder")
    )
    assert preview.next_version_number == 2
    assert preview.draft == after.draft
    assert preview.validation_issues == ()
    assert preview.readiness.all_ready is True
    assert preview.publishable is True


def test_a_changed_role_awaiting_approval_is_not_publishable(factory):
    """The readiness clause: #268 reports a changed role as blocking."""
    _save(factory, "architect", "A tuned architect prompt.")

    preview = _preview(factory)

    assert [item.agent_key for item in preview.changed] == ["architect"]
    assert preview.readiness.blocking_agents == ("architect",)
    assert preview.validation_issues == ()
    assert preview.publishable is False


def test_readiness_blocking_only_an_unchanged_role_does_not_block(factory):
    """``blocking_agents`` intersects the changed roles; nothing else counts."""
    _save(factory, "architect", "A tuned architect prompt.")

    preview = _preview(factory, _fake_readiness("fixer"))

    assert preview.publishable is True


def test_readiness_blocking_a_changed_role_blocks_even_with_evidence(factory):
    _save(factory, "architect", "A tuned architect prompt.")
    _approve_current(factory, "architect")

    assert _preview(factory, _fake_readiness()).publishable is True
    assert _preview(factory, _fake_readiness("architect")).publishable is False


def test_a_changed_role_without_an_active_required_case_is_not_publishable(factory):
    """Correction 1 part 5: its own clause, even when readiness says ready."""
    _save(factory, "architect", "A tuned architect prompt.")
    _deactivate_required_case(factory, "architect")

    preview = _preview(factory, _fake_readiness())

    assert [item.agent_key for item in preview.changed] == ["architect"]
    assert preview.validation_issues == ()
    assert preview.publishable is False


def test_an_unchanged_role_without_an_active_required_case_does_not_block(factory):
    _save(factory, "architect", "A tuned architect prompt.")
    _deactivate_required_case(factory, "fixer")

    assert _preview(factory, _fake_readiness()).publishable is True


def test_an_optional_active_case_does_not_satisfy_the_required_case_clause(factory):
    _save(factory, "architect", "A tuned architect prompt.")
    _deactivate_required_case(factory, "architect")
    with factory.begin() as db:
        db.execute(
            update(AgentTestCase)
            .where(AgentTestCase.agent_key == "architect")
            .values(is_active=True, is_required=False)
        )

    assert _preview(factory, _fake_readiness()).publishable is False


def test_validation_issues_are_collected_prefixed_and_block(factory):
    """Publication's own validators, collected instead of raised."""
    _save(factory, "architect", "A tuned architect prompt.")
    _write_url_endpoint(factory, "builder")

    preview = _preview(factory, _fake_readiness())

    assert [item.agent_key for item in preview.changed] == ["architect", "builder"]
    assert preview.validation_issues == (
        DraftValidationIssue(
            "definitions.builder.candidate.model.endpoint_name",
            "endpoint_url_not_allowed",
            "Endpoint must be a Databricks endpoint name, not a URL.",
        ),
    )
    assert preview.publishable is False


def test_the_preview_reads_readiness_inside_its_transaction_after_the_parent_lock(
    factory,
):
    statements: list[str] = []
    seen_at_readiness: list[list[str]] = []
    engine = factory.kw["bind"]

    def _capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    workbench = AgentTestWorkbench()

    def _readiness(session):
        seen_at_readiness.append(list(statements))
        return workbench.readiness_under_parent_lock(session)

    _save(factory, "architect", "A tuned architect prompt.")
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        _preview(factory, _readiness)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    (before_readiness,) = seen_at_readiness
    assert "FROM graph_release JOIN graph_draft ON 1 = 1" in before_readiness[0]
    assert "graph_release.effective_to IS NULL" in before_readiness[0]


def test_the_preview_takes_the_shared_parent_lock(factory, monkeypatch):
    calls: list[bool] = []
    original = GraphConfiguration._lock_current_parents

    def _spy(self, session, *, exclusive):
        calls.append(exclusive)
        return original(self, session, exclusive=exclusive)

    monkeypatch.setattr(GraphConfiguration, "_lock_current_parents", _spy)
    _preview(factory)

    assert calls == [False]


def test_the_preview_writes_nothing(factory):
    _save(factory, "architect", "A tuned architect prompt.")
    _write_url_endpoint(factory, "builder")
    statements: list[str] = []
    engine = factory.kw["bind"]

    def _capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        _preview(factory)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert statements and set(statements) == {"SELECT"}


def test_the_preview_never_calls_the_remote_endpoint_validator(factory):
    """Correction 37: no remote call while the parent lock is held."""

    class _SpyRemoteValidator:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def validate(self, content) -> None:
            self.calls.append(content.agent_key)

    _save(factory, "architect", "A tuned architect prompt.")
    spy = _SpyRemoteValidator()

    preview = _preview(factory, service=GraphConfiguration(remote_endpoint_validator=spy))

    assert [item.agent_key for item in preview.changed] == ["architect"]
    assert spy.calls == []
