"""#262 cross-writer acceptance over real PostgreSQL, plus the two final audits.

What this module is FOR, and why it is not a duplicate of the four suites that
precede it.

``test_shared_deck_mutation_attribution.py`` proves each writer in isolation over
SQLite; ``test_mixed_release_creation_postgres.py`` proves each creator's lock
ordering; ``test_collaboration_history_api_postgres.py`` proves the authorization
predicate and the grouped projection. Every one of those holds ONE variable still.
This module holds nothing still: **one root deck** receives writes from the owner
on R1, a graph-capable contributor on R2, and a legacy null-pinned contributor, in
one real PostgreSQL transaction sequence, and the assertions are about what the
whole system then says about that deck — exact root/actor/opaque identities, pins
that did not move, the grouped warning, and the absence of any root inference.

Three properties only an end-to-end module can falsify:

1. **No root inference.** Each writer's event must carry the ACTOR's release, not
   the root's. Every isolated suite pins one actor at a time, so a writer that
   substituted the root's pin would still look right in all of them whenever the
   actor happened to be the root. Here the root is on R1 while the contributor is
   on R2 on the SAME deck, so substituting the root's pin changes an observable.
2. **Immutable pins under load.** The owner stays on R1 after a publication, a
   contributor's creation, a duplicate's creation and six content writes. Nothing
   in the isolated suites re-reads the owner's pin at the END of all that.
3. **One grouped query.** Counted over the real fan of six events across three
   actors and three releases, where an N+1 would actually show.

THE TWO CONTRACT AUDITS ARE EXECUTABLE HERE, not prose in a report. The plan's
final audit says to re-run two ``rg`` sweeps and classify every production seam
they discover. A sweep whose result lives in a report is re-run by hand or not at
all, so both are tests: they grep ``src/`` and compare the discovered seam set
against a LITERAL inventory. A new production content writer or session creator
therefore fails this module rather than reaching merge unclassified.

Why PostgreSQL. Three of the claims below cannot be cashed on SQLite: the
``ON DELETE SET NULL`` retention (the unit fixture reports
``PRAGMA foreign_keys = 0``, so nothing cascades and a delete leaves a dangling
FK rather than a nulled one), the append-only trigger, and the forced creation
lock orderings, which need two genuinely concurrent transactions and
``pg_stat_activity`` to observe a waiter.
"""

from __future__ import annotations

import contextlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.api.services.chat_service import ChatService
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter
from src.core.database import _run_migrations, get_db
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionMessage,
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.domain.conversation_engine import AGENT_MODE_PHRASE
from src.services.collaboration_history import (
    AuthorizedCollaborationRoot,
    authorized_collaboration_root,
    get_collaboration_history,
)
from src.services.graph.nodes import _placehold_failed_position, _STALL_REASON
from src.services.permission_service import PermissionContext
from src.services.shared_deck_attribution import DeckMutationContext, MutationActor
from tests.integration.postgres_concurrency_helpers import (
    _WAIT_SECONDS,
    _await_lock_waiters,
)

pytestmark = pytest.mark.postgres

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

#: The four legacy lookup seams C-15 names, plus ``SessionManager.get_session``.
#:
#: DISCLOSURE, carried forward from slice 4A and refined by C-20: the first entry
#: is a *route handler*, and the ``APIRouter`` captured that function object at
#: decoration time, so router dispatch cannot reach a module-level patch of it.
#: It is CONDITIONAL rather than inert — an in-module call from the history
#: handler WOULD fire it — and it is kept because C-15 names it. The three
#: ``SessionManager`` class-attribute patches are unconditionally load-bearing.
_TRIPWIRES = (
    "src.api.routes.sessions.get_session",
    "src.api.services.session_manager.SessionManager._get_session_or_raise",
    "src.api.services.session_manager.SessionManager._get_deck_owner_session",
    "src.api.routes.deck_contributors._get_root_session_or_400",
    "src.api.services.session_manager.SessionManager.get_session",
)


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def _sweep(needle: str) -> set[tuple[str, str]]:
    """Every ``src/`` site matching *needle*, as ``(relative path, stripped line)``.

    The plan's final audit is two ``rg`` sweeps. This is that sweep, run as a test
    rather than by hand, over production code only — ``src/`` — because a test
    that also swept ``tests/`` would churn on every new test.

    KEYED ON THE LINE'S TEXT, NOT ITS NUMBER. A ``path:line`` inventory drifts
    whenever anything above it in the same file is edited, so it would fail for
    reasons that have nothing to do with a new writer appearing — and a guard
    that cries wolf gets deleted. The stripped source line identifies the site
    just as precisely and survives every edit that does not change the site
    itself.
    """
    hits: set[tuple[str, str]] = set()
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if needle in line:
                hits.add((relative, line.strip()))
    return hits


def _sweep_definitions(needle: str) -> set[tuple[str, str]]:
    """Sites matching *needle* that are neither a comment nor a docstring line.

    Constructor and creator audits care about code, and ``src/`` carries long
    design commentary naming these symbols dozens of times. The filter is
    deliberately crude — it drops lines starting with ``#``, ``*`` or a triple
    quote — because a crude filter that keeps too much is safe here (an extra
    site simply has to be classified) while one that drops too much is not.
    """
    return {
        (path, line)
        for path, line in _sweep(needle)
        if not line.startswith(("#", "*", '"""', "'''"))
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def _db_context(factory):
    @contextlib.contextmanager
    def managed():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return managed


def _release(db, *, version_number: int, active: bool, previous_release_id=None):
    published = datetime(2026, 9, 24, tzinfo=timezone.utc) + timedelta(
        seconds=version_number
    )
    release = GraphRelease(
        version_number=version_number,
        previous_release_id=previous_release_id,
        release_note=f"acceptance release v{version_number}",
        published_by="acceptance@example.com",
        published_at=published,
        effective_from=published,
        effective_to=None if active else published + timedelta(seconds=1),
    )
    db.add(release)
    db.flush()
    return release


def _publish_next(db, *, current: GraphRelease, version_number: int) -> GraphRelease:
    """Close the active release and open its successor, SCD2 style."""
    closed_at = current.effective_from + timedelta(seconds=30)
    current.effective_to = closed_at
    successor = GraphRelease(
        version_number=version_number,
        previous_release_id=current.id,
        release_note=f"acceptance release v{version_number}",
        published_by="acceptance@example.com",
        published_at=closed_at,
        effective_from=closed_at,
        effective_to=None,
    )
    db.add(successor)
    db.flush()
    return successor


def _deck_dict(slides):
    return {
        "title": "Shared acceptance deck",
        "css": ".slide{}",
        "external_scripts": [],
        "head_meta": {},
        "slides": slides,
    }


def _events(factory, *, after: int = 0):
    """Evidence rows above a watermark, in insertion order.

    A WATERMARK RATHER THAN A WIPE, and the reason is the contract under test:
    the PostgreSQL trigger makes this table genuinely append-only, so the
    fixture cannot delete its own setup rows — ``DELETE FROM
    shared_deck_mutation_event`` raises "shared deck mutation events are
    append-only". That is the append-only guarantee working, so the test
    accommodates it instead of weakening it.
    """
    with factory() as db:
        return list(
            db.scalars(
                select(SharedDeckMutationEvent)
                .where(SharedDeckMutationEvent.id > after)
                .order_by(SharedDeckMutationEvent.id)
            )
        )


def _graph_mutation(session_id, release_id, *, operation, object_type, object_id=None):
    return DeckMutationContext(
        actor=MutationActor(session_id, release_id),
        operation=operation,
        object_type=object_type,
        object_id=object_id,
    )


class _Tripwires:
    """Patch the five legacy lookup seams and record every call through them."""

    def __enter__(self):
        self._patchers = [patch(target, autospec=True) for target in _TRIPWIRES]
        self.mocks = {
            target: patcher.start()
            for target, patcher in zip(_TRIPWIRES, self._patchers)
        }
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self._patchers):
            patcher.stop()
        return False

    def assert_never_called(self):
        reached = {
            target: mock.call_args_list
            for target, mock in self.mocks.items()
            if mock.call_count
        }
        assert reached == {}, f"legacy lookup seams were reached: {reached}"


# ---------------------------------------------------------------------------
# The acceptance fixture — one root deck, three actors, three releases
# ---------------------------------------------------------------------------


@pytest.fixture
def acceptance(postgres_engine, monkeypatch):
    """R1 owner, R2 graph contributor, marker duplicate, legacy null contributor.

    Every session here is created by a REAL production creator, not inserted:
    ``create_session(graph_capable=True)`` for the owner,
    ``get_or_create_contributor_session`` for the contributor and
    ``duplicate_session`` for the marker duplicate. The one hand-inserted row is
    the legacy null-pinned contributor, and it has to be: no live creator can
    produce a null-pinned contributor any more, which is exactly why legacy
    evidence needs a pre-#261 row to exist at all.
    """
    factory = _factory(postgres_engine)
    db_context = _db_context(factory)
    for target in (
        "src.api.services.session_manager.get_db_session",
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
        "src.services.spec_sync.get_db_session",
        "src.services.graph.nodes.get_db_session",
    ):
        monkeypatch.setattr(target, db_context)
    monkeypatch.setattr(
        "src.api.services.chat_service.get_current_username",
        lambda: "acceptance@example.com",
    )
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )

    manager = SessionManager()

    with factory.begin() as db:
        r1 = _release(db, version_number=1, active=True)
        r1_id, r1_version = r1.id, r1.version_number

    # 1. The owner: an explicit graph-capable root, pinned to the active R1.
    owner_id = manager.create_session(
        session_id="acceptance-owner",
        created_by="owner@example.com",
        graph_capable=True,
    )["session_id"]

    # Its deck, plus a marker message so the duplicate carries the marker.
    manager.save_slide_deck(
        owner_id,
        "Shared acceptance deck",
        '<div class="slide">A</div><div class="slide">B</div>',
        slide_count=2,
        deck_dict=_deck_dict(
            [
                {"slide_id": "slide-a", "html": '<div class="slide">A</div>'},
                {"slide_id": "slide-b", "html": '<div class="slide">B</div>'},
            ]
        ),
    )
    with factory.begin() as db:
        owner_row = db.scalar(
            select(UserSession).where(UserSession.session_id == owner_id)
        )
        db.add(
            SessionMessage(
                session_id=owner_row.id,
                role="user",
                content=f"{AGENT_MODE_PHRASE} build the shared deck",
            )
        )

    # 2. Publish R2. The owner's pin must not move.
    with factory.begin() as db:
        r2 = _publish_next(db, current=db.get(GraphRelease, r1_id), version_number=2)
        r2_id, r2_version = r2.id, r2.version_number

    # 3. A graph-capable contributor. Always capable, so it pins the active R2.
    contributor_id = manager.get_or_create_contributor_session(
        owner_id, "contributor@example.com"
    )["session_id"]

    # 4. A marker-carrying duplicate: a NEW root on R2 while the source stays R1.
    duplicate_id = manager.duplicate_session(owner_id, "duplicator@example.com")[
        "session_id"
    ]

    # 5. A legacy null-pinned contributor of the SAME root — a pre-#261 row.
    with factory.begin() as db:
        owner_row = db.scalar(
            select(UserSession).where(UserSession.session_id == owner_id)
        )
        db.add(
            UserSession(
                session_id="acceptance-legacy",
                created_by="legacy@example.com",
                parent_session_id=owner_row.id,
                graph_release_id=None,
            )
        )

    with factory() as db:
        # The fixture's own setup wrote through the monolith seam, so it left
        # evidence. That evidence cannot be deleted (the table is append-only by
        # trigger), so every test below counts only rows above this watermark.
        setup_events = list(
            db.scalars(
                select(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id)
            )
        )
        # LITERAL 2: the owner's one save_slide_deck emits save_deck and
        # save_deck_slides, and nothing else in setup writes content. A creator
        # that started emitting evidence would change this number.
        assert [e.operation for e in setup_events] == [
            "save_deck",
            "save_deck_slides",
        ], [e.operation for e in setup_events]
        watermark = setup_events[-1].id

    with factory() as db:
        owner_row = db.scalar(
            select(UserSession).where(UserSession.session_id == owner_id)
        )
        deck_row = db.scalar(
            select(SessionSlideDeck).where(SessionSlideDeck.session_id == owner_row.id)
        )
        contributor_row = db.scalar(
            select(UserSession).where(UserSession.session_id == contributor_id)
        )
        duplicate_row = db.scalar(
            select(UserSession).where(UserSession.session_id == duplicate_id)
        )
        legacy_row = db.scalar(
            select(UserSession).where(
                UserSession.session_id == "acceptance-legacy"
            )
        )
        ids = {
            "factory": factory,
            "manager": manager,
            "owner_id": owner_id,
            "contributor_id": contributor_id,
            "duplicate_id": duplicate_id,
            "legacy_id": "acceptance-legacy",
            "owner_pk": owner_row.id,
            "deck_pk": deck_row.id,
            "contributor_pk": contributor_row.id,
            "duplicate_pk": duplicate_row.id,
            "legacy_pk": legacy_row.id,
            "owner_identity": owner_row.collaboration_identity,
            "deck_identity": deck_row.collaboration_identity,
            "contributor_identity": contributor_row.collaboration_identity,
            "legacy_identity": legacy_row.collaboration_identity,
            "r1": r1_id,
            "r2": r2_id,
            "r1_version": r1_version,
            "r2_version": r2_version,
            "watermark": watermark,
        }
    return ids


def _drive_every_writer(acc):
    """Contributor graph row+deck writes, both placeholders, legacy and root writes.

    Returns nothing: the assertions read the evidence table back, because the
    claim is about what the DATABASE holds, not about what these calls returned.
    """
    contributor_id, r2 = acc["contributor_id"], acc["r2"]

    # Contributor graph ROW write — the builder's committed slide.
    SlideWriter().write_slide(
        contributor_id,
        2,
        '<div class="slide">contributor graph row</div>',
        slide_id="slide-graph",
        mutation=_graph_mutation(
            contributor_id, r2, operation="write_slide", object_type="slide",
            object_id="slide-graph",
        ),
    )
    # Contributor graph DECK write — the deck reviewer's post-commit columns.
    write_deck_level_columns(
        contributor_id,
        title="Shared acceptance deck",
        mutation=_graph_mutation(
            contributor_id, r2, operation="write_deck_level", object_type="deck"
        ),
    )
    # BUILDER FAILURE placeholder, through the production helper both fanned
    # nodes use — not a hand-rolled commit_placeholder call, because the claim is
    # that the graph's own failure path forwards its context.
    assert _placehold_failed_position(
        3,
        session_id=contributor_id,
        node="builder",
        reason="RuntimeError",
        mutation=_graph_mutation(
            contributor_id, r2, operation="write_slide", object_type="slide"
        ),
    )
    # STALL placeholder — the foreman's reconciliation of a position no branch
    # delivered. Same helper, distinguished only by its reason.
    assert _placehold_failed_position(
        4,
        session_id=contributor_id,
        node="placeholder",
        reason=_STALL_REASON,
        mutation=_graph_mutation(
            contributor_id, r2, operation="write_slide", object_type="slide"
        ),
    )
    # NULL LEGACY direct write, by the pre-#261 contributor on the same deck.
    ChatService().update_slide(
        acc["legacy_id"], 0, '<div class="slide">legacy edit</div>'
    )
    # ROOT write, by the owner on R1.
    ChatService().update_slide(
        acc["owner_id"], 1, '<div class="slide">owner edit</div>'
    )


# ---------------------------------------------------------------------------
# 1. Cross-writer acceptance over one root deck
# ---------------------------------------------------------------------------


def test_every_writer_records_one_root_deck_with_its_own_actor_and_release(acceptance):
    """Break caught: any writer substitutes the root's pin for the actor's."""
    acc = acceptance
    _drive_every_writer(acc)

    events = _events(acc["factory"], after=acc["watermark"])
    assert [e.operation for e in events] == [
        "write_slide",
        "write_deck_level",
        "write_slide",
        "write_slide",
        "update_slide",
        "update_slide",
    ]

    # ONE root deck and ONE root session for every event, whoever wrote it.
    assert {e.root_session_id for e in events} == {acc["owner_pk"]}
    assert {e.root_deck_id for e in events} == {acc["deck_pk"]}
    # The opaque snapshots are the ROW's identities, not re-derived.
    assert {str(e.root_session_identity) for e in events} == {
        str(acc["owner_identity"])
    }
    assert {str(e.root_deck_identity) for e in events} == {str(acc["deck_identity"])}

    # Exact actor x release triple. The literal versions are what make this a
    # NO-ROOT-INFERENCE assertion: the contributor's four writes say version 2
    # while the root deck's owner is pinned to version 1.
    actual = [
        (e.actor_session_id, str(e.actor_session_identity), e.graph_release_id, e.graph_version)
        for e in events
    ]
    assert actual == [
        (acc["contributor_pk"], str(acc["contributor_identity"]), acc["r2"], 2),
        (acc["contributor_pk"], str(acc["contributor_identity"]), acc["r2"], 2),
        (acc["contributor_pk"], str(acc["contributor_identity"]), acc["r2"], 2),
        (acc["contributor_pk"], str(acc["contributor_identity"]), acc["r2"], 2),
        (acc["legacy_pk"], str(acc["legacy_identity"]), None, None),
        (acc["owner_pk"], str(acc["owner_identity"]), acc["r1"], 1),
    ]

    # Both placeholder rows really are placeholders, and they are distinguishable
    # from each other only by which call site made them — so a helper that
    # collapsed the two reasons would still be caught by the rows.
    with acc["factory"]() as db:
        rows = {
            row.position: row
            for row in db.scalars(
                select(SessionSlide).where(SessionSlide.session_id == acc["owner_pk"])
            )
        }
    assert {3, 4} <= set(rows)
    assert [e.object_id for e in events[2:4]] == [
        rows[3].slide_id,
        rows[4].slide_id,
    ]


def test_no_pin_moved_under_the_whole_write_sequence(acceptance):
    """Break caught: a writer or creator repins a session it touched."""
    acc = acceptance
    _drive_every_writer(acc)

    with acc["factory"]() as db:
        pins = {
            row.session_id: row.graph_release_id
            for row in db.scalars(
                select(UserSession).where(
                    UserSession.session_id.in_(
                        [
                            acc["owner_id"],
                            acc["contributor_id"],
                            acc["duplicate_id"],
                            acc["legacy_id"],
                        ]
                    )
                )
            )
        }
        active = db.scalar(
            select(GraphRelease).where(GraphRelease.effective_to.is_(None))
        )

    # The owner never left R1 although R2 is active and four writes landed on its
    # deck; the duplicate took the NEW active release rather than copying R1.
    assert pins == {
        acc["owner_id"]: acc["r1"],
        acc["contributor_id"]: acc["r2"],
        acc["duplicate_id"]: acc["r2"],
        acc["legacy_id"]: None,
    }
    assert active.id == acc["r2"]
    assert (acc["r1_version"], acc["r2_version"]) == (1, 2)


def test_history_groups_and_warns_without_labelling_the_deck_with_the_root_version(
    acceptance,
):
    """Break caught: grouping collapses actors, or a row takes the root's version."""
    acc = acceptance
    _drive_every_writer(acc)

    with acc["factory"]() as db:
        root = authorized_collaboration_root(
            db,
            requested_session_id=acc["owner_id"],
            permission_context=PermissionContext(
                user_id=None, user_name="owner@example.com", group_ids=[]
            ),
        )
        assert root == AuthorizedCollaborationRoot(
            root_session_id=acc["owner_pk"], root_deck_id=acc["deck_pk"]
        )
        warning, legacy, groups = get_collaboration_history(db, root=root)

    # Two persisted non-null versions on one deck, so the warning is true; the
    # null-pinned row is counted separately and never contributes to it.
    assert (warning, legacy) == (True, True)

    # Three groups, newest first, with response-local labels.
    #
    # The owner's count is 3, not 1: its one direct `update_slide` plus the two
    # the fixture's `save_slide_deck` emitted (`save_deck` and
    # `save_deck_slides`). That is the assertion's point rather than an accident
    # — the monolith seam's pair of events must group with the SAME actor and the
    # SAME release as that actor's direct write, and a projection that keyed on
    # anything but the opaque actor identity plus the exact release would split
    # them.
    #
    # LITERAL versions and counts. The contributor's four changes say Graph
    # Version 2 while this deck's root is pinned to Graph Version 1, so a
    # projection that labelled a contributor's change with the root's version
    # cannot satisfy this list — which is AC6, measured.
    assert [
        (g.actor_label, g.graph_version, g.mutation_count) for g in groups
    ] == [
        ("Contributor 1", 1, 3),
        ("Contributor 2", None, 1),
        ("Contributor 3", 2, 4),
    ]
    # Newest first, on the timestamps the writers actually stamped.
    assert [g.last_mutation_at for g in groups] == sorted(
        (g.last_mutation_at for g in groups), reverse=True
    )
    # The labels are opaque and response-local: no session id, identity, name or
    # principal reaches the projection at all.
    rendered = repr(groups)
    for secret in (
        acc["owner_id"],
        acc["contributor_id"],
        acc["legacy_id"],
        str(acc["owner_identity"]),
        str(acc["contributor_identity"]),
        "owner@example.com",
        "contributor@example.com",
    ):
        assert secret not in rendered


def test_one_persisted_version_plus_legacy_evidence_does_not_warn(acceptance):
    """Break caught: the warning counts a NULL release as a second version.

    ADDED BECAUSE A MUTATION MEASURED ZERO. Making the warning count null
    releases as versions left all 24 tests green, because the main fixture holds
    two persisted versions already — {1, 2} becomes {1, None, 2} and the boolean
    cannot move. The clause is "true only for two persisted NON-NULL versions",
    and the only shape that can falsify it is ONE persisted version beside legacy
    evidence: the correct answer is False, and a warning that counted nulls says
    True.
    """
    acc = acceptance
    # The legacy contributor and the owner only — both on R1 and null, so exactly
    # ONE persisted version is present alongside legacy evidence.
    ChatService().update_slide(
        acc["legacy_id"], 0, '<div class="slide">legacy only</div>'
    )
    ChatService().update_slide(
        acc["owner_id"], 1, '<div class="slide">owner only</div>'
    )

    with acc["factory"]() as db:
        root = AuthorizedCollaborationRoot(
            root_session_id=acc["owner_pk"], root_deck_id=acc["deck_pk"]
        )
        warning, legacy, groups = get_collaboration_history(db, root=root)

    versions = {group.graph_version for group in groups}
    # Exactly one persisted version, and a null one beside it.
    assert versions == {1, None}, versions
    assert warning is False
    assert legacy is True


def test_history_excludes_another_root_decks_evidence(acceptance):
    """Break caught: the projection is not constrained to the requested root deck.

    ADDED BECAUSE A MUTATION MEASURED ZERO. Dropping
    ``deck.id == root.root_deck_id`` left all 24 tests green, and the redundancy
    with ``deck.session_id == root.root_session_id`` was only half the reason:
    the fixture had just ONE root deck carrying evidence, so removing every deck
    constraint would have returned the same rows. A second root deck with its own
    event is what makes the constraint observable at all.
    """
    acc = acceptance
    _drive_every_writer(acc)
    factory = acc["factory"]

    # A second, unrelated root deck with one event of its own.
    from src.services.shared_deck_attribution import record_shared_deck_mutation

    with factory.begin() as db:
        other_root = UserSession(
            session_id="acceptance-other-root",
            created_by="other@example.com",
            graph_release_id=acc["r2"],
        )
        db.add(other_root)
        db.flush()
        other_deck = SessionSlideDeck(session_id=other_root.id, title="Other deck")
        db.add(other_deck)
        db.flush()
        record_shared_deck_mutation(
            db,
            requesting_session=other_root,
            deck_owner=other_root,
            deck=other_deck,
            actor=MutationActor(other_root.session_id, acc["r2"]),
            operation="update_slide",
            object_type="deck",
            object_id="other-slide",
        )
        other_deck_pk, other_root_pk = other_deck.id, other_root.id

    with factory() as db:
        mine = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=acc["owner_pk"], root_deck_id=acc["deck_pk"]
            ),
        )
        theirs = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=other_root_pk, root_deck_id=other_deck_pk
            ),
        )

    # Eight events exist on my deck (six writes plus the fixture's two) and ONE on
    # theirs. LITERAL counts: a projection that ignored the deck constraints would
    # report 9 on both.
    assert sum(group.mutation_count for group in mine[2]) == 8
    assert sum(group.mutation_count for group in theirs[2]) == 1
    assert len(theirs[2]) == 1
    assert theirs[2][0].graph_version == 2
    # And the other deck's single actor never appears among mine.
    assert mine[0] is True and theirs[0] is False


def test_history_is_one_grouped_statement_over_six_events_and_three_actors(acceptance):
    """Break caught: the projection fans out per actor or per release (N+1)."""
    acc = acceptance
    _drive_every_writer(acc)
    factory = acc["factory"]
    statements: list[str] = []

    with factory() as db:
        root = AuthorizedCollaborationRoot(
            root_session_id=acc["owner_pk"], root_deck_id=acc["deck_pk"]
        )

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def record(_conn, _cursor, statement, _params, _ctx, _many):
            if "shared_deck_mutation_event" in statement.lower():
                statements.append(statement)

        try:
            _warning, _legacy, groups = get_collaboration_history(db, root=root)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)

    # LITERAL 1 and LITERAL 3: one statement, three groups. An N+1 would be 1+3
    # or 1+6, and a single statement that returned one group would not be a
    # grouped projection at all.
    assert len(statements) == 1, statements
    assert len(groups) == 3
    assert "group by" in statements[0].lower()


# ---------------------------------------------------------------------------
# 2. Forced creation lock orderings, both ways round
# ---------------------------------------------------------------------------


def _backend_pid(conn):
    return conn.connection.driver_connection.get_backend_pid()


def _await_specific_lock_waiter(engine, pid):
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            if observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid = :pid "
                    "AND wait_event_type = 'Lock')"
                ),
                {"pid": pid},
            ):
                return True
        time.sleep(0.02)
    return False


@contextlib.contextmanager
def _creator_patches(factory):
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _db_context(factory)
    ), patch(
        "src.api.services.chat_service.get_session_manager", return_value=manager
    ), patch(
        "src.core.settings_db.get_settings", return_value=MagicMock()
    ):
        yield manager


def _seed_owner_on_r1(factory):
    with factory.begin() as db:
        r1 = _release(db, version_number=1, active=True)
        owner = UserSession(
            session_id="lock-owner",
            created_by="owner@example.com",
            title="R1 owner",
            graph_release_id=r1.id,
        )
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="R1 owner",
                html_content="<div>R1</div>",
                slide_count=1,
                deck_json='{"slides":[{"html":"<div>R1</div>"}]}',
            )
        )
        db.add(
            SessionMessage(
                session_id=owner.id,
                role="user",
                content=f"{AGENT_MODE_PHRASE} lock ordering",
            )
        )
        return r1.id


def _publisher(factory, r1_id, locked, proceed, pids):
    threading.current_thread().name = "publisher"
    with factory.begin() as db:
        pids["publisher"] = db.scalar(text("SELECT pg_backend_pid()"))
        r1 = db.scalar(
            select(GraphRelease).where(GraphRelease.id == r1_id).with_for_update()
        )
        locked.set()
        assert proceed.wait(timeout=20), "publisher was never released"
        return _publish_next(db, current=r1, version_number=2).id


def _create(manager, creator):
    if creator == "explicit-root":
        return manager.create_session(
            session_id="lock-actor",
            created_by="actor@example.com",
            graph_capable=True,
        )["session_id"]
    if creator == "contributor":
        return manager.get_or_create_contributor_session(
            "lock-owner", "actor@example.com"
        )["session_id"]
    if creator == "duplicate":
        return manager.duplicate_session("lock-owner", "actor@example.com")[
            "session_id"
        ]
    raise AssertionError(creator)


@pytest.mark.parametrize("creator", ["explicit-root", "contributor", "duplicate"])
def test_publication_first_pins_the_creator_to_exact_r2_and_attributes_r2(
    postgres_engine, creator, monkeypatch
):
    """Break caught: a creator behind a publication pins latest-by-guess."""
    factory = _factory(postgres_engine)
    monkeypatch.setattr(
        "src.api.services.slide_repository.get_db_session", _db_context(factory)
    )
    r1_id = _seed_owner_on_r1(factory)
    locked, proceed, pids = threading.Event(), threading.Event(), {}

    @event.listens_for(postgres_engine, "before_cursor_execute")
    def observe(conn, _cursor, statement, _params, _ctx, _many):
        if (
            threading.current_thread().name == "creator"
            and "FROM graph_release" in statement
            and "FOR UPDATE" in statement
        ):
            pids["creator"] = _backend_pid(conn)

    try:
        with _creator_patches(factory) as manager, ThreadPoolExecutor(2) as pool:
            publisher = pool.submit(_publisher, factory, r1_id, locked, proceed, pids)
            assert locked.wait(timeout=10), "publisher did not lock R1"

            def create():
                threading.current_thread().name = "creator"
                return _create(manager, creator)

            created = pool.submit(create)
            deadline = time.monotonic() + 10
            while "creator" not in pids and time.monotonic() < deadline:
                time.sleep(0.02)
            assert _await_specific_lock_waiter(postgres_engine, pids["creator"])
            assert _await_lock_waiters(postgres_engine, 1) >= 1
            assert pids["creator"] != pids["publisher"]
            proceed.set()
            r2_id = publisher.result(timeout=20)
            actor_id = created.result(timeout=20)
    finally:
        event.remove(postgres_engine, "before_cursor_execute", observe)

    assert r2_id != r1_id
    with factory() as db:
        actor = db.scalar(select(UserSession).where(UserSession.session_id == actor_id))
        owner = db.scalar(select(UserSession).where(UserSession.session_id == "lock-owner"))
        assert actor.graph_release_id == r2_id
        # The source's pin is untouched by either ordering.
        assert owner.graph_release_id == r1_id

    # And the evidence a write by that actor produces carries the EXACT release
    # it locked — not the active one re-resolved at write time.
    if creator == "contributor":
        SlideWriter().write_slide(
            actor_id,
            1,
            '<div class="slide">after the race</div>',
            slide_id="slide-race",
            mutation=_graph_mutation(
                actor_id, r2_id, operation="write_slide", object_type="slide",
                object_id="slide-race",
            ),
        )
        [recorded] = [
            e for e in _events(factory) if e.object_id == "slide-race"
        ]
        assert (recorded.graph_release_id, recorded.graph_version) == (r2_id, 2)
        assert recorded.actor_session_id == actor.id
        assert recorded.root_session_id == owner.id


@pytest.mark.parametrize("creator", ["explicit-root", "contributor", "duplicate"])
def test_creation_first_holds_r1_until_the_creator_commits(postgres_engine, creator):
    """Break caught: publication interleaves between row creation and pinning."""
    factory = _factory(postgres_engine)
    r1_id = _seed_owner_on_r1(factory)
    flushed, allow = threading.Event(), threading.Event()
    locked, proceed, pids = threading.Event(), threading.Event(), {}
    paused = {"done": False}

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def pause_after_insert(conn, _cursor, statement, _params, _ctx, _many):
        if (
            threading.current_thread().name == "creator"
            and statement.lstrip().startswith("INSERT INTO user_sessions")
            and not paused["done"]
        ):
            paused["done"] = True
            pids["creator"] = _backend_pid(conn)
            flushed.set()
            assert allow.wait(timeout=20), "creator was never released"

    try:
        with _creator_patches(factory) as manager, ThreadPoolExecutor(2) as pool:

            def create():
                threading.current_thread().name = "creator"
                return _create(manager, creator)

            created = pool.submit(create)
            assert flushed.wait(timeout=10), "creator did not flush its actor"
            publisher = pool.submit(_publisher, factory, r1_id, locked, proceed, pids)
            # The publisher cannot lock R1 until the creator's transaction ends,
            # so releasing the creator is what lets the publication proceed.
            allow.set()
            actor_id = created.result(timeout=20)
            assert locked.wait(timeout=20), "publisher never reached R1"
            proceed.set()
            r2_id = publisher.result(timeout=20)
    finally:
        event.remove(postgres_engine, "after_cursor_execute", pause_after_insert)

    assert r2_id != r1_id
    with factory() as db:
        actor = db.scalar(select(UserSession).where(UserSession.session_id == actor_id))
        # Creation won the race, so the actor is on R1 — the release that was
        # active when it locked, not the one that exists when we look.
        assert actor.graph_release_id == r1_id


# ---------------------------------------------------------------------------
# 3. Migration twice, the trigger, and SET NULL snapshot retention
# ---------------------------------------------------------------------------


def test_migration_is_idempotent_and_identities_survive_a_second_run(acceptance):
    """Break caught: a replayed migration re-generates or drops identities."""
    acc = acceptance
    _drive_every_writer(acc)
    factory = acc["factory"]
    engine = factory.kw["bind"]

    before = _identity_snapshot(factory, acc)
    events_before = [
        (e.id, str(e.root_session_identity), str(e.actor_session_identity))
        for e in _events(factory)
    ]
    assert len(events_before) == 8, len(events_before)

    _run_migrations(engine)
    _run_migrations(engine)

    assert _identity_snapshot(factory, acc) == before
    assert [
        (e.id, str(e.root_session_identity), str(e.actor_session_identity))
        for e in _events(factory)
    ] == events_before

    # The columns the migration is responsible for are still exactly right after
    # being migrated three times in total (fixture + two here).
    inspector = inspect(engine)
    for table in ("user_sessions", "session_slide_decks"):
        column = next(
            c for c in inspector.get_columns(table) if c["name"] == "collaboration_identity"
        )
        assert column["nullable"] is False
        assert column["default"] is not None
    fks = {
        tuple(fk["constrained_columns"]): fk
        for fk in inspector.get_foreign_keys("shared_deck_mutation_event")
    }
    for column in (("root_session_id",), ("root_deck_id",), ("actor_session_id",)):
        assert fks[column]["options"]["ondelete"] == "SET NULL"


def _identity_snapshot(factory, acc):
    with factory() as db:
        return {
            "owner": str(
                db.scalar(
                    select(UserSession.collaboration_identity).where(
                        UserSession.id == acc["owner_pk"]
                    )
                )
            ),
            "contributor": str(
                db.scalar(
                    select(UserSession.collaboration_identity).where(
                        UserSession.id == acc["contributor_pk"]
                    )
                )
            ),
            "legacy": str(
                db.scalar(
                    select(UserSession.collaboration_identity).where(
                        UserSession.id == acc["legacy_pk"]
                    )
                )
            ),
            "deck": str(
                db.scalar(
                    select(SessionSlideDeck.collaboration_identity).where(
                        SessionSlideDeck.id == acc["deck_pk"]
                    )
                )
            ),
        }


def test_the_append_only_trigger_rejects_every_update_and_delete(acceptance):
    """Break caught: the evidence table is mutable, so provenance is deniable."""
    acc = acceptance
    _drive_every_writer(acc)
    engine = acc["factory"].kw["bind"]
    [event_id] = [e.id for e in _events(acc["factory"], after=acc["watermark"])][:1]

    for statement in (
        f"UPDATE shared_deck_mutation_event SET operation = 'save_deck' WHERE id = {event_id}",
        f"UPDATE shared_deck_mutation_event SET graph_version = 99 WHERE id = {event_id}",
        f"DELETE FROM shared_deck_mutation_event WHERE id = {event_id}",
    ):
        with pytest.raises(Exception) as excinfo:
            with engine.begin() as conn:
                conn.execute(text(statement))
        assert "append-only" in str(excinfo.value).lower(), statement

    # The identity columns are immutable in the other direction too: a root or
    # deck whose identity could be rewritten would let evidence be re-pointed.
    with pytest.raises(Exception) as excinfo:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE user_sessions SET collaboration_identity = gen_random_uuid() "
                    "WHERE id = :pk"
                ),
                {"pk": acc["owner_pk"]},
            )
    assert "immutable" in str(excinfo.value).lower()


def test_evidence_keeps_its_snapshots_after_actor_deck_and_root_are_deleted(acceptance):
    """Break caught: a cascade takes the evidence, or leaves a dangling FK."""
    acc = acceptance
    _drive_every_writer(acc)
    factory = acc["factory"]
    before = [
        (
            e.id,
            str(e.root_session_identity),
            str(e.root_deck_identity),
            str(e.actor_session_identity),
            e.graph_release_id,
            e.graph_version,
            e.operation,
        )
        for e in _events(factory, after=acc["watermark"])
    ]
    assert len(before) == 6

    with factory.begin() as db:
        db.execute(
            text("DELETE FROM user_sessions WHERE id = :pk"),
            {"pk": acc["contributor_pk"]},
        )
    with factory.begin() as db:
        db.execute(
            text("DELETE FROM session_slide_decks WHERE id = :pk"),
            {"pk": acc["deck_pk"]},
        )
    with factory.begin() as db:
        db.execute(
            text("DELETE FROM user_sessions WHERE id = :pk"), {"pk": acc["owner_pk"]}
        )

    after = _events(factory, after=acc["watermark"])
    # Every row survived, its three FK columns are NULL rather than dangling, and
    # every opaque snapshot is byte-for-byte what it was.
    assert len(after) == 6
    assert [
        (e.root_session_id, e.root_deck_id, e.actor_session_id) for e in after
    ] == [(None, None, None)] * 6
    assert [
        (
            e.id,
            str(e.root_session_identity),
            str(e.root_deck_identity),
            str(e.actor_session_identity),
            e.graph_release_id,
            e.graph_version,
            e.operation,
        )
        for e in after
    ] == before

    # Grouping still works on the snapshots alone: three distinct actors remain
    # distinguishable with every FK nulled, which is the whole reason the opaque
    # columns exist rather than being derived from the FKs at read time.
    with factory() as db:
        distinct_actors = db.scalar(
            select(func.count(func.distinct(SharedDeckMutationEvent.actor_session_identity)))
        )
    assert distinct_actors == 3


# ---------------------------------------------------------------------------
# 4. The exact history boundary, over the real route
# ---------------------------------------------------------------------------


@pytest.fixture
def route_client(postgres_engine):
    """The real app over the throwaway PostgreSQL database."""
    factory = _factory(postgres_engine)
    db = factory()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as client:
        yield client, db
    app.dependency_overrides.clear()
    db.close()


def _history_url(session_id: str) -> str:
    return f"/api/sessions/{session_id}/collaboration-history"


def _as_user(client, url, *, user_name):
    ctx = PermissionContext(user_id=None, user_name=user_name, group_ids=[])
    with patch("src.api.routes.sessions.get_current_user", return_value=user_name), \
         patch("src.api.routes.sessions.get_permission_context", return_value=ctx), \
         patch("src.api.routes._authz.get_current_user", return_value=user_name), \
         patch("src.api.routes._authz.get_permission_context", return_value=ctx):
        return client.get(url)


@pytest.fixture
def routed_deck(route_client):
    """One root deck with owner-R1 and contributor-R2 evidence, over the route."""
    client, db = route_client
    r1 = _release(db, version_number=1, active=False)
    r2 = _release(db, version_number=2, active=True)
    root = UserSession(
        session_id="route-root", created_by="owner@example.com", graph_release_id=r1.id
    )
    db.add(root)
    db.flush()
    deck = SessionSlideDeck(session_id=root.id, title="Routed deck")
    db.add(deck)
    db.flush()
    contributor = UserSession(
        session_id="route-contributor",
        created_by="contributor@example.com",
        parent_session_id=root.id,
        graph_release_id=r2.id,
    )
    db.add(contributor)
    db.flush()
    from src.services.shared_deck_attribution import record_shared_deck_mutation

    for actor, release in ((root, r1), (contributor, r2)):
        record_shared_deck_mutation(
            db,
            requesting_session=actor,
            deck_owner=root,
            deck=deck,
            actor=MutationActor(actor.session_id, release.id),
            operation="update_slide",
            object_type="deck",
            object_id="slide-1",
        )
    db.commit()
    return {"client": client, "db": db, "root": root, "deck": deck,
            "contributor": contributor}


@pytest.mark.parametrize(
    ("label", "session_id", "user_name"),
    [
        ("unknown id", "no-such-session", "owner@example.com"),
        ("unauthorized real id", "route-root", "stranger@example.com"),
        ("guessed contributor id", "route-contributor-guessed", "stranger@example.com"),
        ("unauthorized contributor id", "route-contributor", "stranger@example.com"),
    ],
)
def test_every_denied_path_is_the_same_404_with_no_legacy_lookup_and_no_event_query(
    routed_deck, label, session_id, user_name
):
    """Break caught: a denied path resolves through a legacy seam or leaks existence."""
    client = routed_deck["client"]
    statements: list[str] = []
    bind = routed_deck["db"].get_bind()

    @event.listens_for(bind, "before_cursor_execute")
    def record(_conn, _cursor, statement, _params, _ctx, _many):
        if "shared_deck_mutation_event" in statement.lower():
            statements.append(statement)

    try:
        with _Tripwires() as tripwires:
            response = _as_user(client, _history_url(session_id), user_name=user_name)
            tripwires.assert_never_called()
    finally:
        event.remove(bind, "before_cursor_execute", record)

    assert response.status_code == 404, label
    # LITERAL detail, so a reworded 404 that happened to stay a 404 is still a
    # regression here: the whole point is that all four are indistinguishable.
    assert response.json() == {"detail": f"Session not found: {session_id}"}, label
    assert statements == [], f"{label} reached the event table: {statements}"


def test_the_authorized_path_also_reaches_no_legacy_lookup_seam(routed_deck):
    """Break caught: authorization is scoped but the happy path still resolves twice."""
    client = routed_deck["client"]
    with _Tripwires() as tripwires:
        response = _as_user(
            client, _history_url("route-root"), user_name="owner@example.com"
        )
        tripwires.assert_never_called()

    assert response.status_code == 200
    body = response.json()
    assert body["mixed_release_warning"] is True
    assert [g["graph_version"] for g in body["groups"]] == [2, 1]
    # Only the four safe fields, and no identity of any kind.
    assert {k for g in body["groups"] for k in g} == {
        "actor_label",
        "graph_version",
        "mutation_count",
        "last_mutation_at",
    }
    rendered = response.text
    for secret in ("route-root", "route-contributor", "owner@example.com",
                   "contributor@example.com"):
        assert secret not in rendered


def test_a_contributor_id_resolves_to_the_same_root_payload(routed_deck):
    """Break caught: a contributor id is resolved by a second, unscoped lookup."""
    client = routed_deck["client"]
    with _Tripwires() as tripwires:
        by_root = _as_user(
            client, _history_url("route-root"), user_name="owner@example.com"
        )
        by_contributor = _as_user(
            client, _history_url("route-contributor"), user_name="owner@example.com"
        )
        tripwires.assert_never_called()

    assert by_root.status_code == by_contributor.status_code == 200
    assert by_root.json() == by_contributor.json()


def test_a_deleted_root_is_the_same_404(routed_deck):
    """Break caught: a deleted root discloses that it once existed."""
    client, db = routed_deck["client"], routed_deck["db"]
    db.execute(
        text("DELETE FROM user_sessions WHERE id = :pk"),
        {"pk": routed_deck["root"].id},
    )
    db.commit()

    with _Tripwires() as tripwires:
        response = _as_user(
            client, _history_url("route-root"), user_name="owner@example.com"
        )
        tripwires.assert_never_called()

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found: route-root"}


# ---------------------------------------------------------------------------
# 5. The two final contract audits, executable
# ---------------------------------------------------------------------------

#: Every production construction of the two content tables, with its
#: classification. The plan's content-writer sweep discovers these; leaving the
#: result in a report means it is re-run by hand or not at all.
_CONTENT_CONSTRUCTORS: dict[tuple[str, str], str] = {
    # Declarations and reprs in the model module: neither writes anything.
    ("src/database/models/session.py", "class SessionSlide(Base):"): "class declaration",
    ("src/database/models/session.py", "class SessionSlideDeck(Base):"): "class declaration",
    (
        "src/database/models/session.py",
        'return f"<SessionSlide(session_id={self.session_id}, position={self.position})>"',
    ): "__repr__, not a construction",
    (
        "src/database/models/session.py",
        'return f"<SessionSlideDeck(session_id={self.session_id}, title=\'{self.title}\')>"',
    ): "__repr__, not a construction",
    # The three real writer seams, each reaching record_shared_deck_mutation.
    ("src/api/services/deck_level_writer.py", "deck = SessionSlideDeck("): "write_deck_level_columns seam",
    ("src/api/services/slide_repository.py", "deck = SessionSlideDeck("): "SlideWriter seam",
    ("src/api/services/session_manager.py", "deck = SessionSlideDeck("): "save_slide_deck monolith seam",
    ("src/api/services/session_manager.py", "row = SessionSlide("): "write_slide row upsert, behind the seam",
    # The one classified EXCLUSION, C-5: a duplicate builds a NEW private root
    # and deck, so it mutates no shared deck and emits no event.
    ("src/api/services/session_manager.py", "new_deck = SessionSlideDeck("): "duplicate_session's NEW private deck — C-5 exclusion",
}

#: Every production construction of ``UserSession``, with its classification.
_SESSION_CONSTRUCTORS: dict[tuple[str, str], str] = {
    ("src/database/models/session.py", "class UserSession(Base):"): "class declaration",
    (
        "src/database/models/session.py",
        'return f"<UserSession(session_id=\'{self.session_id}\', created_by=\'{self.created_by}\'{suffix})>"',
    ): "__repr__, not a construction",
    ("src/api/services/session_manager.py", "session = UserSession("): "create_session — capable iff graph_capable",
    ("src/api/services/session_manager.py", "contributor = UserSession("): "get_or_create_contributor_session — always capable",
    ("src/api/services/session_manager.py", "new_session = UserSession("): "duplicate_session — capable iff carried_marker",
}

#: The modules that must reach ``record_shared_deck_mutation``.
_ATTRIBUTION_WRITERS = {
    "src/api/services/deck_level_writer.py",
    "src/api/services/slide_repository.py",
    "src/api/services/session_manager.py",
}


def test_content_writer_audit_finds_no_unclassified_constructor():
    """The plan's content-writer sweep, run as a test rather than by hand."""
    discovered = _sweep_definitions("SessionSlideDeck(") | _sweep_definitions(
        "SessionSlide("
    )
    unclassified = discovered - set(_CONTENT_CONSTRUCTORS)
    assert not unclassified, (
        "New production construction of a content table, unclassified by the "
        f"#262 writer contract: {sorted(unclassified)}. Classify it in the plan's "
        "writer table and route it through record_shared_deck_mutation, or record "
        "why it is outside the shared-deck aggregate (see C-5 and C-7)."
    )
    # The inventory cannot rot in the other direction either: a classified site
    # that has disappeared means the classification describes code that is gone.
    assert not set(_CONTENT_CONSTRUCTORS) - discovered, (
        "Classified sites that no longer exist: "
        f"{sorted(set(_CONTENT_CONSTRUCTORS) - discovered)}"
    )
    # LITERAL 7, so a sweep that silently stopped discovering sites fails rather
    # than passing over a shrinking universe.
    assert len(discovered) == 9, sorted(discovered)

    # And every module holding a classified writer seam really does call the
    # attribution function.
    callers = {path for path, _line in _sweep("record_shared_deck_mutation(")}
    assert _ATTRIBUTION_WRITERS <= callers, _ATTRIBUTION_WRITERS - callers


def test_lifecycle_and_creator_audit_finds_no_unclassified_creator():
    """The plan's creator/lifecycle sweep, run as a test rather than by hand."""
    discovered = _sweep_definitions("UserSession(")
    unclassified = discovered - set(_SESSION_CONSTRUCTORS)
    assert not unclassified, (
        "New production construction of UserSession, unclassified by the #262 "
        f"creator contract: {sorted(unclassified)}. Every creator must decide "
        "graph capability explicitly and lock the active release before flush."
    )
    assert not set(_SESSION_CONSTRUCTORS) - discovered, (
        "Classified creators that no longer exist: "
        f"{sorted(set(_SESSION_CONSTRUCTORS) - discovered)}"
    )
    # LITERAL 5: three real creators — explicit, contributor, duplicate — plus the
    # class declaration and its repr. Every other creator in the plan's table
    # routes through one of the three.
    assert len(discovered) == 5, sorted(discovered)


def test_the_placeholder_and_lifecycle_seams_all_forward_a_mutation_context():
    """Break caught: a placeholder or lifecycle seam writes without provenance.

    ``_placehold_failed_position`` is the single sanctioned placeholder path, and
    its ``mutation`` parameter is REQUIRED rather than optional — a default of
    ``None`` is how an unattributed placeholder row would ship. Every call site
    must pass it, so the sweep counts sites and the signature check proves the
    parameter has no default to fall back on.
    """
    import inspect as py_inspect

    signature = py_inspect.signature(_placehold_failed_position)
    assert "mutation" in signature.parameters
    assert signature.parameters["mutation"].default is py_inspect.Parameter.empty, (
        "_placehold_failed_position.mutation must stay REQUIRED: an optional "
        "context is how a placeholder row ships with no collaboration evidence."
    )

    nodes_source = (SRC / "services" / "graph" / "nodes.py").read_text(encoding="utf-8")
    # LITERAL 4 call sites: builder, build_reviewer, fix_reviewer and the
    # foreman's stall path. A fifth fanned failure route must be classified
    # rather than inherited.
    call_sites = [
        index
        for index, line in enumerate(nodes_source.splitlines())
        if "_placehold_failed_position(" in line and "def " not in line
    ]
    assert len(call_sites) == 4, call_sites
    body = nodes_source.splitlines()
    for index in call_sites:
        window = "\n".join(body[index : index + 9])
        assert re.search(r"mutation=", window), (
            f"nodes.py call site at offset {index} forwards no mutation context"
        )


def test_the_named_non_seams_stay_named(acceptance):
    """C-5, C-7 and the agent's in-memory namesake, asserted rather than asserted-to.

    Three things look like writers or creators to a sweep and are not, and each
    has been rediscovered at least once in this ticket. They are pinned here so
    the next sweep does not spend a round on them again.
    """
    acc = acceptance
    manager = acc["manager"]

    # C-5: duplicating into a NEW private root/deck is not a mutation of the
    # source shared deck, so it emits nothing.
    manager.duplicate_session(acc["owner_id"], "second-copy@example.com")
    assert _events(acc["factory"], after=acc["watermark"]) == []

    # C-7: read-time authorship repair is non-user migration state.
    with acc["factory"].begin() as db:
        deck = db.get(SessionSlideDeck, acc["deck_pk"])
        deck.deck_json = (
            '{"title":"Shared acceptance deck","slides":['
            '{"slide_id":"slide-a","html":"<div class=\\"slide\\">A</div>"}]}'
        )
        db.query(SessionSlide).filter(
            SessionSlide.session_id == acc["owner_pk"]
        ).delete()
    manager.get_slide_deck(acc["owner_id"])
    assert _events(acc["factory"], after=acc["watermark"]) == []

    # The name collision: src/services/agent.py defines its OWN create_session,
    # which populates an in-memory dict and creates no row, no pin and no deck.
    # It has no production caller. It is not a creator seam, and a sweep for
    # `create_session(` will keep finding it.
    from src.services import agent as agent_module

    source = Path(agent_module.__file__).read_text(encoding="utf-8")
    assert "def create_session(self) -> dict[str, Any]:" in source
    assert "UserSession(" not in source, (
        "src/services/agent.py now constructs a UserSession, so its create_session "
        "IS a creator seam and must be classified in the #262 creator contract."
    )
