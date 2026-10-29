"""Prompt shipping: the packaged manifest as the next Graph Release.

Code-shipped prompts reach an install as a whole Graph Release, never one role
at a time.  The active release's seven definitions are compared with the
packaged manifest's seven by ``content_hash``:

- all seven match: nothing to do;
- the packaged definitions fail the publication validators: nothing is written;
- the live graph is touched (a hand-edited role, or the active release is a
  restore): the differing packaged definitions are inserted as
  ``system:code-ship`` revisions and nothing is published, so an admin can adopt;
- otherwise the packaged manifest is published through #269's core, the way
  rollback publishes historical content: no approval gate, no evidence, the
  three-way draft rebase.

A role is hand-edited when its active revision was not created by a ``system:``
actor **and** its content differs from the packaged definition for that role (the
content fallback: revisions are deduplicated by hash, so a person who typed the
shipped text keeps authorship of a revision that no ship could override).

Shipped content is always materialised as ``system:code-ship`` before the core
runs, whoever publishes it: the core would otherwise stamp ``created_by`` with the
publisher, and an adopted install would never count as untouched again.

Locks (global order, see ``graph_configuration_publication``):

- ``ship_packaged_manifest`` runs in one ``session_factory.begin()`` transaction:
  the bootstrap advisory lock, L0 exclusive, L1 (all seven draft agents), then the
  locked snapshot.  Every refusal and every write follows those locks.
- ``adopt_packaged_manifest`` takes L0 exclusive then L1 in the caller's session,
  as ``restore_release`` does.  It is an admin request, so no advisory lock.
- ``packaged_update_status`` takes only the shared parent lock and writes nothing.

No model, runtime or remote-endpoint call is made at all.

The manifest is always a parameter: this module never loads the packaged snapshot
(C5).  Like rollback, it imports neither ``graph_release_evidence`` nor #268's
workbench at module scope (Correction 29).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from sqlalchemy import select

from src.database.models.graph_configuration import AgentDefinitionRevision, GraphRelease
from src.services.graph_configuration_bootstrap import _GraphConfigurationBootstrap
from src.services.graph_configuration_content import (
    GraphConfigurationIntegrityError,
    database_transaction_timestamp,
    materialize_or_reuse_revision,
)
from src.services.graph_configuration_draft import DraftValidationIssue
from src.services.graph_configuration_publication import (
    FieldDiff,
    PublicationConflict,
    PublishedRelease,
    _model_nodes,
    definition_field_diffs,
)
from src.services.graph_configuration_rollback import (
    DraftEffect,
    _GraphConfigurationRollback,
)
from src.services.graph_configuration_workbench import ActiveReleaseSnapshot
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AgentKey,
    DefinitionContent,
    GraphV1Manifest,
    definition_content_hash,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from src.database.models.graph_configuration import GraphDraft, GraphDraftAgent
    from src.services.graph_configuration_workbench import GraphWorkbenchSnapshot

#: ``created_by`` of every code-shipped revision, and ``published_by`` of a
#: startup ship.
CODE_SHIP_ACTOR: Final = "system:code-ship"
#: A revision created by an actor with this prefix is code's, not a person's.
SYSTEM_ACTOR_PREFIX: Final = "system:"

PackagedBlockReason = Literal["hand_edited", "rollback", "invalid"]


@dataclass(frozen=True)
class PackagedUpdateStatus:
    #: The packaged manifest differs from the active release (any role hash).
    available: bool
    #: In ``GRAPH_V1_AGENT_KEYS`` order.
    differing_agents: tuple[AgentKey, ...]
    #: The first of ``invalid``, ``hand_edited``, ``rollback`` that applies; always
    #: ``None`` when nothing is available.  ``None`` with ``available`` means a
    #: startup ship would publish it.
    blocked_reason: PackagedBlockReason | None
    #: Active revisions not created by ``system:*`` that differ from the packaged
    #: definition for their role, in ``GRAPH_V1_AGENT_KEYS`` order.
    hand_edited_agents: tuple[AgentKey, ...]
    #: The publication validators over all seven packaged definitions, with
    #: fields ``definitions.<agent_key>.<field>``.
    validation_issues: tuple[DraftValidationIssue, ...]
    #: Active -> packaged, for the differing roles only.
    field_diffs: Mapping[AgentKey, tuple[FieldDiff, ...]]
    active_release: ActiveReleaseSnapshot
    #: The shared draft's current ``lock_version`` (what an adopt must send).
    lock_version: int


@dataclass(frozen=True)
class ShipNothing:
    release_id: int
    version_number: int


@dataclass(frozen=True)
class ShipBlocked:
    reason: Literal["hand_edited", "rollback"]
    hand_edited_agents: tuple[AgentKey, ...]


@dataclass(frozen=True)
class ShipInvalid:
    issues: tuple[DraftValidationIssue, ...]


@dataclass(frozen=True)
class Shipped:
    published: PublishedRelease
    #: Exactly seven, in ``GRAPH_V1_AGENT_KEYS`` order: what the rebase did.
    draft_effect: Mapping[AgentKey, DraftEffect]


ShipOutcome = ShipNothing | ShipBlocked | ShipInvalid | Shipped
AdoptOutcome = PublicationConflict | ShipNothing | ShipInvalid | Shipped


def _packaged_contents(manifest: GraphV1Manifest) -> dict[AgentKey, DefinitionContent]:
    """The manifest's seven definitions, keyed and ordered by ``GRAPH_V1_AGENT_KEYS``."""
    manifest.assert_complete(GRAPH_V1_AGENT_KEYS)
    definitions = {definition.agent_key: definition for definition in manifest.definitions}
    return {key: definitions[key] for key in GRAPH_V1_AGENT_KEYS}


def _content_hashes(
    contents: Mapping[AgentKey, DefinitionContent],
) -> dict[AgentKey, str]:
    return {key: definition_content_hash(contents[key]) for key in GRAPH_V1_AGENT_KEYS}


def _differing_agents(
    snapshot: GraphWorkbenchSnapshot, packaged_hashes: Mapping[AgentKey, str]
) -> tuple[AgentKey, ...]:
    model_nodes = _model_nodes(snapshot)
    return tuple(
        key
        for key in GRAPH_V1_AGENT_KEYS
        if model_nodes[key].published.content_hash != packaged_hashes[key]
    )


def _hand_edited_agents(
    session: Session,
    snapshot: GraphWorkbenchSnapshot,
    packaged_hashes: Mapping[AgentKey, str],
) -> tuple[AgentKey, ...]:
    """Active roles a person chose: not ``system:*`` and not the packaged content.

    Only a role whose active hash differs from the packaged one can be
    hand-edited (the content fallback), so only those creators are read.
    """
    model_nodes = _model_nodes(snapshot)
    differing = {
        key: model_nodes[key].published.revision_id
        for key in _differing_agents(snapshot, packaged_hashes)
    }
    if not differing:
        return ()
    creators: dict[int, str] = dict(
        session.execute(
            select(AgentDefinitionRevision.id, AgentDefinitionRevision.created_by).where(
                AgentDefinitionRevision.id.in_(differing.values())
            )
        ).all()
    )
    if set(creators) != set(differing.values()):
        raise GraphConfigurationIntegrityError(
            "active release maps a revision that cannot be read"
        )
    return tuple(
        key
        for key, revision_id in differing.items()
        if not creators[revision_id].startswith(SYSTEM_ACTOR_PREFIX)
    )


class _GraphConfigurationShipping(_GraphConfigurationRollback, _GraphConfigurationBootstrap):
    """Ship, adopt and report the packaged manifest against the active release.

    A thin caller of #269's publication core, reusing rollback's draft rebase
    (``_draft_effect``, ``_verify_rebased_draft``) and bootstrap's advisory lock.
    """

    def packaged_update_status(
        self, session: Session, *, manifest: GraphV1Manifest
    ) -> PackagedUpdateStatus:
        """What the packaged manifest would change, and why it was not shipped.

        One transaction under the shared parent lock (the ``preview_release``
        pattern).  Writes nothing.
        """
        packaged = _packaged_contents(manifest)
        packaged_hashes = _content_hashes(packaged)
        with session.begin():
            release_row, draft_row = self._lock_current_parents(session, exclusive=False)
            snapshot = self._snapshot_locked_workbench(
                session, release=release_row, draft=draft_row
            )
            differing = _differing_agents(snapshot, packaged_hashes)
            hand_edited = _hand_edited_agents(session, snapshot, packaged_hashes)
            issues = tuple(self._candidate_contents_issues(packaged))
            model_nodes = _model_nodes(snapshot)
            blocked: PackagedBlockReason | None
            if not differing:
                blocked = None
            elif issues:
                blocked = "invalid"
            elif hand_edited:
                blocked = "hand_edited"
            elif snapshot.active_release.restored_from_release_id is not None:
                blocked = "rollback"
            else:
                blocked = None
            return PackagedUpdateStatus(
                available=bool(differing),
                differing_agents=differing,
                blocked_reason=blocked,
                hand_edited_agents=hand_edited,
                validation_issues=issues,
                field_diffs=MappingProxyType(
                    {
                        key: definition_field_diffs(
                            model_nodes[key].published.content, packaged[key]
                        )
                        for key in differing
                    }
                ),
                active_release=snapshot.active_release,
                lock_version=draft_row.lock_version,
            )

    def ship_packaged_manifest(
        self,
        session_factory: sessionmaker,
        *,
        manifest: GraphV1Manifest,
        app_version: str,
    ) -> ShipOutcome:
        """Publish the packaged manifest if the live graph is untouched (startup).

        One transaction: the bootstrap advisory lock, L0 exclusive, L1, then the
        snapshot.  In order: all seven hashes match -> ``ShipNothing``; the
        packaged definitions have validation issues -> ``ShipInvalid``; the install
        is touched -> the differing packaged definitions are materialised as
        ``system:code-ship`` and ``ShipBlocked`` (no release, no draft change);
        otherwise ``Shipped``, published by ``system:code-ship``.  Only
        ``ShipBlocked`` and ``Shipped`` write.
        """
        packaged = _packaged_contents(manifest)
        packaged_hashes = _content_hashes(packaged)
        with session_factory.begin() as session:
            self._take_bootstrap_lock(session)
            release_row, draft_row = self._lock_current_parents(session, exclusive=True)
            draft_rows = {
                row.agent_key: row
                for row in self._lock_all_draft_agents(session, draft_id=draft_row.id)
            }
            snapshot = self._snapshot_locked_workbench(
                session, release=release_row, draft=draft_row
            )
            differing = _differing_agents(snapshot, packaged_hashes)
            if not differing:
                return ShipNothing(release_row.id, release_row.version_number)
            issues = tuple(self._candidate_contents_issues(packaged))
            if issues:
                return ShipInvalid(issues)
            hand_edited = _hand_edited_agents(session, snapshot, packaged_hashes)
            blocked: ShipBlocked | None = None
            if hand_edited:
                blocked = ShipBlocked("hand_edited", hand_edited)
            elif snapshot.active_release.restored_from_release_id is not None:
                blocked = ShipBlocked("rollback", ())
            if blocked is not None:
                self._materialize_packaged(session, packaged, differing)
                return blocked
            return self._publish_packaged(
                session,
                release_row=release_row,
                draft_row=draft_row,
                draft_rows=draft_rows,
                snapshot=snapshot,
                packaged=packaged,
                packaged_hashes=packaged_hashes,
                release_note=f"Shipped with Tellr {app_version}",
                actor=CODE_SHIP_ACTOR,
            )

    def adopt_packaged_manifest(
        self,
        session: Session,
        *,
        manifest: GraphV1Manifest,
        app_version: str,
        actor: str,
        expected_lock_version: int,
    ) -> AdoptOutcome:
        """An admin publishes the packaged manifest, whatever blocked the ship.

        The request shape (actor, lock version, note) is checked before any lock
        and raises ``PublicationRejected``.  Then one transaction: L0 exclusive,
        L1, the snapshot; a stale lock is a ``PublicationConflict``; then
        ``ShipNothing`` if all seven match, ``ShipInvalid`` if the packaged
        definitions have issues; otherwise the shipped revisions are materialised
        as ``system:code-ship`` and published with ``published_by`` = ``actor``.
        Hand edits and rollbacks do not block an adopt.
        """
        release_note = f"Adopted shipped version (Tellr {app_version})"
        self._validate_publication_request(actor, expected_lock_version, release_note)
        packaged = _packaged_contents(manifest)
        packaged_hashes = _content_hashes(packaged)
        with session.begin():
            release_row, draft_row = self._lock_current_parents(session, exclusive=True)
            draft_rows = {
                row.agent_key: row
                for row in self._lock_all_draft_agents(session, draft_id=draft_row.id)
            }
            snapshot = self._snapshot_locked_workbench(
                session, release=release_row, draft=draft_row
            )
            if expected_lock_version != draft_row.lock_version:
                return PublicationConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=draft_row.lock_version,
                    active_release_id=release_row.id,
                    active_version_number=release_row.version_number,
                    draft=snapshot.draft,
                )
            if not _differing_agents(snapshot, packaged_hashes):
                return ShipNothing(release_row.id, release_row.version_number)
            issues = tuple(self._candidate_contents_issues(packaged))
            if issues:
                return ShipInvalid(issues)
            return self._publish_packaged(
                session,
                release_row=release_row,
                draft_row=draft_row,
                draft_rows=draft_rows,
                snapshot=snapshot,
                packaged=packaged,
                packaged_hashes=packaged_hashes,
                release_note=release_note,
                actor=actor,
            )

    @staticmethod
    def _materialize_packaged(
        session: Session,
        packaged: Mapping[AgentKey, DefinitionContent],
        agent_keys: tuple[AgentKey, ...],
    ) -> frozenset[AgentKey]:
        """Insert (or reuse) the packaged revisions as ``system:code-ship``.

        Returns the roles whose revision this call added.  The caller holds L0.
        """
        timestamp = database_transaction_timestamp(session)
        added: set[AgentKey] = set()
        for key in agent_keys:
            _revision, was_added = materialize_or_reuse_revision(
                session, packaged[key], actor=CODE_SHIP_ACTOR, timestamp=timestamp
            )
            if was_added:
                added.add(key)
        session.flush()
        return frozenset(added)

    def _publish_packaged(
        self,
        session: Session,
        *,
        release_row: GraphRelease,
        draft_row: GraphDraft,
        draft_rows: Mapping[AgentKey, GraphDraftAgent],
        snapshot: GraphWorkbenchSnapshot,
        packaged: Mapping[AgentKey, DefinitionContent],
        packaged_hashes: Mapping[AgentKey, str],
        release_note: str,
        actor: str,
    ) -> Shipped:
        """The ship/adopt write: system revisions, #269's core, the draft rebase.

        The caller holds L0 and L1 and has made every refusal.  An integrity
        error here aborts the whole transaction, pre-materialised revisions
        included.
        """
        added = self._materialize_packaged(session, packaged, GRAPH_V1_AGENT_KEYS)
        effect = self._draft_effect(snapshot, packaged_hashes)
        published = self._commit_locked_publication(
            session,
            release_row=release_row,
            draft_row=draft_row,
            snapshot=snapshot,
            contents=packaged,
            evidence=(),
            release_note=release_note,
            actor=actor,
            restored_from_release_id=None,
        )
        if not all(mapping.reused for mapping in published.mappings.values()):
            raise GraphConfigurationIntegrityError(
                "publication materialized a shipped revision as the publisher"
            )
        for key in GRAPH_V1_AGENT_KEYS:
            if effect[key] == "reset":
                self._assign_locked_candidate(draft_rows[key], packaged[key])
        session.flush()
        new_release_row = session.get(GraphRelease, published.release.release_id)
        if new_release_row is None:
            raise GraphConfigurationIntegrityError(
                "shipped release is missing after publication"
            )
        self._verify_rebased_draft(
            session,
            release_row=new_release_row,
            draft_row=draft_row,
            effect=effect,
            before=snapshot,
            restored=packaged,
        )
        # The core saw every revision as existing; report the ones this
        # transaction added as new (``PublishedMapping.reused``'s contract).
        published = replace(
            published,
            mappings=MappingProxyType(
                {
                    key: replace(mapping, reused=key not in added)
                    for key, mapping in published.mappings.items()
                }
            ),
        )
        return Shipped(published=published, draft_effect=effect)


__all__ = [
    "CODE_SHIP_ACTOR",
    "SYSTEM_ACTOR_PREFIX",
    "AdoptOutcome",
    "PackagedBlockReason",
    "PackagedUpdateStatus",
    "ShipBlocked",
    "ShipInvalid",
    "ShipNothing",
    "ShipOutcome",
    "Shipped",
]
