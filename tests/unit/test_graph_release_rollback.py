"""#270 Tasks 2 and 3a: compare, structural checks, rollback preview, and restore.

SQLite, with #269's real ``publish_draft`` and its test-only ``_NoEvidenceGate``.
SQLite's transaction timestamp has one-second resolution, so every publication
runs under ``install_release_clock`` (Correction 1): a strictly increasing clock,
``v1_from + n hours`` for the n-th publication.  Tasks 3 and 6 import it.

SQLite renders no ``FOR SHARE``/``FOR UPDATE``; the lock statements are checked
by compiling the captured statement for PostgreSQL, and the PostgreSQL suites
(Tasks 3b-5) prove the waits.
"""

from __future__ import annotations

import ast
import inspect
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql

import src.services.graph_configuration_content as content_module
import src.services.graph_configuration_draft as draft_module
import src.services.graph_configuration_publication as publication_module
from src.core.database import Base
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestRun,
    GraphRelease,
    GraphReleaseAgent,
    GraphReleaseTestRun,
)
from src.services.graph_configuration import (
    AgentComparison,
    DraftSaveResult,
    DraftValidationIssue,
    EditableModelDraft,
    EvidenceLink,
    FieldDiff,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    PublicationConflict,
    PublicationRejected,
    PublishedRelease,
    ReleaseComparison,
    RestoredRelease,
    RollbackIncompatible,
    RollbackMatchesActive,
    RollbackPreview,
    RollbackSourceActive,
)
from src.services.graph_configuration_content import (
    as_utc_aware,
    definition_content_from_row,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    definition_content_hash,
)
from src.services.graph_release_history import (
    GraphVersionNotFound,
    ReleaseRef,
    list_release_history,
    read_release_detail,
)
from src.services.model_endpoint_catalog import EndpointValidationFailure
from src.services.prompt_assembler import PromptAssembler, _default_bundles
from tests.unit import test_graph_release_publication as publication_tests
from tests.unit.test_graph_release_history import link_run, seed_case, seed_run
from tests.unit.test_graph_release_publication import (
    _artifacts,
    _NoEvidenceGate,
    _save_prompt,
)

#: #269's SQLite fixture: in-memory engine, foreign keys on, v1 bootstrapped.
factory = publication_tests.factory

_OTHERS = ("data_analyst", "build_reviewer", "fixer", "fix_reviewer", "deck_reviewer")


# ---------------------------------------------------------------------------
# Shared harness (Correction 1; imported by Tasks 3 and 6)
# ---------------------------------------------------------------------------


class ReleaseClock:
    """A strictly increasing publication clock: ``v1_from + n hours`` for call n."""

    def __init__(self, v1_from) -> None:
        self.v1_from = v1_from
        self.call_count = 0

    def __call__(self, session):
        self.call_count += 1
        return self.v1_from + self.call_count * timedelta(hours=1)


def install_release_clock(monkeypatch, factory) -> ReleaseClock:
    """Patch the core's transaction timestamp; never sleep (Correction 1)."""
    with factory() as db:
        v1_from = as_utc_aware(
            db.scalar(
                select(GraphRelease.effective_from).where(GraphRelease.version_number == 1)
            )
        )
    clock = ReleaseClock(v1_from)
    monkeypatch.setattr(publication_module, "database_transaction_timestamp", clock)
    return clock


def current_lock(factory) -> int:
    with factory() as db:
        snapshot = GraphConfiguration().read_workbench(db)
        db.rollback()
    return snapshot.draft.lock_version


def draft_content(factory, agent_key):
    with factory() as db:
        snapshot = GraphConfiguration().read_workbench(db)
        db.rollback()
    return next(n for n in snapshot.nodes if n.agent_key == agent_key).draft.content


def publish(factory, note: str) -> PublishedRelease:
    with factory() as db:
        result = GraphConfiguration().publish_draft(
            db,
            expected_lock_version=current_lock(factory),
            release_note=note,
            actor="publisher@example.com",
            evidence_gate=_NoEvidenceGate(),
        )
    assert isinstance(result, PublishedRelease), result
    return result


def save_prompt_text(factory, agent_key: str, prompt_text: str) -> None:
    _save_prompt(factory, agent_key, "", lock=current_lock(factory), prompt_text=prompt_text)


def save_endpoint(factory, agent_key: str, endpoint_name: str) -> None:
    content = draft_content(factory, agent_key)
    with factory() as db:
        out = GraphConfiguration().save_editable_model_draft(
            db,
            agent_key=agent_key,
            expected_lock_version=current_lock(factory),
            actor="editor@example.com",
            candidate=EditableModelDraft(
                prompt_text=content.prompt_text,
                endpoint_name=endpoint_name,
                temperature=float(content.model.temperature),
                max_tokens=content.model.max_tokens,
                top_p=float(content.model.top_p),
            ),
        )
    assert isinstance(out, DraftSaveResult)


def refs(factory) -> dict[int, ReleaseRef]:
    with factory() as db:
        entries = list_release_history(db)
    return {e.version_number: ReleaseRef(e.release_id, e.version_number) for e in entries}


#: v1's id after ``offset_release_ids``: every later release id is its version
#: number plus this, so no id equals any version number (fix round 1, I-1).
RELEASE_ID_OFFSET = 10


def offset_release_ids(factory, offset: int = RELEASE_ID_OFFSET) -> None:
    """Re-key the bootstrapped v1 to ``1 + offset`` so ids never equal versions.

    On PostgreSQL a rolled-back publication consumes a ``graph_release.id``
    sequence value, so ids and version numbers diverge in production.  SQLite
    allocates ``max(id) + 1`` and has no sequence to burn, so this re-keys v1
    and every column that references ``graph_release.id`` (found from the ORM
    metadata), then proves referential integrity with ``foreign_key_check``.
    Later releases then get ``version + offset`` from SQLite's own allocation.
    """
    referencing = [
        (fk.parent.table.name, fk.parent.name)
        for table in Base.metadata.sorted_tables
        for fk in table.foreign_keys
        if fk.column.table.name == "graph_release" and fk.column.name == "id"
    ]
    raw = factory.kw["bind"].raw_connection()
    try:
        cursor = raw.cursor()
        assert cursor.execute("SELECT id, version_number FROM graph_release").fetchall() == [
            (1, 1)
        ]
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("UPDATE graph_release SET id = id + ?", (offset,))
        for table, column in referencing:
            cursor.execute(
                f"UPDATE {table} SET {column} = {column} + ? WHERE {column} IS NOT NULL",
                (offset,),
            )
        raw.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
        assert cursor.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        raw.close()


def release_ids(factory) -> list[tuple[int, int]]:
    with factory() as db:
        return [
            tuple(row)
            for row in db.execute(
                select(GraphRelease.id, GraphRelease.version_number).order_by(
                    GraphRelease.version_number
                )
            )
        ]


def build_v2_v3_v4(factory, monkeypatch) -> dict[str, object]:
    """v2 (architect +A), v3 (builder +B), v4 (architect +C), all via ``publish_draft``.

    Release ids are ``version + RELEASE_ID_OFFSET`` (``offset_release_ids``).
    """
    offset_release_ids(factory)
    clock = install_release_clock(monkeypatch, factory)
    v1_texts = {key: draft_content(factory, key).prompt_text for key in GRAPH_V1_AGENT_KEYS}
    _save_prompt(factory, "architect", "\n\nTune A.", lock=current_lock(factory))
    v2_architect = draft_content(factory, "architect").prompt_text
    publish(factory, "v2")
    _save_prompt(factory, "builder", "\n\nTune B.", lock=current_lock(factory))
    v3_builder = draft_content(factory, "builder").prompt_text
    publish(factory, "v3")
    _save_prompt(factory, "architect", "\n\nTune C.", lock=current_lock(factory))
    v4_architect = draft_content(factory, "architect").prompt_text
    publish(factory, "v4")
    assert clock.call_count == 3
    return {
        "clock": clock,
        "refs": refs(factory),
        "v1_texts": v1_texts,
        "v2_architect": v2_architect,
        "v3_builder": v3_builder,
        "v4_architect": v4_architect,
    }


def preview(factory, version_number: int, **service_kwargs) -> RollbackPreview:
    with factory() as db:
        return GraphConfiguration(**service_kwargs).preview_rollback(
            db, version_number=version_number
        )


def compare(factory, version_number: int, **service_kwargs) -> ReleaseComparison:
    with factory() as db:
        return GraphConfiguration(**service_kwargs).compare_with_active(
            db, version_number=version_number
        )


def mapping(factory, release_id: int) -> dict[str, int]:
    with factory() as db:
        return dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == release_id)
            ).all()
        )


class _MustNotRun:
    def validate(self, content):
        raise AssertionError("the remote endpoint validator must not run here")


class _RecordingValidator:
    """Records every call and whether the caller's session had a transaction open."""

    def __init__(self, session_holder: dict, failing: set[str] | None = None) -> None:
        self.session_holder = session_holder
        self.failing = failing
        self.calls: list[tuple[str, bool]] = []

    def validate(self, content):
        session = self.session_holder["session"]
        self.calls.append((content.model.endpoint_name, session.in_transaction()))
        if self.failing is None or content.model.endpoint_name in self.failing:
            raise EndpointValidationFailure(
                "endpoint_unavailable", "Endpoint is unavailable.", True
            )


def _preview_with(factory, version_number: int, validator, holder) -> RollbackPreview:
    with factory() as db:
        holder["session"] = db
        return GraphConfiguration(remote_endpoint_validator=validator).preview_rollback(
            db, version_number=version_number
        )


# ---------------------------------------------------------------------------
# The harness itself (Correction 1, step 3)
# ---------------------------------------------------------------------------


def test_release_clock_publishes_v2_to_v8_in_sequence_on_sqlite(factory, monkeypatch):
    clock = install_release_clock(monkeypatch, factory)
    for version in range(2, 9):
        _save_prompt(factory, "architect", f"\n\nv{version}.", lock=current_lock(factory))
        published = publish(factory, f"v{version}")
        assert published.release.version_number == version
    assert clock.call_count == 7
    with factory() as db:
        versions = list(
            db.scalars(select(GraphRelease.version_number).order_by(GraphRelease.id))
        )
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8]


# ---------------------------------------------------------------------------
# compare_with_active
# ---------------------------------------------------------------------------


def test_compare_active_with_historical_lists_seven_roles_with_exact_diffs(
    factory, monkeypatch
):
    built = build_v2_v3_v4(factory, monkeypatch)
    r = built["refs"]
    v2_mapping, v4_mapping = mapping(factory, r[2].release_id), mapping(factory, r[4].release_id)

    comparison = compare(factory, 2)

    assert comparison.active == r[4]
    assert comparison.historical == r[2]
    assert tuple(a.agent_key for a in comparison.agents) == GRAPH_V1_AGENT_KEYS
    by_key = {a.agent_key: a for a in comparison.agents}
    assert by_key["architect"] == AgentComparison(
        agent_key="architect",
        active_revision_id=v4_mapping["architect"],
        historical_revision_id=v2_mapping["architect"],
        same_revision=False,
        field_diffs=(
            FieldDiff("prompt_text", built["v4_architect"], built["v2_architect"]),
        ),
    )
    assert by_key["builder"] == AgentComparison(
        agent_key="builder",
        active_revision_id=v4_mapping["builder"],
        historical_revision_id=v2_mapping["builder"],
        same_revision=False,
        field_diffs=(
            FieldDiff("prompt_text", built["v3_builder"], built["v1_texts"]["builder"]),
        ),
    )
    for key in _OTHERS:
        assert by_key[key] == AgentComparison(
            agent_key=key,
            active_revision_id=v4_mapping[key],
            historical_revision_id=v2_mapping[key],
            same_revision=True,
            field_diffs=(),
        )


def test_compare_takes_no_parent_lock_and_does_no_remote_work(factory, monkeypatch):
    """Correction 22: the comparison is lock-free (the history read model's rule)."""
    build_v2_v3_v4(factory, monkeypatch)
    expected = compare(factory, 2)
    before = _artifacts(factory)

    def _no_lock(self, session, *, exclusive):
        raise AssertionError("compare_with_active must not take the parent lock")

    monkeypatch.setattr(GraphConfiguration, "_lock_current_parents", _no_lock)
    assert compare(factory, 2, remote_endpoint_validator=_MustNotRun()) == expected
    assert _artifacts(factory) == before


def test_unknown_version_is_not_found(factory, monkeypatch):
    build_v2_v3_v4(factory, monkeypatch)
    with pytest.raises(GraphVersionNotFound) as compared:
        compare(factory, 99)
    assert compared.value.version_number == 99
    with pytest.raises(GraphVersionNotFound) as previewed:
        preview(factory, 99)
    assert previewed.value.version_number == 99


# ---------------------------------------------------------------------------
# preview_rollback
# ---------------------------------------------------------------------------


def test_preview_names_next_version_lineage_evidence_and_default_note(
    factory, monkeypatch
):
    built = build_v2_v3_v4(factory, monkeypatch)
    r = built["refs"]
    lock = current_lock(factory)

    result = preview(factory, 2)

    assert result.next_version_number == 5
    assert result.source == r[2]
    assert result.active == r[4]
    assert result.lock_version == lock
    assert result.default_release_note == "Roll back to Graph Version 2."
    assert result.blocked is None
    assert result.restorable is True
    assert result.issues == ()
    assert result.warnings == ()
    assert result.evidence == ()
    assert result.comparison == compare(factory, 2)


def test_preview_draft_effect_is_three_way(factory, monkeypatch):
    build_v2_v3_v4(factory, monkeypatch)
    _save_prompt(factory, "builder", "\n\nPending P.", lock=current_lock(factory))

    result = preview(factory, 2)

    assert result.draft_effect == {
        "architect": "reset",
        "builder": "kept",
        **{key: "unchanged" for key in _OTHERS},
    }
    assert tuple(result.draft_effect) == GRAPH_V1_AGENT_KEYS


def test_a_pending_edit_is_kept_even_on_a_role_identical_in_both_releases(
    factory, monkeypatch
):
    """Q7: a saved edit is kept whatever the active and restored contents are."""
    build_v2_v3_v4(factory, monkeypatch)
    _save_prompt(factory, "fixer", "\n\nPending P.", lock=current_lock(factory))

    result = preview(factory, 2)

    assert result.draft_effect["fixer"] == "kept"
    assert result.draft_effect["architect"] == "reset"
    assert result.draft_effect["builder"] == "reset"


def test_a_draft_saved_to_exactly_the_restored_content_is_kept(factory, monkeypatch):
    """Q7: equal to the restored content is still a pending edit against the active."""
    built = build_v2_v3_v4(factory, monkeypatch)
    save_prompt_text(factory, "architect", built["v2_architect"])

    result = preview(factory, 2)

    assert result.draft_effect["architect"] == "kept"
    assert result.draft_effect["builder"] == "reset"


def test_ids_that_differ_from_versions_resolve_by_version_everywhere(
    factory, monkeypatch
):
    """Fix round 1, I-1: every version-to-id resolution, with id = version + 10."""
    build_v2_v3_v4(factory, monkeypatch)
    offset = RELEASE_ID_OFFSET
    assert release_ids(factory) == [(v + offset, v) for v in (1, 2, 3, 4)]
    ids = _link_v2_runs(factory, {1: ReleaseRef(1 + offset, 1), 2: ReleaseRef(2 + offset, 2)})

    with factory() as db:
        entries = list_release_history(db)
        detail = read_release_detail(db, version_number=2)
    assert [(e.release_id, e.version_number) for e in entries] == [
        (v + offset, v) for v in (4, 3, 2, 1)
    ]
    assert entries[0].previous == ReleaseRef(3 + offset, 3)
    assert (detail.entry.release_id, detail.entry.version_number) == (2 + offset, 2)
    assert detail.entry.previous == ReleaseRef(1 + offset, 1)

    comparison = compare(factory, 2)
    assert comparison.active == ReleaseRef(4 + offset, 4)
    assert comparison.historical == ReleaseRef(2 + offset, 2)

    result = preview(factory, 2)
    assert result.source == ReleaseRef(2 + offset, 2)
    assert result.active == ReleaseRef(4 + offset, 4)
    assert result.next_version_number == 5
    assert result.default_release_note == "Roll back to Graph Version 2."
    assert {link.source_release_id for link in result.evidence} == {2 + offset}
    assert {link.agent_test_run_id for link in result.evidence} == {
        ids[name]
        for name in ("builder", "architect_other", "architect_first", "architect_second")
    }


def test_preview_first_statement_is_the_shared_parent_lock(factory, monkeypatch):
    """Fix round 1, I-2: L0 ``FOR SHARE`` (never ``FOR UPDATE``), first statement."""
    build_v2_v3_v4(factory, monkeypatch)
    statements: list[object] = []
    with factory() as db:
        event.listen(
            db, "do_orm_execute", lambda state: statements.append(state.statement)
        )
        GraphConfiguration().preview_rollback(db, version_number=2)

    first = " ".join(str(statements[0].compile(dialect=postgresql.dialect())).split())
    assert first.endswith("FOR SHARE OF graph_release, graph_draft")


def test_preview_blocks_source_active_then_matches_active(factory, monkeypatch):
    built = build_v2_v3_v4(factory, monkeypatch)
    assert preview(factory, 4).blocked == "source_is_active"
    assert preview(factory, 4).restorable is False

    save_prompt_text(factory, "architect", built["v2_architect"])
    save_prompt_text(factory, "builder", built["v1_texts"]["builder"])
    publish(factory, "v5 = v2")
    r = refs(factory)
    assert mapping(factory, r[5].release_id) == mapping(factory, r[2].release_id)

    result = preview(factory, 2)
    assert result.blocked == "matches_active"
    assert result.restorable is False
    assert result.issues == ()


def test_incompatible_historical_release_is_reported_per_role(factory, monkeypatch):
    build_v2_v3_v4(factory, monkeypatch)
    with factory() as db:
        v2_id = db.scalar(select(GraphRelease.id).where(GraphRelease.version_number == 2))
        revision = db.get(AgentDefinitionRevision, mapping(factory, v2_id)["architect"])
        identity = (revision.protected_assembly_version, revision.protected_assembly_digest)
    bundles = {k: v for k, v in _default_bundles().items() if k != identity}
    assert len(bundles) == len(_default_bundles()) - 1
    # Every v1-lineage role shares v2 architect's bundle, so v4's goes too.
    monkeypatch.setattr(draft_module, "_PROMPT_ASSEMBLER", PromptAssembler(bundles=bundles))
    before = _artifacts(factory)

    result = preview(factory, 2)

    assert result.blocked == "incompatible"
    assert result.restorable is False
    assert result.issues[0] == DraftValidationIssue(
        "definitions.architect.protected_assembly.version",
        "protected_bundle_unavailable",
        "Protected assembly bundle is unavailable.",
    )
    assert [i.field.split(".")[1] for i in result.issues] == list(GRAPH_V1_AGENT_KEYS)
    assert _artifacts(factory) == before


def test_blocked_is_the_first_applicable_check_and_issues_are_still_reported(
    factory, monkeypatch
):
    """``source_is_active`` wins over ``incompatible``; the issues are still shown."""
    build_v2_v3_v4(factory, monkeypatch)
    monkeypatch.setattr(draft_module, "_PROMPT_ASSEMBLER", PromptAssembler(bundles={}))

    result = preview(factory, 4)

    assert result.blocked == "source_is_active"
    assert len(result.issues) == len(GRAPH_V1_AGENT_KEYS)
    assert result.issues[0].code == "protected_bundle_unavailable"


def test_endpoint_name_policy_makes_a_historical_release_incompatible(
    factory, monkeypatch
):
    """Correction 32: rollback validates with publication's local phase, incl. #266's policy."""
    build_v2_v3_v4(factory, monkeypatch)
    r = refs(factory)
    with factory.begin() as db:  # SQLite has no mutation guards
        revision = db.get(
            AgentDefinitionRevision, mapping(factory, r[2].release_id)["architect"]
        )
        revision.endpoint_name = "https://example.invalid/serving-endpoints/x"
        revision.content_hash = definition_content_hash(definition_content_from_row(revision))

    result = preview(factory, 2)

    assert result.blocked == "incompatible"
    assert result.issues == (
        DraftValidationIssue(
            "definitions.architect.candidate.model.endpoint_name",
            "endpoint_url_not_allowed",
            "Endpoint must be a Databricks endpoint name, not a URL.",
        ),
    )


def test_a_failed_local_phase_skips_the_post_stale_phase(factory, monkeypatch):
    """One ``try`` per role, as in publication's ``_changed_candidate_issues``."""
    build_v2_v3_v4(factory, monkeypatch)
    seen: list[str] = []

    def _post_stale(content):
        seen.append(content.agent_key)
        return (DraftValidationIssue("candidate.x", "post_stale", "Post-stale."),)

    monkeypatch.setattr(GraphConfiguration, "post_stale_validators", (_post_stale,))
    clean = preview(factory, 2)
    assert seen == list(GRAPH_V1_AGENT_KEYS)
    assert clean.issues[0] == DraftValidationIssue(
        "definitions.architect.candidate.x", "post_stale", "Post-stale."
    )
    assert clean.blocked == "incompatible"

    seen.clear()
    monkeypatch.setattr(draft_module, "_PROMPT_ASSEMBLER", PromptAssembler(bundles={}))
    rejected = preview(factory, 2)
    assert seen == []
    assert all(i.code == "protected_bundle_unavailable" for i in rejected.issues)


def test_rollback_and_publication_share_one_candidate_validation_loop(monkeypatch):
    """2-m-2: ``_structural_issues`` and #269's ``_changed_candidate_issues`` both
    delegate to one helper over a contents mapping, so a validator phase added to
    publication also applies to rollback (Correction 32)."""
    from types import SimpleNamespace

    calls: list[list[tuple[str, object]]] = []
    marker = DraftValidationIssue("definitions.x.y", "shared", "Shared.")

    def _spy(self, contents):
        calls.append(list(contents.items()))
        return [marker]

    monkeypatch.setattr(GraphConfiguration, "_candidate_contents_issues", _spy)
    service = GraphConfiguration()
    contents = {key: f"content-{key}" for key in reversed(GRAPH_V1_AGENT_KEYS)}

    assert service._structural_issues(contents) == (marker,)
    assert calls == [[(key, f"content-{key}") for key in GRAPH_V1_AGENT_KEYS]]

    calls.clear()
    changed = (GRAPH_V1_AGENT_KEYS[3], GRAPH_V1_AGENT_KEYS[0])
    model_nodes = {
        key: SimpleNamespace(draft=SimpleNamespace(content=f"draft-{key}"))
        for key in GRAPH_V1_AGENT_KEYS
    }
    assert service._changed_candidate_issues(model_nodes, changed) == [marker]
    assert calls == [[(key, f"draft-{key}") for key in changed]]


def test_preview_runs_the_remote_check_after_the_locked_transaction(factory, monkeypatch):
    """Corrections 2 and 34: the remote check runs outside any transaction."""
    build_v2_v3_v4(factory, monkeypatch)

    def _no_runtime(self, *args, **kwargs):
        raise AssertionError("the preview must not construct an AgentRuntime")

    monkeypatch.setattr("src.services.agent_runtime.AgentRuntime.__init__", _no_runtime)
    holder: dict = {}
    validator = _RecordingValidator(holder, failing=set())
    before = _artifacts(factory)

    result = _preview_with(factory, 2, validator, holder)

    assert validator.calls == [("databricks-claude-opus-4-6", False)]
    assert result.warnings == ()
    assert result.restorable is True
    assert _artifacts(factory) == before


def test_preview_endpoint_failures_are_warnings_that_never_block(factory, monkeypatch):
    build_v2_v3_v4(factory, monkeypatch)
    holder: dict = {}
    before = _artifacts(factory)

    result = _preview_with(factory, 2, _RecordingValidator(holder), holder)

    assert len(result.warnings) == 7
    assert result.warnings == tuple(
        DraftValidationIssue(
            f"definitions.{key}.candidate.model.endpoint_name",
            "endpoint_unavailable",
            "Endpoint is unavailable.",
        )
        for key in GRAPH_V1_AGENT_KEYS
    )
    assert result.restorable is True
    assert result.blocked is None
    assert result.issues == ()
    assert _artifacts(factory) == before


def test_preview_checks_each_distinct_endpoint_once_and_warns_every_user(
    factory, monkeypatch
):
    build_v2_v3_v4(factory, monkeypatch)
    save_endpoint(factory, "fixer", "databricks-other-endpoint")
    publish(factory, "v5")
    _save_prompt(factory, "architect", "\n\nTune D.", lock=current_lock(factory))
    publish(factory, "v6")
    holder: dict = {}
    validator = _RecordingValidator(holder, failing={"databricks-other-endpoint"})

    result = _preview_with(factory, 5, validator, holder)

    assert validator.calls == [
        ("databricks-claude-opus-4-6", False),
        ("databricks-other-endpoint", False),
    ]
    assert result.warnings == (
        DraftValidationIssue(
            "definitions.fixer.candidate.model.endpoint_name",
            "endpoint_unavailable",
            "Endpoint is unavailable.",
        ),
    )
    assert result.blocked is None


# ---------------------------------------------------------------------------
# The source's evidence
# ---------------------------------------------------------------------------


def _link_v2_runs(factory, r) -> dict[str, int]:
    """Runs linked to v2, created so that run-id order differs from the result order.

    Result order is (``GRAPH_V1_AGENT_KEYS`` index, test case id, run id).
    """
    builder_case = seed_case(factory, agent_key="builder", name="builder smoke")
    architect_case = seed_case(factory, agent_key="architect", name="architect smoke")
    other_case = seed_case(factory, agent_key="architect", name="architect other")
    v1 = r[1].release_id
    ids = {
        "builder_case": builder_case,
        "architect_case": architect_case,
        "other_case": other_case,
        "builder": seed_run(factory, case_id=builder_case, agent_key="builder", release_id=v1),
        "architect_other": seed_run(
            factory, case_id=other_case, agent_key="architect", release_id=v1
        ),
        "architect_first": seed_run(
            factory, case_id=architect_case, agent_key="architect", release_id=v1
        ),
        "architect_second": seed_run(
            factory, case_id=architect_case, agent_key="architect", release_id=v1
        ),
    }
    for name in ("builder", "architect_other", "architect_first", "architect_second"):
        link_run(factory, release_id=r[2].release_id, run_id=ids[name])
    return ids


def test_preview_evidence_is_the_source_runs_as_historical_restore_in_role_order(
    factory, monkeypatch
):
    build_v2_v3_v4(factory, monkeypatch)
    r = refs(factory)
    ids = _link_v2_runs(factory, r)

    result = preview(factory, 2)

    v2 = r[2].release_id
    assert result.evidence == (
        EvidenceLink(
            ids["architect_first"], "architect", ids["architect_case"], "historical_restore", v2
        ),
        EvidenceLink(
            ids["architect_second"], "architect", ids["architect_case"], "historical_restore", v2
        ),
        EvidenceLink(
            ids["architect_other"], "architect", ids["other_case"], "historical_restore", v2
        ),
        EvidenceLink(ids["builder"], "builder", ids["builder_case"], "historical_restore", v2),
    )
    # Another release's links are not the source's.
    assert preview(factory, 3).evidence == ()


def test_preview_source_linked_to_a_non_candidate_run_is_an_integrity_error(
    factory, monkeypatch
):
    build_v2_v3_v4(factory, monkeypatch)
    r = refs(factory)
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    baseline = seed_run(
        factory, case_id=case_id, agent_key="architect", release_id=r[1].release_id,
        run_kind="published_baseline",
    )
    link_run(factory, release_id=r[2].release_id, run_id=baseline)

    with pytest.raises(
        GraphConfigurationIntegrityError,
        match="^release evidence references a non-candidate run$",
    ):
        preview(factory, 2)


def test_locked_historical_evidence_is_l3_for_update_in_id_order(factory, monkeypatch):
    """Correction 28: ``lock=True`` is ``FOR UPDATE OF agent_test_run``, id order, refreshed."""
    build_v2_v3_v4(factory, monkeypatch)
    r = refs(factory)
    ids = _link_v2_runs(factory, r)
    service = GraphConfiguration()
    statements: dict[bool, list] = {}

    for lock in (False, True):
        with factory() as db:
            real_scalars = db.scalars

            def _spy(statement, *args, _seen=statements.setdefault(lock, []), **kwargs):
                _seen.append(statement)
                return real_scalars(statement, *args, **kwargs)

            db.scalars = _spy
            with db.begin():
                links = service._historical_evidence(
                    db, source_release_id=r[2].release_id, lock=lock
                )
        assert [link.agent_test_run_id for link in links] == [
            ids["architect_first"],
            ids["architect_second"],
            ids["architect_other"],
            ids["builder"],
        ]

    def _sql(statement) -> str:
        return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())

    assert _sql(statements[True][0]).endswith(
        "ORDER BY agent_test_run.id FOR UPDATE OF agent_test_run"
    )
    assert statements[True][0].get_execution_options().get("populate_existing") is True
    assert _sql(statements[False][0]).endswith("ORDER BY agent_test_run.id")


# ---------------------------------------------------------------------------
# _load_source and module hygiene
# ---------------------------------------------------------------------------


def test_load_source_maps_malformed_historical_content_to_an_integrity_error(
    factory, monkeypatch
):
    """Correction 12 as re-aimed by Correction 33: never a bare ``TypeError``."""
    build_v2_v3_v4(factory, monkeypatch)

    def _malformed(row):
        raise TypeError("malformed persisted content")

    monkeypatch.setattr(content_module, "definition_content_from_row", _malformed)
    with factory() as db:
        with db.begin():
            with pytest.raises(
                GraphConfigurationIntegrityError, match="has invalid semantic content$"
            ) as raised:
                GraphConfiguration()._load_source(db, version_number=2)
    assert isinstance(raised.value.__cause__, TypeError)


def test_load_source_returns_the_exact_seven_historical_definitions(factory, monkeypatch):
    built = build_v2_v3_v4(factory, monkeypatch)
    r = built["refs"]
    with factory() as db:
        with db.begin():
            source = GraphConfiguration()._load_source(db, version_number=2)
    assert source.ref == r[2]
    assert tuple(source.contents) == GRAPH_V1_AGENT_KEYS
    assert {k: d.agent_definition_revision_id for k, d in source.definitions.items()} == (
        mapping(factory, r[2].release_id)
    )
    assert source.contents["architect"].prompt_text == built["v2_architect"]


def test_rollback_module_imports_no_evidence_or_workbench_module_at_module_scope():
    """Correction 29: the facade imports this module; those modules import it back."""
    path = Path(__file__).resolve().parents[2] / "src/services/graph_configuration_rollback.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    }
    assert "src.services.graph_release_evidence" not in imported
    assert "src.services.agent_test_workbench" not in imported
    assert "src.services.agent_runtime" not in imported


def test_facade_puts_rollback_first_in_its_bases():
    from src.services.graph_configuration_rollback import _GraphConfigurationRollback

    assert GraphConfiguration.__bases__[0] is _GraphConfigurationRollback


# ===========================================================================
# Task 3a: restore_release
# ===========================================================================

_ONCALL = "oncall@example.com"
_NOTE = "Emergency: back to 3"
_UNSET = object()


def build_v2_to_v7(factory, monkeypatch) -> dict[str, object]:
    """v2..v7 each change architect (+2 .. +7) through ``publish_draft``.

    Release ids are ``version + RELEASE_ID_OFFSET`` (``offset_release_ids``), so no
    id equals any version number.
    """
    offset_release_ids(factory)
    clock = install_release_clock(monkeypatch, factory)
    architect_texts: dict[int, str] = {}
    for version in range(2, 8):
        _save_prompt(factory, "architect", f"\n\n+{version}", lock=current_lock(factory))
        architect_texts[version] = draft_content(factory, "architect").prompt_text
        publish(factory, f"v{version}")
    assert clock.call_count == 6
    return {"clock": clock, "refs": refs(factory), "architect_texts": architect_texts}


def restore(
    factory,
    version_number,
    *,
    lock=_UNSET,
    note=_NOTE,
    actor=_ONCALL,
    service=None,
):
    service = GraphConfiguration() if service is None else service
    with factory() as db:
        return service.restore_release(
            db,
            version_number=version_number,
            expected_lock_version=current_lock(factory) if lock is _UNSET else lock,
            release_note=note,
            actor=actor,
        )


def rollback_artifacts(factory) -> dict[str, list[tuple[object, ...]]]:
    """#269's artefact tuples plus the evidence links and the runs' verdict columns."""
    artifacts = _artifacts(factory)
    with factory() as db:
        artifacts["links"] = [
            tuple(row)
            for row in db.execute(
                select(
                    GraphReleaseTestRun.graph_release_id,
                    GraphReleaseTestRun.agent_test_run_id,
                    GraphReleaseTestRun.evidence_kind,
                    GraphReleaseTestRun.source_release_id,
                ).order_by(
                    GraphReleaseTestRun.graph_release_id,
                    GraphReleaseTestRun.agent_test_run_id,
                    GraphReleaseTestRun.evidence_kind,
                )
            )
        ]
        artifacts["runs"] = [
            tuple(row)
            for row in db.execute(
                select(
                    AgentTestRun.id,
                    AgentTestRun.verdict,
                    AgentTestRun.verdict_reviewer,
                    AgentTestRun.verdict_at,
                    AgentTestRun.verdict_notes,
                ).order_by(AgentTestRun.id)
            )
        ]
    return artifacts


def link_v3_evidence(factory, r) -> dict[str, int]:
    """An approved architect run linked to v3 (``R3``), plus one linked to v5 only."""
    case_id = seed_case(factory, agent_key="architect", name="architect smoke")
    r3 = seed_run(factory, case_id=case_id, agent_key="architect", release_id=r[2].release_id)
    r5 = seed_run(factory, case_id=case_id, agent_key="architect", release_id=r[4].release_id)
    link_run(factory, release_id=r[3].release_id, run_id=r3)
    link_run(factory, release_id=r[5].release_id, run_id=r5)
    return {"case": case_id, "r3": r3, "r5": r5}


def workbench_nodes(factory):
    with factory() as db:
        snapshot = GraphConfiguration().read_workbench(db)
        db.rollback()
    return snapshot, {n.agent_key: n for n in snapshot.nodes if n.execution_kind == "model"}


def fresh_release(factory, release_id: int) -> GraphRelease:
    with factory() as db:
        return db.get(GraphRelease, release_id)


def _pg(statement) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def test_restore_v3_while_v7_active_produces_v8_restoring_v3(factory, monkeypatch):
    built = build_v2_to_v7(factory, monkeypatch)
    r = built["refs"]
    offset = RELEASE_ID_OFFSET
    assert [r[v] for v in range(1, 8)] == [ReleaseRef(v + offset, v) for v in range(1, 8)]
    evidence_ids = link_v3_evidence(factory, r)
    lock = current_lock(factory)
    v3_mapping = mapping(factory, r[3].release_id)
    v3_effective_to = fresh_release(factory, r[3].release_id).effective_to
    with factory() as db:
        revision_ids = set(db.scalars(select(AgentDefinitionRevision.id)))

    outcome = restore(factory, 3, lock=lock)

    assert isinstance(outcome, RestoredRelease), outcome
    published = outcome.published
    assert outcome.source == r[3]
    assert published.release.version_number == 8
    assert published.release.release_id == 8 + offset
    assert published.previous_release_id == r[7].release_id
    assert published.release.restored_from_release_id == r[3].release_id
    assert published.release.release_note == _NOTE
    assert published.release.published_by == _ONCALL
    assert tuple(published.mappings) == GRAPH_V1_AGENT_KEYS
    assert {k: m.agent_definition_revision_id for k, m in published.mappings.items()} == (
        v3_mapping
    )
    assert all(m.reused is True for m in published.mappings.values())
    assert published.changed_agent_keys == ("architect",)
    assert mapping(factory, published.release.release_id) == v3_mapping
    with factory() as db:
        assert set(db.scalars(select(AgentDefinitionRevision.id))) == revision_ids
        versions = list(db.scalars(select(GraphRelease.version_number)))
    assert sorted(versions) == list(range(1, 9))

    v7, v8 = fresh_release(factory, r[7].release_id), fresh_release(
        factory, published.release.release_id
    )
    assert v7.effective_to == v8.effective_from
    assert v8.effective_to is None
    assert fresh_release(factory, r[3].release_id).effective_to == v3_effective_to

    # Evidence: the source's links, as ``historical_restore`` with the source id.
    expected_link = EvidenceLink(
        evidence_ids["r3"], "architect", evidence_ids["case"], "historical_restore",
        r[3].release_id,
    )
    assert published.evidence == (expected_link,)
    with factory() as db:
        v8_links = db.execute(
            select(
                GraphReleaseTestRun.agent_test_run_id,
                GraphReleaseTestRun.evidence_kind,
                GraphReleaseTestRun.source_release_id,
            ).where(GraphReleaseTestRun.graph_release_id == v8.id)
        ).all()
    assert [tuple(row) for row in v8_links] == [
        (evidence_ids["r3"], "historical_restore", r[3].release_id)
    ]

    snapshot, _nodes = workbench_nodes(factory)
    assert snapshot.draft.base_release_id == v8.id
    assert snapshot.draft.lock_version == lock + 1
    assert published.draft.lock_version == lock + 1
    assert published.draft.base_release_id == v8.id

    with factory() as db:
        entries = list_release_history(db)
    assert entries[0].release_id == v8.id
    assert entries[0].version_number == 8
    assert entries[0].restored_from == r[3]
    assert entries[0].previous == r[7]
    by_version = {e.version_number: e for e in entries}
    assert by_version[3].restored_by == (ReleaseRef(v8.id, 8),)


def test_restore_resets_clean_roles_and_keeps_pending_edits(factory, monkeypatch):
    build_v2_to_v7(factory, monkeypatch)
    r = refs(factory)
    _save_prompt(factory, "builder", "\n\nPending P.", lock=current_lock(factory))
    _before_snapshot, before = workbench_nodes(factory)
    lock = current_lock(factory)
    with factory() as db:
        v3_architect_hash = db.get(
            AgentDefinitionRevision, mapping(factory, r[3].release_id)["architect"]
        ).content_hash

    outcome = restore(factory, 3, lock=lock)

    assert isinstance(outcome, RestoredRelease), outcome
    assert outcome.draft_effect == {
        "architect": "reset",
        "builder": "kept",
        **{key: "unchanged" for key in _OTHERS},
    }
    assert tuple(outcome.draft_effect) == GRAPH_V1_AGENT_KEYS
    after_snapshot, after = workbench_nodes(factory)
    assert after_snapshot.draft.lock_version == lock + 1
    assert after["architect"].changed is False
    assert after["architect"].draft.candidate_hash == v3_architect_hash
    assert after["architect"].draft.content == after["architect"].published.content
    assert after["builder"].changed is True
    assert after["builder"].draft.candidate_hash == before["builder"].draft.candidate_hash
    assert after["builder"].draft.content == before["builder"].draft.content
    for key in _OTHERS:
        assert after[key].changed is False
        assert after[key].draft.candidate_hash == before[key].draft.candidate_hash


def test_stale_lock_returns_conflict_and_writes_nothing(factory, monkeypatch):
    build_v2_to_v7(factory, monkeypatch)
    r = refs(factory)
    link_v3_evidence(factory, r)
    snapshot, _nodes = workbench_nodes(factory)
    lock = snapshot.draft.lock_version
    before = rollback_artifacts(factory)

    expected = PublicationConflict(
        expected_lock_version=lock - 1,
        current_lock_version=lock,
        active_release_id=r[7].release_id,
        active_version_number=7,
        draft=snapshot.draft,
    )
    assert restore(factory, 3, lock=lock - 1) == expected
    # The stale check precedes the rollback-specific refusals.
    assert restore(factory, 7, lock=lock - 1) == expected
    assert rollback_artifacts(factory) == before


def _incompatible_bundles(factory, monkeypatch, r) -> None:
    """Task 2's monkeypatch: v3 architect's protected bundle is no longer known."""
    with factory() as db:
        revision = db.get(
            AgentDefinitionRevision, mapping(factory, r[3].release_id)["architect"]
        )
        identity = (revision.protected_assembly_version, revision.protected_assembly_digest)
    bundles = {k: v for k, v in _default_bundles().items() if k != identity}
    assert len(bundles) == len(_default_bundles()) - 1
    monkeypatch.setattr(draft_module, "_PROMPT_ASSEMBLER", PromptAssembler(bundles=bundles))


def _publish_v8_matching_v5(factory, built) -> None:
    """Correction 18: v8's architect equals v5's; every other role is shared."""
    save_prompt_text(factory, "architect", built["architect_texts"][5])
    publish(factory, "v8 = v5")
    r = refs(factory)
    assert mapping(factory, r[8].release_id) == mapping(factory, r[5].release_id)


@pytest.mark.parametrize(
    "case", ["unknown", "source_active", "matches_active", "incompatible", "matches_first"]
)
def test_refusals_write_nothing(factory, monkeypatch, case):
    built = build_v2_to_v7(factory, monkeypatch)
    r = refs(factory)
    link_v3_evidence(factory, r)
    if case in ("matches_active", "matches_first"):
        _publish_v8_matching_v5(factory, built)
        r = refs(factory)
        assert preview(factory, 5).blocked == "matches_active"
    if case in ("incompatible", "matches_first"):
        _incompatible_bundles(factory, monkeypatch, r)
    before = rollback_artifacts(factory)

    if case == "unknown":
        with pytest.raises(GraphVersionNotFound) as raised:
            restore(factory, 99)
        assert raised.value.version_number == 99
    elif case == "source_active":
        assert restore(factory, 7) == RollbackSourceActive(r[7])
    elif case in ("matches_active", "matches_first"):
        # ``matches_active`` precedes ``incompatible`` (``matches_first``).
        assert restore(factory, 5) == RollbackMatchesActive(active=r[8], source=r[5])
    else:
        with pytest.raises(RollbackIncompatible) as raised:
            restore(factory, 3)
        assert raised.value.source == r[3]
        assert raised.value.issues[0] == DraftValidationIssue(
            "definitions.architect.protected_assembly.version",
            "protected_bundle_unavailable",
            "Protected assembly bundle is unavailable.",
        )
        assert [i.field.split(".")[1] for i in raised.value.issues] == list(
            GRAPH_V1_AGENT_KEYS
        )
    assert rollback_artifacts(factory) == before


def test_restore_refuses_an_endpoint_url_before_any_write(factory, monkeypatch):
    """3a-m2: the restore itself, not only the preview, refuses #266's endpoint
    policy with ``RollbackIncompatible`` and writes nothing."""
    build_v2_v3_v4(factory, monkeypatch)
    r = refs(factory)
    with factory.begin() as db:  # SQLite has no mutation guards
        revision = db.get(
            AgentDefinitionRevision, mapping(factory, r[2].release_id)["architect"]
        )
        revision.endpoint_name = "https://example.invalid/serving-endpoints/x"
        revision.content_hash = definition_content_hash(definition_content_from_row(revision))
    before = rollback_artifacts(factory)

    with pytest.raises(RollbackIncompatible) as raised:
        restore(factory, 2)

    assert raised.value.source == r[2]
    assert raised.value.issues == (
        DraftValidationIssue(
            "definitions.architect.candidate.model.endpoint_name",
            "endpoint_url_not_allowed",
            "Endpoint must be a Databricks endpoint name, not a URL.",
        ),
    )
    assert rollback_artifacts(factory) == before


_V_TYPE = DraftValidationIssue(
    "version_number", "strict_type", "version_number must be an integer."
)
_V_RANGE = DraftValidationIssue(
    "version_number", "out_of_range", "version_number must be a positive integer."
)
_ACTOR_BLANK = DraftValidationIssue("actor", "blank", "Actor must not be blank.")
_LOCK_RANGE = DraftValidationIssue(
    "lock_version", "out_of_range", "Lock version must be greater than or equal to 0."
)
_NOTE_BLANK = DraftValidationIssue("release_note", "blank", "Release note must not be blank.")
_NOTE_TYPE = DraftValidationIssue(
    "release_note", "strict_type", "Release note must be a string."
)
_NOTE_LONG = DraftValidationIssue(
    "release_note", "too_long", "Release note must be at most 2000 characters."
)


@pytest.mark.parametrize(
    ("kwargs", "issues"),
    [
        ({"version_number": 0}, (_V_RANGE,)),
        ({"version_number": -1}, (_V_RANGE,)),
        ({"version_number": True}, (_V_TYPE,)),
        ({"version_number": "3"}, (_V_TYPE,)),
        ({"version_number": 3.0}, (_V_TYPE,)),
        ({"note": ""}, (_NOTE_BLANK,)),
        ({"note": "   "}, (_NOTE_BLANK,)),
        ({"note": None}, (_NOTE_TYPE,)),
        ({"note": "x" * 2001}, (_NOTE_LONG,)),
        ({"actor": ""}, (_ACTOR_BLANK,)),
        (
            {"version_number": "3", "actor": "", "lock": -1, "note": ""},
            (_V_TYPE, _ACTOR_BLANK, _LOCK_RANGE, _NOTE_BLANK),
        ),
        (
            {"version_number": 0, "actor": " ", "note": "x" * 2001},
            (_V_RANGE, _ACTOR_BLANK, _NOTE_LONG),
        ),
    ],
)
def test_request_issues_are_rejected_before_any_lock(factory, monkeypatch, kwargs, issues):
    build_v2_to_v7(factory, monkeypatch)
    before = rollback_artifacts(factory)
    lock_calls: list[bool] = []
    real_lock = GraphConfiguration._lock_current_parents

    def _spy(self, session, *, exclusive):
        lock_calls.append(exclusive)
        return real_lock(self, session, exclusive=exclusive)

    monkeypatch.setattr(GraphConfiguration, "_lock_current_parents", _spy)
    kwargs = dict(kwargs)
    version_number = kwargs.pop("version_number", 3)
    lock = kwargs.pop("lock", 0)
    with pytest.raises(PublicationRejected) as raised:
        restore(factory, version_number, lock=lock, **kwargs)

    assert raised.value.issues == issues
    assert lock_calls == []
    assert rollback_artifacts(factory) == before


def test_note_is_stored_verbatim(factory, monkeypatch):
    build_v2_to_v7(factory, monkeypatch)
    first = restore(factory, 3, note="  keep  ")
    assert isinstance(first, RestoredRelease), first
    assert first.published.release.release_note == "  keep  "
    assert fresh_release(factory, first.published.release.release_id).release_note == (
        "  keep  "
    )

    long_note = "n" * 2000
    second = restore(factory, 4, note=long_note)
    assert isinstance(second, RestoredRelease), second
    assert second.published.release.version_number == 9
    assert fresh_release(factory, second.published.release.release_id).release_note == (
        long_note
    )


def test_rollback_calls_no_model_or_remote_validator(factory, monkeypatch):
    build_v2_to_v7(factory, monkeypatch)
    from src.services.agent_test_workbench import AgentTestWorkbench

    def _forbidden(*args, **kwargs):
        raise AssertionError("rollback must not construct or call this")

    monkeypatch.setattr("src.services.agent_runtime.AgentRuntime.__init__", _forbidden)
    monkeypatch.setattr(AgentTestWorkbench, "__init__", _forbidden)
    monkeypatch.setattr(
        draft_module.CatalogRemoteEndpointDraftValidator, "validate", _forbidden
    )

    outcome = restore(
        factory, 3, service=GraphConfiguration(remote_endpoint_validator=_MustNotRun())
    )

    assert isinstance(outcome, RestoredRelease), outcome
    assert outcome.published.release.version_number == 8


def test_rollback_lock_order_is_l0_then_l1_then_l3_before_any_write(factory, monkeypatch):
    """L0 ``FOR UPDATE`` (first statement), L1 by key, L3 runs by id, then writes."""
    build_v2_to_v7(factory, monkeypatch)
    link_v3_evidence(factory, refs(factory))
    lock = current_lock(factory)
    orm_statements: list[object] = []
    cursor_sql: list[str] = []
    engine = factory.kw["bind"]

    def _cursor(conn, cursor, statement, parameters, context, executemany):
        cursor_sql.append(" ".join(statement.split()).upper())

    event.listen(engine, "before_cursor_execute", _cursor)
    try:
        with factory() as db:
            event.listen(
                db, "do_orm_execute", lambda state: orm_statements.append(state.statement)
            )
            cursor_sql.clear()
            outcome = GraphConfiguration().restore_release(
                db,
                version_number=3,
                expected_lock_version=lock,
                release_note=_NOTE,
                actor=_ONCALL,
            )
    finally:
        event.remove(engine, "before_cursor_execute", _cursor)
    assert isinstance(outcome, RestoredRelease), outcome

    compiled = [_pg(statement) for statement in orm_statements]
    assert compiled[0].endswith("FOR UPDATE OF graph_release, graph_draft")
    assert "FROM graph_draft_agent" in compiled[1]
    assert compiled[1].endswith("ORDER BY graph_draft_agent.agent_key FOR UPDATE")
    l3 = [
        i for i, sql in enumerate(compiled)
        if sql.endswith("ORDER BY agent_test_run.id FOR UPDATE OF agent_test_run")
    ]
    assert len(l3) == 1
    l3_statement = orm_statements[l3[0]]
    assert l3_statement.get_execution_options().get("populate_existing") is True
    # No other statement locks anything.
    assert [i for i, sql in enumerate(compiled) if " FOR " in sql] == [0, 1, l3[0]]

    first_write = next(
        i for i, sql in enumerate(cursor_sql)
        if sql.startswith(("INSERT", "UPDATE", "DELETE"))
    )
    l3_cursor = next(
        i for i, sql in enumerate(cursor_sql)
        if "FROM AGENT_TEST_RUN JOIN GRAPH_RELEASE_TEST_RUN" in sql
    )
    assert l3_cursor < first_write


def test_a_materialized_revision_is_an_integrity_error_and_writes_nothing(
    factory, monkeypatch
):
    """Rollback reuses every historical revision; the core reporting a new one is fatal."""
    build_v2_to_v7(factory, monkeypatch)
    before = rollback_artifacts(factory)
    real = publication_module.materialize_or_reuse_revision

    def _reports_created(session, content, *, actor, timestamp):
        revision, _created = real(session, content, actor=actor, timestamp=timestamp)
        return revision, True

    monkeypatch.setattr(publication_module, "materialize_or_reuse_revision", _reports_created)
    with pytest.raises(
        GraphConfigurationIntegrityError, match="^rollback materialized a new revision$"
    ):
        restore(factory, 3)
    assert rollback_artifacts(factory) == before


@pytest.mark.parametrize("wrong", ["architect_unchanged", "builder_unchanged"])
def test_a_wrong_draft_effect_is_caught_by_the_rebase_verification(
    factory, monkeypatch, wrong
):
    """``_verify_rebased_draft``: an ``unchanged`` role must end clean at the
    restored content.  (A self-consistent wrong effect, e.g. a pending role
    marked ``reset``, verifies: the effect itself is pinned by Task 2's tests.)"""
    build_v2_to_v7(factory, monkeypatch)
    _save_prompt(factory, "builder", "\n\nPending P.", lock=current_lock(factory))
    before = rollback_artifacts(factory)
    real = GraphConfiguration._draft_effect

    def _wrong_effect(snapshot, restored_hashes):
        effect = dict(real(snapshot, restored_hashes))
        if wrong == "architect_unchanged":
            effect["architect"] = "unchanged"  # a role needing a reset is left at v7
        else:
            effect["builder"] = "unchanged"  # a pending edit is not clean
        return effect

    monkeypatch.setattr(GraphConfiguration, "_draft_effect", staticmethod(_wrong_effect))
    with pytest.raises(GraphConfigurationIntegrityError, match="rebased draft"):
        restore(factory, 3)
    assert rollback_artifacts(factory) == before


@pytest.mark.parametrize(
    "branch", ["reset_not_clean", "unchanged_moved", "kept_moved", "not_based"]
)
def test_verify_rebased_draft_checks_each_effect(factory, monkeypatch, branch):
    """Direct: each effect's post-condition, against the locked current release."""
    build_v2_to_v7(factory, monkeypatch)
    _save_prompt(factory, "builder", "\n\nPending P.", lock=current_lock(factory))
    service = GraphConfiguration()
    with factory() as db:
        with db.begin():
            release_row, draft_row = service._lock_current_parents(db, exclusive=True)
            rows = {
                row.agent_key: row
                for row in service._lock_all_draft_agents(db, draft_id=draft_row.id)
            }
            before = service._snapshot_locked_workbench(
                db, release=release_row, draft=draft_row
            )
            nodes = _model_nodes_of(before)
            restored = {key: nodes[key].published.content for key in GRAPH_V1_AGENT_KEYS}
            effect = {key: "unchanged" for key in GRAPH_V1_AGENT_KEYS}
            effect["builder"] = "kept"
            # The honest effect verifies.
            service._verify_rebased_draft(
                db, release_row=release_row, draft_row=draft_row, effect=effect,
                before=before, restored=restored,
            )
            if branch == "reset_not_clean":
                effect["builder"] = "reset"  # builder is pending, so not clean
            elif branch == "unchanged_moved":
                fixer = nodes["fixer"].draft.content
                moved = fixer.model_copy(update={"prompt_text": fixer.prompt_text + " moved"})
                service._assign_locked_candidate(rows["fixer"], moved)
            elif branch == "kept_moved":
                service._assign_locked_candidate(
                    rows["builder"], nodes["builder"].published.content
                )
            else:
                # A release the draft is not based on (v6; the draft is on v7).
                release_row = db.scalar(
                    select(GraphRelease).where(GraphRelease.version_number == 6)
                )
            db.flush()
            with pytest.raises(GraphConfigurationIntegrityError, match="rebased draft"):
                service._verify_rebased_draft(
                    db, release_row=release_row, draft_row=draft_row, effect=effect,
                    before=before, restored=restored,
                )
            db.rollback()


def _model_nodes_of(snapshot):
    return {n.agent_key: n for n in snapshot.nodes if n.execution_kind == "model"}


def test_a_verdict_change_on_a_linked_run_is_refused_after_rollback(factory, monkeypatch):
    """C48: the rollback's source runs stay frozen; a verdict change is refused."""
    from src.services.agent_test_workbench import (
        AgentTestWorkbench,
        IneligibleForApprovalError,
    )

    build_v2_to_v7(factory, monkeypatch)
    ids = link_v3_evidence(factory, refs(factory))
    assert isinstance(restore(factory, 3), RestoredRelease)
    before = rollback_artifacts(factory)

    with factory() as db:
        with pytest.raises(IneligibleForApprovalError) as raised:
            AgentTestWorkbench().record_verdict(
                db, run_id=ids["r3"], verdict="rejected", reviewer=_ONCALL, notes=None
            )
    assert raised.value.reason == "linked_to_release"
    assert raised.value.run_id == ids["r3"]
    assert rollback_artifacts(factory) == before


_CANDIDATE_HASH_WRITER_ALLOWLIST = [
    # Bootstrap's builder creates a fresh draft row from authoritative content.
    "services/graph_configuration_content.py:draft_from_definition:constructor",
    # The one attribute writer: the three-way rebase and every draft save (C36).
    "services/graph_configuration_draft.py:_assign_locked_candidate:attribute",
]


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _candidate_hash_writes(node: ast.AST) -> list[str]:
    """The kinds of ``candidate_hash`` write ``node`` performs, if any."""
    kinds: list[str] = []
    targets = (
        node.targets if isinstance(node, ast.Assign)
        else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign))
        else []
    )
    if any(isinstance(t, ast.Attribute) and t.attr == "candidate_hash" for t in targets):
        kinds.append("attribute")
    if not isinstance(node, ast.Call):
        return kinds
    name = _call_name(node.func)
    keywords = {k.arg for k in node.keywords}
    if name == "GraphDraftAgent" and "candidate_hash" in keywords:
        kinds.append("constructor")
    if name == "values" and (
        "candidate_hash" in keywords
        or any(
            isinstance(arg, ast.Dict)
            and any(
                isinstance(k, ast.Constant) and k.value == "candidate_hash"
                for k in arg.keys
            )
            for arg in node.args
        )
    ):
        kinds.append("values")
    if (
        name == "setattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "candidate_hash"
    ):
        kinds.append("setattr")
    return kinds


def _candidate_hash_writers(root: Path) -> list[str]:
    writers: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                for kind in _candidate_hash_writes(node):
                    writers.append(f"{path.relative_to(root)}:{func.name}:{kind}")
    return sorted(writers)


def test_candidate_hash_writers_are_the_allowlisted_attribute_and_builder_sites():
    """Structural pin (C36), reviewed rather than relied on: the draft behaviour is
    proven by ``test_graph_configuration_draft.py`` in the gate.

    Pins every ``candidate_hash`` write in ``src``: attribute assignment anywhere,
    ``GraphDraftAgent(candidate_hash=...)``, Core ``.values(candidate_hash=...)`` or a
    ``{"candidate_hash": ...}`` values mapping, and ``setattr(..., "candidate_hash",
    ...)``. Only the allowlisted sites may write it."""
    source = inspect.getsource(draft_module._GraphConfigurationDraft._write_locked_content)
    assert "_GraphConfigurationDraft._assign_locked_candidate(" in source
    assert "setattr(" not in source
    root = Path(__file__).resolve().parents[2] / "src"
    assert _candidate_hash_writers(root) == _CANDIDATE_HASH_WRITER_ALLOWLIST


@pytest.mark.parametrize(
    ("snippet", "kind"),
    [
        ("row.candidate_hash = h", "attribute"),
        ("GraphDraftAgent(graph_draft_id=1, candidate_hash=h)", "constructor"),
        ("update(GraphDraftAgent).values(candidate_hash=h)", "values"),
        ('update(GraphDraftAgent).values({"candidate_hash": h})', "values"),
        ('setattr(row, "candidate_hash", h)', "setattr"),
    ],
)
def test_candidate_hash_writer_scan_detects_each_write_form(tmp_path, snippet, kind):
    (tmp_path / "rogue.py").write_text(f"def rogue(row, h):\n    {snippet}\n")
    assert _candidate_hash_writers(tmp_path) == [f"rogue.py:rogue:{kind}"]
