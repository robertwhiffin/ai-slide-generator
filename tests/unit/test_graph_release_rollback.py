"""#270 Task 2: compare with the active release, structural checks, rollback preview.

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
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import src.services.graph_configuration_content as content_module
import src.services.graph_configuration_draft as draft_module
import src.services.graph_configuration_publication as publication_module
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphRelease,
    GraphReleaseAgent,
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
    PublishedRelease,
    ReleaseComparison,
    RollbackPreview,
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


def build_v2_v3_v4(factory, monkeypatch) -> dict[str, object]:
    """v2 (architect +A), v3 (builder +B), v4 (architect +C), all via ``publish_draft``."""
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
