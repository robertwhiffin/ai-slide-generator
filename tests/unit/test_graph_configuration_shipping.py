"""Prompt shipping (Task 1): ship, adopt and status for the packaged manifest.

SQLite, with #269's real ``publish_draft`` (and its test-only ``_NoEvidenceGate``)
for hand edits and #270's real ``restore_release`` for rollbacks.  The fixture
bootstraps v1 from the packaged manifest, so a fresh install is untouched and
matches it.  Test manifests are ``load_graph_v1_manifest()`` with one or more
roles' ``prompt_text`` replaced (``_manifest``).

SQLite's transaction timestamp has one-second resolution, so every publication
after v1 runs under ``install_release_clock`` (Correction 7).  SQLite renders no
``FOR SHARE``/``FOR UPDATE`` and skips the bootstrap advisory lock (Correction 6):
lock statements are checked by compiling the captured ORM statement for
PostgreSQL, and the advisory lock by a spy on ``_take_bootstrap_lock``.

Assertions read the rows back (``GraphRelease``, ``GraphReleaseAgent``,
``AgentDefinitionRevision.created_by``, the draft's candidate hashes and
``lock_version``) rather than trusting the returned outcome alone.
"""

from __future__ import annotations

import ast
from importlib import metadata
from pathlib import Path

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.dialects import postgresql

import src.services.graph_configuration_publication as publication_module
import src.services.graph_definition_manifest as manifest_module
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration import (
    CODE_SHIP_ACTOR,
    SYSTEM_ACTOR_PREFIX,
    BootstrapResult,
    DraftSaveConflict,
    DraftValidationIssue,
    EditableModelDraft,
    FieldDiff,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    PackagedUpdateStatus,
    PublicationConflict,
    PublishedRelease,
    RestoredRelease,
    ShipBlocked,
    ShipInvalid,
    ShipNothing,
    Shipped,
    adopt_packaged_update,
    definition_field_diffs,
    read_packaged_update_status,
    ship_packaged_graph_configuration,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    DefinitionContent,
    GraphV1Manifest,
    definition_content_hash,
    load_graph_v1_manifest,
)
from tests.unit import test_graph_release_publication as publication_tests
from tests.unit.test_graph_release_publication import (
    _artifacts,
    _NoEvidenceGate,
    _publish,
    _save_model,
    _save_prompt,
)
from tests.unit.test_graph_release_rollback import (
    current_lock,
    draft_content,
    install_release_clock,
)

#: #269's SQLite fixture: in-memory engine, foreign keys on, v1 bootstrapped.
factory = publication_tests.factory

# The code-ship actor and release note are written as literals in the assertions,
# on purpose: a wrong ``CODE_SHIP_ACTOR`` must not make them pass.
_BOOTSTRAP = "system:bootstrap"
_ADMIN = "admin@example.com"
_PUBLISHER = "publisher@example.com"
_APP_VERSION = "9.9.9"
_OTHERS = ("data_analyst", "build_reviewer", "fixer", "fix_reviewer", "deck_reviewer")
_NOT_ARCHITECT = tuple(key for key in GRAPH_V1_AGENT_KEYS if key != "architect")
_ISSUE = DraftValidationIssue("definitions.architect.model.endpoint_name", "endpoint_policy", "x")
_URL_ISSUE = DraftValidationIssue(
    "definitions.architect.candidate.model.endpoint_name",
    "endpoint_url_not_allowed",
    "Endpoint must be a Databricks endpoint name, not a URL.",
)
_UNSET = object()


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------


def _contents(manifest: GraphV1Manifest) -> dict[str, DefinitionContent]:
    return {definition.agent_key: definition for definition in manifest.definitions}


def _hashes(manifest: GraphV1Manifest) -> dict[str, str]:
    return {
        key: definition_content_hash(content) for key, content in _contents(manifest).items()
    }


def _payloads(contents) -> dict[str, object]:
    return {key: content.canonical_payload() for key, content in contents.items()}


def _v1_prompt(agent_key: str) -> str:
    return _contents(load_graph_v1_manifest())[agent_key].prompt_text


def _shipped_text(agent_key: str, tag: str) -> str:
    return _v1_prompt(agent_key) + f"\n\nShipped {tag}."


def _manifest(base: GraphV1Manifest | None = None, **prompts: str) -> GraphV1Manifest:
    """``base`` (default: the packaged manifest) with the named roles' prompt replaced.

    The models are frozen, so this copies with ``model_copy(update=...)`` and
    rebuilds the manifest, then checks that exactly the roles whose text really
    changed have a new hash.
    """
    base = load_graph_v1_manifest() if base is None else base
    assert set(prompts) <= set(GRAPH_V1_AGENT_KEYS), prompts
    manifest = GraphV1Manifest(
        manifest_version=1,
        definitions=tuple(
            definition.model_copy(update={"prompt_text": prompts[definition.agent_key]})
            if definition.agent_key in prompts
            else definition
            for definition in base.definitions
        ),
    )
    before, after = _hashes(base), _hashes(manifest)
    base_contents = _contents(base)
    assert tuple(key for key in GRAPH_V1_AGENT_KEYS if before[key] != after[key]) == tuple(
        key
        for key in GRAPH_V1_AGENT_KEYS
        if key in prompts and prompts[key] != base_contents[key].prompt_text
    )
    return manifest


def _with_architect_endpoint(manifest: GraphV1Manifest, endpoint_name: str) -> GraphV1Manifest:
    definitions = []
    for definition in manifest.definitions:
        if definition.agent_key == "architect":
            definition = definition.model_copy(
                update={
                    "model": definition.model.model_copy(
                        update={"endpoint_name": endpoint_name}
                    )
                }
            )
        definitions.append(definition)
    return GraphV1Manifest(manifest_version=1, definitions=tuple(definitions))


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


def ship(factory, manifest, *, app_version=_APP_VERSION, service=None):
    service = GraphConfiguration() if service is None else service
    return service.ship_packaged_manifest(
        factory, manifest=manifest, app_version=app_version
    )


def adopt(factory, manifest, *, lock=_UNSET, actor=_ADMIN, app_version=_APP_VERSION,
          service=None):
    service = GraphConfiguration() if service is None else service
    expected = current_lock(factory) if lock is _UNSET else lock
    with factory() as db:
        return service.adopt_packaged_manifest(
            db,
            manifest=manifest,
            app_version=app_version,
            actor=actor,
            expected_lock_version=expected,
        )


def status(factory, manifest, *, service=None) -> PackagedUpdateStatus:
    """The read-only status; every call also proves it wrote nothing."""
    service = GraphConfiguration() if service is None else service
    before = _artifacts(factory)
    with factory() as db:
        result = service.packaged_update_status(db, manifest=manifest)
    assert _artifacts(factory) == before
    return result


def hand_publish_prompt(factory, agent_key, *, prompt_text=None, actor=_PUBLISHER):
    """A person's edit: save the prompt, then publish it through ``publish_draft``."""
    _save_prompt(
        factory, agent_key, "\n\nHand edit.", lock=current_lock(factory), prompt_text=prompt_text
    )
    published = _publish(
        factory, lock=current_lock(factory), gate=_NoEvidenceGate(), note="Hand edit",
        actor=actor,
    )
    assert isinstance(published, PublishedRelease), published
    assert published.changed_agent_keys == (agent_key,)
    return published


def hand_publish_model(factory, agent_key, endpoint_name, *, actor=_PUBLISHER):
    _save_model(factory, agent_key, endpoint_name, lock=current_lock(factory))
    published = _publish(
        factory, lock=current_lock(factory), gate=_NoEvidenceGate(), note="Model edit",
        actor=actor,
    )
    assert isinstance(published, PublishedRelease), published
    assert published.changed_agent_keys == (agent_key,)
    return published


def restore_to(factory, version_number, *, actor=_ADMIN) -> RestoredRelease:
    with factory() as db:
        restored = GraphConfiguration().restore_release(
            db,
            version_number=version_number,
            expected_lock_version=current_lock(factory),
            release_note=f"Back to {version_number}",
            actor=actor,
        )
    assert isinstance(restored, RestoredRelease), restored
    return restored


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _releases(factory) -> list[GraphRelease]:
    with factory() as db:
        return list(db.scalars(select(GraphRelease).order_by(GraphRelease.version_number)))


def _active(factory) -> GraphRelease:
    with factory() as db:
        rows = list(db.scalars(select(GraphRelease).where(GraphRelease.effective_to.is_(None))))
    assert len(rows) == 1, rows
    return rows[0]


def _mapping(factory, release_id: int) -> dict[str, int]:
    with factory() as db:
        return dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == release_id)
            ).all()
        )


def _mapped_revisions(factory, release_id: int) -> dict[str, AgentDefinitionRevision]:
    ids = _mapping(factory, release_id)
    with factory() as db:
        return {key: db.get(AgentDefinitionRevision, rid) for key, rid in ids.items()}


def _revision(factory, revision_id: int) -> AgentDefinitionRevision:
    with factory() as db:
        return db.get(AgentDefinitionRevision, revision_id)


def _revisions_with(factory, agent_key: str, content_hash: str) -> list[AgentDefinitionRevision]:
    with factory() as db:
        return list(
            db.scalars(
                select(AgentDefinitionRevision).where(
                    AgentDefinitionRevision.agent_key == agent_key,
                    AgentDefinitionRevision.content_hash == content_hash,
                )
            )
        )


def _revision_count(factory) -> int:
    with factory() as db:
        return db.scalar(select(func.count()).select_from(AgentDefinitionRevision))


def _workbench(factory):
    with factory() as db:
        snapshot = GraphConfiguration().read_workbench(db)
        db.rollback()
    return snapshot, {n.agent_key: n for n in snapshot.nodes if n.execution_kind == "model"}


def _differing(factory, manifest) -> tuple[str, ...]:
    """The test's own view of which roles the manifest changes against the live graph."""
    _snapshot, nodes = _workbench(factory)
    packaged = _hashes(manifest)
    return tuple(
        key for key in GRAPH_V1_AGENT_KEYS if nodes[key].published.content_hash != packaged[key]
    )


def _new_revisions(before, after) -> set[tuple[str, str, str]]:
    """Revision rows added between two ``_artifacts`` reads, as (key, hash, creator).

    Every earlier row must still be present, unchanged.
    """
    old = set(before["revisions"])
    assert old <= set(after["revisions"])
    return {(row[1], row[2], row[3]) for row in after["revisions"] if row not in old}


def _assert_only_revisions_added(before, after, expected: set[tuple[str, str, str]]) -> None:
    for part in ("releases", "mappings", "draft", "draft_agents"):
        assert after[part] == before[part], part
    assert _new_revisions(before, after) == expected


def _pg(statement) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


class _MustNotRun:
    def validate(self, content):
        raise AssertionError("shipping must make no remote endpoint call")


# ---------------------------------------------------------------------------
# Exports and structure
# ---------------------------------------------------------------------------


def test_ship_actor_constants_and_exports():
    import src.services.graph_configuration as facade

    assert CODE_SHIP_ACTOR == "system:code-ship"
    assert SYSTEM_ACTOR_PREFIX == "system:"
    for name in (
        "CODE_SHIP_ACTOR",
        "SYSTEM_ACTOR_PREFIX",
        "PackagedBlockReason",
        "PackagedUpdateStatus",
        "ShipNothing",
        "ShipBlocked",
        "ShipInvalid",
        "Shipped",
        "ShipOutcome",
        "AdoptOutcome",
        "ship_packaged_graph_configuration",
    ):
        assert name in facade.__all__, name
        assert hasattr(facade, name), name


def test_facade_puts_shipping_first_then_rollback():
    from src.services.graph_configuration_shipping import _GraphConfigurationShipping

    from src.services.graph_configuration_rollback import _GraphConfigurationRollback

    assert GraphConfiguration.__bases__[0] is _GraphConfigurationShipping
    assert GraphConfiguration.__bases__[1] is _GraphConfigurationRollback


def test_shipping_module_imports_no_evidence_workbench_runtime_or_snapshot_at_module_scope():
    """Correction 29 and C5: lazy imports only, and the snapshot is never loaded here."""
    path = Path(__file__).resolve().parents[2] / "src/services/graph_configuration_shipping.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    }
    for forbidden in (
        "src.services.graph_release_evidence",
        "src.services.agent_test_workbench",
        "src.services.agent_runtime",
        "src.services.agent_definition_manifest_v1",
    ):
        assert forbidden not in imported, forbidden


# ---------------------------------------------------------------------------
# ship_packaged_manifest
# ---------------------------------------------------------------------------


def test_untouched_install_ships_the_packaged_manifest_as_the_next_release(
    factory, monkeypatch
):
    install_release_clock(monkeypatch, factory)
    v1 = _active(factory)
    v1_mapping = _mapping(factory, v1.id)
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    packaged, packaged_hashes = _contents(manifest), _hashes(manifest)
    lock = current_lock(factory)

    outcome = ship(factory, manifest)

    assert isinstance(outcome, Shipped), outcome
    published = outcome.published
    assert published.release.version_number == 2
    assert published.release.published_by == "system:code-ship"
    assert published.release.release_note == "Shipped with Tellr 9.9.9"
    assert published.release.restored_from_release_id is None
    assert published.release.previous_release_id == v1.id
    assert published.previous_release_id == v1.id
    assert published.changed_agent_keys == ("architect",)
    assert published.evidence == ()
    assert tuple(outcome.draft_effect) == GRAPH_V1_AGENT_KEYS
    assert dict(outcome.draft_effect) == {
        "architect": "reset",
        **{key: "unchanged" for key in _NOT_ARCHITECT},
    }

    # V2 is the one active release, written by the code-ship actor.
    releases = _releases(factory)
    assert [r.version_number for r in releases] == [1, 2]
    v1_row, v2 = releases
    assert v2.effective_to is None
    assert v1_row.effective_to is not None
    assert v1_row.effective_to == v2.effective_from
    assert v2.id == published.release.release_id == _active(factory).id
    assert (v2.published_by, v2.release_note, v2.restored_from_release_id) == (
        "system:code-ship",
        "Shipped with Tellr 9.9.9",
        None,
    )

    # Its seven mappings: the architect is a new system revision with the packaged
    # content; the six unchanged roles reuse their v1 revision ids.
    v2_mapping = _mapping(factory, v2.id)
    assert v2_mapping == {
        key: mapping.agent_definition_revision_id
        for key, mapping in published.mappings.items()
    }
    assert {key: v2_mapping[key] for key in _NOT_ARCHITECT} == {
        key: v1_mapping[key] for key in _NOT_ARCHITECT
    }
    assert v2_mapping["architect"] != v1_mapping["architect"]
    architect = _revision(factory, v2_mapping["architect"])
    assert architect.created_by == "system:code-ship"
    assert architect.content_hash == packaged_hashes["architect"]
    assert definition_content_from_row(architect).canonical_payload() == (
        packaged["architect"].canonical_payload()
    )
    assert {
        key: revision.content_hash for key, revision in _mapped_revisions(factory, v2.id).items()
    } == packaged_hashes
    assert _revision_count(factory) == len(GRAPH_V1_AGENT_KEYS) + 1

    # The draft is rebased onto v2 and every role is clean at the packaged content.
    snapshot, nodes = _workbench(factory)
    assert snapshot.draft.base_release_id == v2.id
    assert snapshot.draft.lock_version == lock + 1
    assert snapshot.draft.updated_by == "system:code-ship"
    assert {key: node.draft.candidate_hash for key, node in nodes.items()} == packaged_hashes
    assert all(node.changed is False for node in nodes.values())

    # The whole history still validates.
    assert GraphConfiguration().bootstrap_v1(factory) == BootstrapResult(False, v2.id, 2)


def test_matching_manifest_is_a_noop(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    v1 = _active(factory)
    before = _artifacts(factory)

    assert ship(factory, load_graph_v1_manifest()) == ShipNothing(
        release_id=v1.id, version_number=1
    )
    assert _artifacts(factory) == before

    # A rebuilt manifest with equal content is the same no-op.
    rebuilt = _manifest(architect=_v1_prompt("architect"))
    assert rebuilt is not load_graph_v1_manifest()
    assert ship(factory, rebuilt) == ShipNothing(release_id=v1.id, version_number=1)
    assert _artifacts(factory) == before


def test_second_ship_is_a_noop(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    manifest = _manifest(architect=_shipped_text("architect", "M"))

    first = ship(factory, manifest)
    assert isinstance(first, Shipped), first
    after_first = _artifacts(factory)

    second = ship(factory, manifest)

    assert second == ShipNothing(
        release_id=first.published.release.release_id, version_number=2
    )
    assert _artifacts(factory) == after_first
    assert [r.version_number for r in _releases(factory)] == [1, 2]


def test_hand_edited_prompt_blocks_ship_and_inserts_system_revisions(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    hand = hand_publish_prompt(factory, "builder")
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    packaged_hashes = _hashes(manifest)
    # The edited role's packaged content differs from the edit (no content fallback).
    assert packaged_hashes["builder"] != hand.mappings["builder"].content_hash
    assert _differing(factory, manifest) == ("architect", "builder")
    before = _artifacts(factory)
    lock = current_lock(factory)

    outcome = ship(factory, manifest)

    assert outcome == ShipBlocked(reason="hand_edited", hand_edited_agents=("builder",))
    after = _artifacts(factory)
    # No release, no mapping and no draft change; only the packaged architect is
    # inserted, as a system revision (the packaged builder is v1's, already there).
    _assert_only_revisions_added(
        before, after, {("architect", packaged_hashes["architect"], "system:code-ship")}
    )
    (inserted,) = _revisions_with(factory, "architect", packaged_hashes["architect"])
    assert inserted.created_by == "system:code-ship"
    assert definition_content_from_row(inserted).canonical_payload() == (
        _contents(manifest)["architect"].canonical_payload()
    )
    assert current_lock(factory) == lock
    assert _active(factory).id == hand.release.release_id
    assert _mapping(factory, hand.release.release_id)["builder"] == (
        hand.mappings["builder"].agent_definition_revision_id
    )


def test_model_only_edit_blocks_ship(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    hand = hand_publish_model(factory, "builder", "system.ai.claude-opus-5-5")
    builder_revision = _revision(factory, hand.mappings["builder"].agent_definition_revision_id)
    assert builder_revision.prompt_text == _v1_prompt("builder")  # the model alone changed
    assert builder_revision.created_by == _PUBLISHER
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    assert _hashes(manifest)["builder"] != hand.mappings["builder"].content_hash
    before = _artifacts(factory)

    outcome = ship(factory, manifest)

    assert outcome == ShipBlocked(reason="hand_edited", hand_edited_agents=("builder",))
    _assert_only_revisions_added(
        before,
        _artifacts(factory),
        {("architect", _hashes(manifest)["architect"], "system:code-ship")},
    )
    assert _active(factory).id == hand.release.release_id


def test_rollback_blocks_reshipping(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    v1 = _active(factory)
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    shipped = ship(factory, manifest)
    assert isinstance(shipped, Shipped), shipped
    restored = restore_to(factory, 1)
    v3_id = restored.published.release.release_id
    before = _artifacts(factory)

    outcome = ship(factory, manifest)

    assert outcome == ShipBlocked(reason="rollback", hand_edited_agents=())
    # M's revisions already exist, so nothing at all is written.
    assert _artifacts(factory) == before
    active = _active(factory)
    assert (active.id, active.version_number, active.restored_from_release_id) == (
        v3_id,
        3,
        v1.id,
    )
    assert _mapping(factory, v3_id) == _mapping(factory, v1.id)
    # Matching comes first: a rollback to exactly the packaged content is nothing.
    assert ship(factory, load_graph_v1_manifest()) == ShipNothing(
        release_id=v3_id, version_number=3
    )
    assert _artifacts(factory) == before

    # A newer packaged architect is still inserted as a system revision, unpublished.
    newer = _manifest(architect=_shipped_text("architect", "M-next"))
    assert ship(factory, newer) == ShipBlocked(reason="rollback", hand_edited_agents=())
    _assert_only_revisions_added(
        before,
        _artifacts(factory),
        {("architect", _hashes(newer)["architect"], "system:code-ship")},
    )
    assert _active(factory).id == v3_id


def test_pending_draft_edit_is_kept_across_a_ship(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    saved = _save_prompt(factory, "builder", "\n\nPending.", lock=current_lock(factory))
    pending_hash = saved.definition.candidate_hash
    pending_text = saved.definition.content.prompt_text
    lock = current_lock(factory)
    manifest = _manifest(
        architect=_shipped_text("architect", "M"), builder=_shipped_text("builder", "M")
    )
    packaged_hashes = _hashes(manifest)
    assert packaged_hashes["builder"] != pending_hash

    outcome = ship(factory, manifest)

    assert isinstance(outcome, Shipped), outcome
    assert outcome.draft_effect["builder"] == "kept"
    assert outcome.draft_effect["architect"] == "reset"
    assert outcome.draft_effect["fixer"] == "unchanged"
    assert dict(outcome.draft_effect) == {
        "architect": "reset",
        "builder": "kept",
        **{key: "unchanged" for key in _OTHERS},
    }
    assert outcome.published.changed_agent_keys == ("architect", "builder")

    snapshot, nodes = _workbench(factory)
    # The release is the packaged manifest, never the pending edit.
    assert {key: node.published.content_hash for key, node in nodes.items()} == packaged_hashes
    # The builder draft still holds the edit, now pending against the shipped builder.
    assert nodes["builder"].draft.candidate_hash == pending_hash
    assert nodes["builder"].draft.content.prompt_text == pending_text
    assert nodes["builder"].changed is True
    # The clean architect was reset to the packaged content.
    assert nodes["architect"].draft.candidate_hash == packaged_hashes["architect"]
    assert nodes["architect"].changed is False
    for key in _OTHERS:
        assert nodes[key].draft.candidate_hash == packaged_hashes[key]
        assert nodes[key].changed is False
    assert snapshot.draft.base_release_id == outcome.published.release.release_id
    assert snapshot.draft.lock_version == lock + 1

    # The editor's next save on the pre-ship lock is a normal stale conflict.
    content = draft_content(factory, "builder")
    with factory() as db:
        stale = GraphConfiguration().save_editable_model_draft(
            db,
            agent_key="builder",
            expected_lock_version=lock,
            actor="editor@example.com",
            candidate=EditableModelDraft(
                prompt_text=content.prompt_text + " more",
                endpoint_name=content.model.endpoint_name,
                temperature=float(content.model.temperature),
                max_tokens=content.model.max_tokens,
                top_p=float(content.model.top_p),
            ),
        )
    assert isinstance(stale, DraftSaveConflict), stale
    assert _workbench(factory)[1]["builder"].draft.candidate_hash == pending_hash


def test_invalid_packaged_content_writes_nothing(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    seen: list[dict[str, DefinitionContent]] = []

    def _issues(self, contents):
        seen.append(dict(contents))
        return [_ISSUE]

    monkeypatch.setattr(GraphConfiguration, "_candidate_contents_issues", _issues)
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    before = _artifacts(factory)

    outcome = ship(factory, manifest)

    assert outcome == ShipInvalid(issues=(_ISSUE,))
    assert _artifacts(factory) == before
    # The validators were given the packaged definitions, all seven.
    assert seen
    for contents in seen:
        assert set(contents) == set(GRAPH_V1_AGENT_KEYS)
        assert _payloads(contents) == _payloads(_contents(manifest))


def test_invalid_packaged_content_on_a_hand_edited_install_inserts_nothing(
    factory, monkeypatch
):
    """Controller ruling 5: validation precedes the block check, so an invalid
    manifest on a touched install inserts no revision either."""
    install_release_clock(monkeypatch, factory)
    hand = hand_publish_prompt(factory, "builder")
    monkeypatch.setattr(
        GraphConfiguration, "_candidate_contents_issues", lambda self, contents: [_ISSUE]
    )
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    packaged_architect = _hashes(manifest)["architect"]
    assert _differing(factory, manifest) == ("architect", "builder")
    before = _artifacts(factory)

    outcome = ship(factory, manifest)

    assert outcome == ShipInvalid(issues=(_ISSUE,))
    assert _artifacts(factory) == before
    assert _revisions_with(factory, "architect", packaged_architect) == []
    assert _active(factory).id == hand.release.release_id


def test_a_url_endpoint_in_the_packaged_manifest_is_invalid_everywhere(factory, monkeypatch):
    """The real local validators (#266's endpoint-name policy), with no monkeypatch."""
    install_release_clock(monkeypatch, factory)
    manifest = _with_architect_endpoint(
        _manifest(architect=_shipped_text("architect", "M")), "https://x/y"
    )
    before = _artifacts(factory)

    assert ship(factory, manifest) == ShipInvalid(issues=(_URL_ISSUE,))
    assert _artifacts(factory) == before

    reported = status(factory, manifest)
    assert reported.available is True
    assert reported.blocked_reason == "invalid"
    assert reported.validation_issues == (_URL_ISSUE,)

    assert adopt(factory, manifest) == ShipInvalid(issues=(_URL_ISSUE,))
    assert _artifacts(factory) == before


@pytest.mark.parametrize("scenario", ["shipped", "blocked", "nothing"])
def test_ship_takes_the_bootstrap_lock_then_l0_exclusive(factory, monkeypatch, scenario):
    """Advisory lock (a spy: SQLite skips it), then L0 ``FOR UPDATE`` as the first
    statement, then L1, all in one transaction and before any write."""
    install_release_clock(monkeypatch, factory)
    if scenario == "blocked":
        hand_publish_prompt(factory, "builder")
    manifest = (
        load_graph_v1_manifest()
        if scenario == "nothing"
        else _manifest(architect=_shipped_text("architect", "M"))
    )
    engine = factory.kw["bind"]
    timeline: list[str] = []
    cursor_sql: list[str] = []
    begins: list[object] = []
    bootstrap_calls: list[tuple[object, bool]] = []
    parent_calls: list[tuple[object, bool]] = []
    real_bootstrap_lock = GraphConfiguration._take_bootstrap_lock
    real_parents = GraphConfiguration._lock_current_parents

    def _spy_bootstrap_lock(self, session):
        timeline.append("bootstrap_lock")
        bootstrap_calls.append((session, session.in_transaction()))
        return real_bootstrap_lock(self, session)

    def _spy_parents(self, session, *, exclusive):
        parent_calls.append((session, exclusive))
        return real_parents(self, session, exclusive=exclusive)

    def _orm(state):
        timeline.append(_pg(state.statement))

    def _cursor(conn, cursor, statement, parameters, context, executemany):
        cursor_sql.append(" ".join(statement.split()).upper())

    def _begin(conn):
        begins.append(conn)

    monkeypatch.setattr(GraphConfiguration, "_take_bootstrap_lock", _spy_bootstrap_lock)
    monkeypatch.setattr(GraphConfiguration, "_lock_current_parents", _spy_parents)
    event.listen(factory, "do_orm_execute", _orm)
    event.listen(engine, "before_cursor_execute", _cursor)
    event.listen(engine, "begin", _begin)
    try:
        outcome = ship(factory, manifest)
    finally:
        event.remove(factory, "do_orm_execute", _orm)
        event.remove(engine, "before_cursor_execute", _cursor)
        event.remove(engine, "begin", _begin)

    expected = {"shipped": Shipped, "blocked": ShipBlocked, "nothing": ShipNothing}[scenario]
    assert isinstance(outcome, expected), outcome

    # The advisory lock comes before every statement, once, inside the transaction.
    assert timeline[0] == "bootstrap_lock"
    assert timeline.count("bootstrap_lock") == 1
    ((lock_session, in_transaction),) = bootstrap_calls
    assert in_transaction is True
    # Then L0 exclusive in the same session, then L1; nothing else locks.
    assert parent_calls == [(lock_session, True)]
    statements = timeline[1:]
    assert statements[0].endswith("FOR UPDATE OF graph_release, graph_draft")
    assert "FROM graph_draft_agent" in statements[1]
    assert statements[1].endswith("ORDER BY graph_draft_agent.agent_key FOR UPDATE")
    assert [i for i, sql in enumerate(statements) if " FOR " in sql] == [0, 1]
    # One transaction.
    assert len(begins) == 1
    # No write before both locks.
    assert "FROM GRAPH_RELEASE JOIN GRAPH_DRAFT" in cursor_sql[0]
    assert "FROM GRAPH_DRAFT_AGENT" in cursor_sql[1]
    assert cursor_sql[1].endswith("ORDER BY GRAPH_DRAFT_AGENT.AGENT_KEY")
    writes = [
        i for i, sql in enumerate(cursor_sql) if sql.startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    if scenario == "nothing":
        assert writes == []
    else:
        assert writes and writes[0] > 1


def test_ship_and_adopt_write_through_the_one_publication_core(factory, monkeypatch):
    """No copy of ``_commit_locked_publication``: one call each, with the pinned kwargs."""
    install_release_clock(monkeypatch, factory)
    core = publication_module._GraphConfigurationPublication._commit_locked_publication
    assert GraphConfiguration._commit_locked_publication is core
    calls: list[dict[str, object]] = []

    def _spy(self, session, **kwargs):
        calls.append(kwargs)
        return core(self, session, **kwargs)

    monkeypatch.setattr(
        publication_module._GraphConfigurationPublication, "_commit_locked_publication", _spy
    )
    manifest = _manifest(architect=_shipped_text("architect", "M"))

    assert isinstance(ship(factory, manifest), Shipped)

    (call,) = calls
    assert call["evidence"] == ()
    assert call["actor"] == "system:code-ship"
    assert call["release_note"] == "Shipped with Tellr 9.9.9"
    assert call["restored_from_release_id"] is None
    assert _payloads(call["contents"]) == _payloads(_contents(manifest))

    hand_publish_prompt(factory, "builder")
    calls.clear()
    second = _manifest(manifest, deck_reviewer=_shipped_text("deck_reviewer", "M2"))

    assert isinstance(adopt(factory, second), Shipped)

    (call,) = calls
    assert call["evidence"] == ()
    assert call["actor"] == _ADMIN
    assert call["restored_from_release_id"] is None
    assert _payloads(call["contents"]) == _payloads(_contents(second))


def test_a_wrong_draft_effect_aborts_the_whole_ship(factory, monkeypatch):
    """``_verify_rebased_draft`` runs inside the transaction: a rebase that does not
    match its effect writes nothing, not even the pre-materialised revisions."""
    install_release_clock(monkeypatch, factory)
    real = GraphConfiguration._draft_effect

    def _wrong_effect(*args, **kwargs):
        effect = dict(real(*args, **kwargs))
        effect["architect"] = "unchanged"  # it needs a reset
        return effect

    monkeypatch.setattr(GraphConfiguration, "_draft_effect", staticmethod(_wrong_effect))
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    before = _artifacts(factory)

    with pytest.raises(GraphConfigurationIntegrityError, match="rebased draft"):
        ship(factory, manifest)

    assert _artifacts(factory) == before


def test_shipping_makes_no_remote_endpoint_call(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    service = GraphConfiguration(remote_endpoint_validator=_MustNotRun())
    manifest = _manifest(architect=_shipped_text("architect", "M"))

    assert status(factory, manifest, service=service).available is True
    assert isinstance(ship(factory, manifest, service=service), Shipped)
    second = _manifest(manifest, deck_reviewer=_shipped_text("deck_reviewer", "M2"))
    assert isinstance(adopt(factory, second, service=service), Shipped)


# ---------------------------------------------------------------------------
# adopt_packaged_manifest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shipped_first", [False, True], ids=["adopt-writes", "ship-wrote"])
def test_adopt_publishes_shipped_content_under_the_admin_with_system_revisions(
    factory, monkeypatch, shipped_first
):
    """``adopt-writes``: no startup ship ran, so adopt must materialise the shipped
    revisions as ``system:code-ship`` itself, not as the admin."""
    install_release_clock(monkeypatch, factory)
    v1_mapping = _mapping(factory, _active(factory).id)
    hand = hand_publish_prompt(factory, "builder")
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    packaged_hashes = _hashes(manifest)
    if shipped_first:
        assert ship(factory, manifest) == ShipBlocked(
            reason="hand_edited", hand_edited_agents=("builder",)
        )
    else:
        assert _revisions_with(factory, "architect", packaged_hashes["architect"]) == []
    lock = current_lock(factory)

    outcome = adopt(factory, manifest, lock=lock)

    assert isinstance(outcome, Shipped), outcome
    release = outcome.published.release
    assert release.version_number == 3
    assert release.published_by == _ADMIN
    assert release.release_note == "Adopted shipped version (Tellr 9.9.9)"
    assert release.restored_from_release_id is None
    assert release.previous_release_id == hand.release.release_id
    assert outcome.published.changed_agent_keys == ("architect", "builder")
    assert dict(outcome.draft_effect) == {
        "architect": "reset",
        "builder": "reset",
        **{key: "unchanged" for key in _OTHERS},
    }

    active = _active(factory)
    assert (active.id, active.version_number, active.published_by, active.release_note) == (
        release.release_id,
        3,
        _ADMIN,
        "Adopted shipped version (Tellr 9.9.9)",
    )
    revisions = _mapped_revisions(factory, active.id)
    assert {key: revision.content_hash for key, revision in revisions.items()} == (
        packaged_hashes
    )
    # The differing roles: the architect's shipped revision is the code's...
    assert revisions["architect"].created_by == "system:code-ship"
    assert revisions["architect"].id not in v1_mapping.values()
    # ...and the builder's packaged content is v1's own system revision, reused.
    assert revisions["builder"].id == v1_mapping["builder"]
    assert revisions["builder"].created_by == _BOOTSTRAP
    assert {key: revisions[key].id for key in _OTHERS} == {key: v1_mapping[key] for key in _OTHERS}
    assert all(r.created_by.startswith("system:") for r in revisions.values())
    # Adopt authored no revision at all.
    assert _ADMIN not in {row[3] for row in _artifacts(factory)["revisions"]}
    assert len(_revisions_with(factory, "architect", packaged_hashes["architect"])) == 1

    # The draft is rebased and clean at the packaged content, the architect reset.
    snapshot, nodes = _workbench(factory)
    assert snapshot.draft.base_release_id == active.id
    assert snapshot.draft.lock_version == lock + 1
    assert snapshot.draft.updated_by == _ADMIN
    assert nodes["architect"].draft.candidate_hash == packaged_hashes["architect"]
    assert {key: node.draft.candidate_hash for key, node in nodes.items()} == packaged_hashes
    assert all(node.changed is False for node in nodes.values())
    assert GraphConfiguration().bootstrap_v1(factory) == BootstrapResult(False, active.id, 3)


def test_adopt_makes_the_install_untouched_again(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    v1_mapping = _mapping(factory, _active(factory).id)
    hand_publish_prompt(factory, "builder")
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    assert isinstance(adopt(factory, manifest), Shipped)
    assert status(factory, manifest).available is False

    second = _manifest(manifest, deck_reviewer=_shipped_text("deck_reviewer", "M2"))
    reported = status(factory, second)
    assert (reported.available, reported.blocked_reason, reported.hand_edited_agents) == (
        True,
        None,
        (),
    )

    outcome = ship(factory, second)

    assert isinstance(outcome, Shipped), outcome
    assert outcome.published.release.published_by == "system:code-ship"
    assert outcome.published.release.version_number == 4
    assert outcome.published.changed_agent_keys == ("deck_reviewer",)
    active = _active(factory)
    assert (active.version_number, active.published_by) == (4, "system:code-ship")
    revisions = _mapped_revisions(factory, active.id)
    assert {key: revision.content_hash for key, revision in revisions.items()} == (
        _hashes(second)
    )
    assert revisions["deck_reviewer"].created_by == "system:code-ship"
    # The builder edit was replaced by the adopt: all seven packaged definitions.
    assert revisions["builder"].id == v1_mapping["builder"]


def test_adopt_with_a_stale_lock_is_a_conflict_and_writes_nothing(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    hand = hand_publish_prompt(factory, "builder")
    snapshot, nodes = _workbench(factory)
    lock = snapshot.draft.lock_version
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    matching = _manifest(builder=nodes["builder"].published.content.prompt_text)
    assert _differing(factory, matching) == ()
    before = _artifacts(factory)

    def _conflict(expected_lock_version):
        return PublicationConflict(
            expected_lock_version=expected_lock_version,
            current_lock_version=lock,
            active_release_id=hand.release.release_id,
            active_version_number=2,
            draft=snapshot.draft,
        )

    assert adopt(factory, manifest, lock=lock - 1) == _conflict(lock - 1)
    assert adopt(factory, manifest, lock=lock + 1) == _conflict(lock + 1)
    # The stale check precedes nothing-to-adopt.
    assert adopt(factory, matching, lock=lock - 1) == _conflict(lock - 1)
    # No revision was materialised, and nothing else moved.
    assert _artifacts(factory) == before


def test_adopt_of_a_matching_manifest_is_nothing_and_writes_nothing(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    v1 = _active(factory)
    before = _artifacts(factory)

    assert adopt(factory, load_graph_v1_manifest(), lock=0) == ShipNothing(
        release_id=v1.id, version_number=1
    )
    assert _artifacts(factory) == before


def test_adopt_is_not_blocked_by_a_rollback(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    shipped = ship(factory, manifest)
    assert isinstance(shipped, Shipped), shipped
    restore_to(factory, 1)
    assert status(factory, manifest).blocked_reason == "rollback"

    adopted = adopt(factory, manifest)

    assert isinstance(adopted, Shipped), adopted
    release = adopted.published.release
    assert (release.version_number, release.published_by, release.restored_from_release_id) == (
        4,
        _ADMIN,
        None,
    )
    assert _mapping(factory, release.release_id) == _mapping(
        factory, shipped.published.release.release_id
    )
    # No longer a rollback, so the next packaged version ships on its own.
    second = _manifest(manifest, deck_reviewer=_shipped_text("deck_reviewer", "M2"))
    final = ship(factory, second)
    assert isinstance(final, Shipped), final
    assert (final.published.release.version_number, final.published.release.published_by) == (
        5,
        "system:code-ship",
    )


def test_adopt_takes_l0_exclusive_then_l1_before_any_write(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    hand_publish_prompt(factory, "builder")
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    lock = current_lock(factory)
    engine = factory.kw["bind"]
    statements: list[str] = []
    cursor_sql: list[str] = []

    def _cursor(conn, cursor, statement, parameters, context, executemany):
        cursor_sql.append(" ".join(statement.split()).upper())

    event.listen(engine, "before_cursor_execute", _cursor)
    try:
        with factory() as db:
            event.listen(
                db, "do_orm_execute", lambda state: statements.append(_pg(state.statement))
            )
            cursor_sql.clear()
            outcome = GraphConfiguration().adopt_packaged_manifest(
                db,
                manifest=manifest,
                app_version=_APP_VERSION,
                actor=_ADMIN,
                expected_lock_version=lock,
            )
    finally:
        event.remove(engine, "before_cursor_execute", _cursor)

    assert isinstance(outcome, Shipped), outcome
    assert statements[0].endswith("FOR UPDATE OF graph_release, graph_draft")
    assert "FROM graph_draft_agent" in statements[1]
    assert statements[1].endswith("ORDER BY graph_draft_agent.agent_key FOR UPDATE")
    assert [i for i, sql in enumerate(statements) if " FOR " in sql] == [0, 1]
    assert "FROM GRAPH_RELEASE JOIN GRAPH_DRAFT" in cursor_sql[0]
    assert "FROM GRAPH_DRAFT_AGENT" in cursor_sql[1]
    writes = [
        i for i, sql in enumerate(cursor_sql) if sql.startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes and writes[0] > 1


# ---------------------------------------------------------------------------
# The content fallback
# ---------------------------------------------------------------------------


def test_hand_applied_shipped_text_counts_as_untouched_while_it_matches(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    manifest = _manifest(architect=_shipped_text("architect", "M"))

    # An admin publishes exactly M's architect text before M ships.
    hand = hand_publish_prompt(
        factory, "architect", prompt_text=_shipped_text("architect", "M"), actor=_ADMIN
    )
    admin_revision_id = hand.mappings["architect"].agent_definition_revision_id
    assert _revision(factory, admin_revision_id).created_by == _ADMIN
    assert hand.mappings["architect"].content_hash == _hashes(manifest)["architect"]
    v2_id = hand.release.release_id

    # 1. M matches the live graph by hash: nothing to ship.
    before = _artifacts(factory)
    assert ship(factory, manifest) == ShipNothing(release_id=v2_id, version_number=2)
    assert _artifacts(factory) == before

    # 2. M2 changes only the deck_reviewer.  The admin's architect equals the
    #    packaged one, so it is not a hand edit and M2 ships.
    second = _manifest(manifest, deck_reviewer=_shipped_text("deck_reviewer", "M2"))
    reported = status(factory, second)
    assert (reported.blocked_reason, reported.hand_edited_agents) == (None, ())
    shipped = ship(factory, second)
    assert isinstance(shipped, Shipped), shipped
    assert shipped.published.release.published_by == "system:code-ship"
    assert shipped.published.changed_agent_keys == ("deck_reviewer",)
    v3_id = shipped.published.release.release_id
    assert _mapping(factory, v3_id)["architect"] == admin_revision_id
    assert _revision(factory, admin_revision_id).created_by == _ADMIN

    # 3. M3 changes the architect's text: the live admin revision is now a hand edit.
    third = _manifest(second, architect=_shipped_text("architect", "M3"))
    before = _artifacts(factory)
    assert ship(factory, third) == ShipBlocked(
        reason="hand_edited", hand_edited_agents=("architect",)
    )
    _assert_only_revisions_added(
        before,
        _artifacts(factory),
        {("architect", _hashes(third)["architect"], "system:code-ship")},
    )
    assert _active(factory).id == v3_id
    assert _mapping(factory, v3_id)["architect"] == admin_revision_id

    # 4. One adopt clears it, and the next packaged version ships on its own.
    adopted = adopt(factory, third)
    assert isinstance(adopted, Shipped), adopted
    assert adopted.published.release.published_by == _ADMIN
    assert _mapped_revisions(factory, adopted.published.release.release_id)[
        "architect"
    ].created_by == "system:code-ship"
    fourth = _manifest(third, deck_reviewer=_shipped_text("deck_reviewer", "M4"))
    final = ship(factory, fourth)
    assert isinstance(final, Shipped), final
    assert final.published.release.published_by == "system:code-ship"
    assert final.published.release.version_number == 5
    assert final.published.changed_agent_keys == ("deck_reviewer",)


# ---------------------------------------------------------------------------
# packaged_update_status
# ---------------------------------------------------------------------------


def _assert_status(factory, reported, manifest, *, available, differing, blocked,
                   hand_edited, issues=_UNSET) -> None:
    snapshot, nodes = _workbench(factory)
    assert isinstance(reported, PackagedUpdateStatus)
    assert _differing(factory, manifest) == differing  # the scenario is what we think
    assert reported.available is available
    assert reported.differing_agents == differing
    assert reported.blocked_reason == blocked
    assert reported.hand_edited_agents == hand_edited
    if issues is not _UNSET:
        assert reported.validation_issues == issues
    assert reported.active_release == snapshot.active_release
    assert reported.lock_version == snapshot.draft.lock_version
    packaged = _contents(manifest)
    assert set(reported.field_diffs) == set(differing)
    assert {key: tuple(diffs) for key, diffs in reported.field_diffs.items()} == {
        key: definition_field_diffs(nodes[key].published.content, packaged[key])
        for key in differing
    }


def test_status_reports_reason_agents_and_diffs(factory, monkeypatch):
    install_release_clock(monkeypatch, factory)
    manifest = _manifest(architect=_shipped_text("architect", "M"))

    # Nothing available: the packaged manifest is the live graph.
    _assert_status(
        factory, status(factory, load_graph_v1_manifest()), load_graph_v1_manifest(),
        available=False, differing=(), blocked=None, hand_edited=(), issues=(),
    )

    # Available and untouched: no reason; diffs are active -> packaged per role.
    both = _manifest(manifest, deck_reviewer=_shipped_text("deck_reviewer", "M"))
    reported = status(factory, both)
    _assert_status(
        factory, reported, both,
        available=True, differing=("architect", "deck_reviewer"), blocked=None,
        hand_edited=(), issues=(),
    )
    assert reported.field_diffs["architect"] == (
        FieldDiff("prompt_text", _v1_prompt("architect"), _shipped_text("architect", "M")),
    )

    # A hand edit.
    hand = hand_publish_prompt(factory, "builder")
    _assert_status(
        factory, status(factory, manifest), manifest,
        available=True, differing=("architect", "builder"), blocked="hand_edited",
        hand_edited=("builder",), issues=(),
    )

    # A rollback to v1, whose revisions are all system-created.
    v1 = _releases(factory)[0]
    restore_to(factory, 1)
    reported = status(factory, manifest)
    _assert_status(
        factory, reported, manifest,
        available=True, differing=("architect",), blocked="rollback", hand_edited=(),
        issues=(),
    )
    assert reported.active_release.restored_from_release_id == v1.id

    # A rollback to the hand-edited v2: "hand_edited" outranks "rollback".
    restore_to(factory, 2)
    reported = status(factory, manifest)
    _assert_status(
        factory, reported, manifest,
        available=True, differing=("architect", "builder"), blocked="hand_edited",
        hand_edited=("builder",), issues=(),
    )
    assert reported.active_release.restored_from_release_id == hand.release.release_id

    # Validation issues: "invalid" outranks both.
    monkeypatch.setattr(
        GraphConfiguration, "_candidate_contents_issues", lambda self, contents: [_ISSUE]
    )
    _assert_status(
        factory, status(factory, manifest), manifest,
        available=True, differing=("architect", "builder"), blocked="invalid",
        hand_edited=("builder",), issues=(_ISSUE,),
    )

    # Nothing available: no reason at all, though issues and a rollback are present
    # (the builder's admin revision equals this manifest's builder, so not a hand edit).
    matching = _manifest(builder=_workbench(factory)[1]["builder"].published.content.prompt_text)
    _assert_status(
        factory, status(factory, matching), matching,
        available=False, differing=(), blocked=None, hand_edited=(),
    )


@pytest.mark.parametrize(
    ("creator", "hand_edited"),
    [
        pytest.param("system:migration", (), id="system-prefix"),
        pytest.param("system-bot@example.com", ("builder",), id="no-colon"),
        pytest.param(_PUBLISHER, ("builder",), id="person"),
    ],
)
def test_only_system_prefixed_creators_count_as_untouched(
    factory, monkeypatch, creator, hand_edited
):
    install_release_clock(monkeypatch, factory)
    hand = hand_publish_prompt(factory, "builder")
    with factory.begin() as db:  # SQLite has no revision mutation guard
        db.execute(
            update(AgentDefinitionRevision)
            .where(
                AgentDefinitionRevision.id
                == hand.mappings["builder"].agent_definition_revision_id
            )
            .values(created_by=creator)
        )
    manifest = _manifest(architect=_shipped_text("architect", "M"))

    reported = status(factory, manifest)
    assert reported.hand_edited_agents == hand_edited
    assert reported.blocked_reason == ("hand_edited" if hand_edited else None)

    outcome = ship(factory, manifest)
    if hand_edited:
        assert outcome == ShipBlocked(reason="hand_edited", hand_edited_agents=hand_edited)
        assert _active(factory).id == hand.release.release_id
    else:
        assert isinstance(outcome, Shipped), outcome
        assert outcome.published.changed_agent_keys == ("architect", "builder")


def test_status_takes_only_the_shared_parent_lock_and_writes_nothing(factory, monkeypatch):
    """From a hand-edited state, where a ship would insert revisions: status does not."""
    install_release_clock(monkeypatch, factory)
    hand_publish_prompt(factory, "builder")
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    engine = factory.kw["bind"]
    exclusive_calls: list[bool] = []
    statements: list[str] = []
    cursor_sql: list[str] = []
    real_parents = GraphConfiguration._lock_current_parents

    def _spy_parents(self, session, *, exclusive):
        exclusive_calls.append(exclusive)
        return real_parents(self, session, exclusive=exclusive)

    def _cursor(conn, cursor, statement, parameters, context, executemany):
        cursor_sql.append(" ".join(statement.split()).upper())

    monkeypatch.setattr(GraphConfiguration, "_lock_current_parents", _spy_parents)
    before = _artifacts(factory)
    event.listen(engine, "before_cursor_execute", _cursor)
    try:
        with factory() as db:
            event.listen(
                db, "do_orm_execute", lambda state: statements.append(_pg(state.statement))
            )
            reported = GraphConfiguration().packaged_update_status(db, manifest=manifest)
    finally:
        event.remove(engine, "before_cursor_execute", _cursor)

    assert reported.blocked_reason == "hand_edited"
    assert exclusive_calls == [False]
    assert statements[0].endswith("FOR SHARE OF graph_release, graph_draft")
    assert [sql for sql in statements if " FOR " in sql and "FOR SHARE" not in sql] == []
    assert [sql for sql in cursor_sql if sql.startswith(("INSERT", "UPDATE", "DELETE"))] == []
    assert _artifacts(factory) == before


# ---------------------------------------------------------------------------
# The startup wrapper
# ---------------------------------------------------------------------------


def _spy_ship(monkeypatch) -> list[tuple[object, GraphV1Manifest, str]]:
    calls: list[tuple[object, GraphV1Manifest, str]] = []
    real = GraphConfiguration.ship_packaged_manifest

    def _spy(self, session_factory, *, manifest, app_version):
        calls.append((session_factory, manifest, app_version))
        return real(self, session_factory, manifest=manifest, app_version=app_version)

    monkeypatch.setattr(GraphConfiguration, "ship_packaged_manifest", _spy)
    return calls


def test_startup_wrapper_ships_the_packaged_manifest(factory, monkeypatch):
    v1 = _active(factory)
    calls = _spy_ship(monkeypatch)
    before = _artifacts(factory)

    outcome = ship_packaged_graph_configuration(factory)

    assert outcome == ShipNothing(release_id=v1.id, version_number=1)
    ((session_factory, manifest, _app_version),) = calls
    assert session_factory is factory
    assert manifest == load_graph_v1_manifest()
    assert _artifacts(factory) == before


def test_startup_wrapper_names_the_app_version(factory, monkeypatch):
    """Controller ruling 1: the installed ``databricks-tellr-app`` version, else
    ``"unknown"`` (never the stale ``src.__version__``)."""
    try:
        expected = metadata.version("databricks-tellr-app")
    except metadata.PackageNotFoundError:
        expected = "unknown"
    calls = _spy_ship(monkeypatch)

    ship_packaged_graph_configuration(factory)

    ((_session_factory, _manifest_arg, app_version),) = calls
    assert app_version == expected


# ---------------------------------------------------------------------------
# The admin helpers (the routes' only way to the packaged manifest)
# ---------------------------------------------------------------------------


def _installed_version() -> str:
    try:
        return metadata.version("databricks-tellr-app")
    except metadata.PackageNotFoundError:
        return "unknown"


def test_status_helper_reports_against_the_loaded_manifest(factory, monkeypatch):
    import src.services.graph_configuration as facade

    assert "read_packaged_update_status" in facade.__all__
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    monkeypatch.setattr(manifest_module, "load_graph_v1_manifest", lambda: manifest)
    before = _artifacts(factory)

    with factory() as db:
        reported = read_packaged_update_status(db)

    # Only the patched manifest differs from the bootstrapped v1.
    assert (reported.available, reported.differing_agents, reported.blocked_reason) == (
        True,
        ("architect",),
        None,
    )
    assert reported.field_diffs["architect"] == (
        FieldDiff("prompt_text", _v1_prompt("architect"), _shipped_text("architect", "M")),
    )
    assert _artifacts(factory) == before


def test_adopt_helper_publishes_the_loaded_manifest(factory, monkeypatch):
    import src.services.graph_configuration as facade

    assert "adopt_packaged_update" in facade.__all__
    install_release_clock(monkeypatch, factory)
    hand_publish_prompt(factory, "builder")
    manifest = _manifest(architect=_shipped_text("architect", "M"))
    monkeypatch.setattr(manifest_module, "load_graph_v1_manifest", lambda: manifest)

    with factory() as db:
        outcome = adopt_packaged_update(
            db, actor=_ADMIN, expected_lock_version=current_lock(factory)
        )

    assert isinstance(outcome, Shipped), outcome
    release = outcome.published.release
    assert (release.published_by, release.release_note) == (
        _ADMIN,
        f"Adopted shipped version (Tellr {_installed_version()})",
    )
    revisions = _mapped_revisions(factory, release.release_id)
    assert {key: revision.content_hash for key, revision in revisions.items()} == (
        _hashes(manifest)
    )
    assert revisions["architect"].created_by == "system:code-ship"


def test_startup_wrapper_uses_the_installed_databricks_tellr_app_version(monkeypatch):
    import src.services.graph_configuration as facade

    def fake_version(name):
        if name == "databricks-tellr-app":
            return "7.7.7"
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(facade.metadata, "version", fake_version)
    captured = {}

    def fake_ship(self, session_factory, *, manifest, app_version):
        captured["app_version"] = app_version
        return "outcome"

    monkeypatch.setattr(GraphConfiguration, "ship_packaged_manifest", fake_ship)

    result = facade.ship_packaged_graph_configuration(object())

    assert result == "outcome"
    assert captured["app_version"] == "7.7.7"
