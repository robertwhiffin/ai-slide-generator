"""Authorization-scoped collaboration history: predicate, projection, route, privacy.

Four concerns, each with its own section:

1. ``authorized_collaboration_root`` reproduces **all five** live CAN_VIEW checks
   (correction C-13) and is the endpoint's only entry lookup.
2. ``get_collaboration_history`` groups by the opaque ``actor_session_identity``
   plus the exact release, newest first, with response-local Contributor N labels.
3. The route returns a byte-identical 404 for every no-row/denied condition and
   touches none of the four legacy lookup seams (correction C-15).
4. The serialized payload discloses only the six permitted values.

Correction C-14 (root-resolution depth) is settled by
``TestContributorNestingDepth`` below: production cannot build a depth-2 chain,
so the single-hop ``coalesce`` join is equivalent to
``PermissionService._resolve_root_session`` for every reachable row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy import event as sa_event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — registers every model on Base.metadata
from src.core.database import Base, get_db
from src.core.permission_context import PermissionContext
from src.database.models.deck_contributor import DeckContributor
from src.database.models.graph_configuration import GraphRelease
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import (
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.services.collaboration_history import (
    AuthorizedCollaborationRoot,
    CollaborationReleaseGroup,
    authorized_collaboration_root,
    get_collaboration_history,
)
from src.services.permission_service import get_permission_service

# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------

_BASE_TIME = datetime(2026, 9, 23, 9, 0, 0)


@pytest.fixture
def db():
    """In-memory SQLite session with the full Tellr schema."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    session.info["engine"] = engine
    yield session
    session.close()
    engine.dispose()


def _release(db, *, version_number: int, active: bool = False) -> GraphRelease:
    published = _BASE_TIME - timedelta(days=30 - version_number)
    release = GraphRelease(
        version_number=version_number,
        release_note=f"collaboration history fixture release v{version_number}",
        published_by="fixture@example.com",
        published_at=published,
        effective_from=published,
        effective_to=None if active else published + timedelta(days=1),
    )
    db.add(release)
    db.flush()
    return release


def _root(db, session_id: str, *, created_by: str, global_permission=None) -> UserSession:
    root = UserSession(
        session_id=session_id,
        created_by=created_by,
        global_permission=global_permission,
    )
    db.add(root)
    db.flush()
    return root


def _deck(db, root: UserSession) -> SessionSlideDeck:
    deck = SessionSlideDeck(session_id=root.id, title=f"Deck for {root.session_id}")
    db.add(deck)
    db.flush()
    return deck


def _contributor(db, root: UserSession, session_id: str, *, created_by: str) -> UserSession:
    contributor = UserSession(
        session_id=session_id,
        created_by=created_by,
        parent_session_id=root.id,
    )
    db.add(contributor)
    db.flush()
    return contributor


def _grant(
    db,
    root: UserSession,
    *,
    identity_type: str,
    identity_id: str,
    identity_name: str,
    level: PermissionLevel,
) -> DeckContributor:
    grant = DeckContributor(
        user_session_id=root.id,
        identity_type=identity_type,
        identity_id=identity_id,
        identity_name=identity_name,
        permission_level=level.value,
    )
    db.add(grant)
    db.flush()
    return grant


def _event(
    db,
    *,
    root: UserSession,
    deck: SessionSlideDeck,
    actor: UserSession,
    release: GraphRelease | None,
    occurred_at: datetime,
    operation: str = "update_slide",
    object_type: str = "deck",
    object_id: str | None = "slide-1",
) -> SharedDeckMutationEvent:
    """Insert one evidence row directly — Task 3 owns the writer seams."""
    mutation_event = SharedDeckMutationEvent(
        root_session_id=root.id,
        root_deck_id=deck.id,
        actor_session_id=actor.id,
        root_session_identity=root.collaboration_identity,
        root_deck_identity=deck.collaboration_identity,
        actor_session_identity=actor.collaboration_identity,
        graph_release_id=None if release is None else release.id,
        graph_version=None if release is None else release.version_number,
        operation=operation,
        object_type=object_type,
        object_id=object_id,
        occurred_at=occurred_at,
    )
    db.add(mutation_event)
    db.flush()
    return mutation_event


def _ctx(*, user_id=None, user_name=None, group_ids=None) -> PermissionContext:
    return PermissionContext(
        user_id=user_id,
        user_name=user_name,
        group_ids=list(group_ids or []),
    )


@pytest.fixture
def shared_deck(db):
    """One root owned by owner@example.com, with a deck, and one contributor."""
    db.commit()
    root = _root(db, "sess-root-1", created_by="owner@example.com")
    deck = _deck(db, root)
    contributor = _contributor(db, root, "sess-contrib-1", created_by="contrib@example.com")
    db.commit()
    return {"root": root, "deck": deck, "contributor": contributor}


# ---------------------------------------------------------------------------
# 1. authorized_collaboration_root — the five live CAN_VIEW checks (C-13)
# ---------------------------------------------------------------------------


class TestFiveCanViewChecksAdmitIndependently:
    """Break caught: collapsing the identity_name fallback into the identity_id
    clause, or honouring an invalid CAN_MANAGE workspace share."""

    def test_check_1_deck_owner_admits(self, db, shared_deck):
        root, deck = shared_deck["root"], shared_deck["deck"]

        resolved = authorized_collaboration_root(
            db,
            requested_session_id="sess-root-1",
            permission_context=_ctx(user_id="owner-uid", user_name="owner@example.com"),
        )

        assert resolved == AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        )

    def test_check_2_direct_grant_by_identity_id_admits(self, db, shared_deck):
        root, deck = shared_deck["root"], shared_deck["deck"]
        _grant(
            db,
            root,
            identity_type="USER",
            identity_id="viewer-uid",
            identity_name="stored-display-name-not-the-caller",
            level=PermissionLevel.CAN_VIEW,
        )
        db.commit()

        resolved = authorized_collaboration_root(
            db,
            requested_session_id="sess-root-1",
            permission_context=_ctx(user_id="viewer-uid", user_name="viewer@example.com"),
        )

        assert resolved == AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        )

    def test_check_3_fallback_grant_by_identity_name_admits(self, db, shared_deck):
        """The grant's identity_id does NOT match the caller: only the NAME does."""
        root, deck = shared_deck["root"], shared_deck["deck"]
        _grant(
            db,
            root,
            identity_type="USER",
            identity_id="a-stale-directory-id",
            identity_name="named@example.com",
            level=PermissionLevel.CAN_VIEW,
        )
        db.commit()

        resolved = authorized_collaboration_root(
            db,
            requested_session_id="sess-root-1",
            permission_context=_ctx(
                user_id="the-callers-real-uid", user_name="named@example.com"
            ),
        )

        assert resolved == AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        )

    def test_check_4_group_grant_admits(self, db, shared_deck):
        root, deck = shared_deck["root"], shared_deck["deck"]
        _grant(
            db,
            root,
            identity_type="GROUP",
            identity_id="group-42",
            identity_name="data-team",
            level=PermissionLevel.CAN_VIEW,
        )
        db.commit()

        resolved = authorized_collaboration_root(
            db,
            requested_session_id="sess-root-1",
            permission_context=_ctx(
                user_id="stranger-uid",
                user_name="stranger@example.com",
                group_ids=["group-7", "group-42"],
            ),
        )

        assert resolved == AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        )

    @pytest.mark.parametrize("share", ["CAN_VIEW", "CAN_EDIT"])
    def test_check_5_valid_workspace_share_admits(self, db, share):
        db.commit()
        root = _root(
            db, "sess-shared", created_by="owner@example.com", global_permission=share
        )
        deck = _deck(db, root)
        db.commit()

        resolved = authorized_collaboration_root(
            db,
            requested_session_id="sess-shared",
            permission_context=_ctx(
                user_id="stranger-uid", user_name="stranger@example.com"
            ),
        )

        assert resolved == AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        )

    def test_can_manage_workspace_share_does_not_admit(self, db):
        """CAN_MANAGE is deliberately absent from VALID_DECK_GLOBAL_PERMISSIONS."""
        db.commit()
        root = _root(
            db,
            "sess-overshared",
            created_by="owner@example.com",
            global_permission="CAN_MANAGE",
        )
        _deck(db, root)
        db.commit()

        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-overshared",
                permission_context=_ctx(
                    user_id="stranger-uid", user_name="stranger@example.com"
                ),
            )
            is None
        )

    @pytest.mark.parametrize("share", ["CAN_USE", "", "can_view", "OWNER"])
    def test_other_global_permission_values_do_not_admit(self, db, share):
        db.commit()
        root = _root(
            db, "sess-junk-share", created_by="owner@example.com", global_permission=share
        )
        _deck(db, root)
        db.commit()

        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-junk-share",
                permission_context=_ctx(
                    user_id="stranger-uid", user_name="stranger@example.com"
                ),
            )
            is None
        )

    @pytest.mark.parametrize(
        "level",
        [
            PermissionLevel.CAN_VIEW,
            PermissionLevel.CAN_EDIT,
            PermissionLevel.CAN_MANAGE,
        ],
    )
    def test_every_direct_grant_level_admits(self, db, shared_deck, level):
        """CAN_VIEW, CAN_EDIT and CAN_MANAGE are all authorized to read history."""
        root, deck = shared_deck["root"], shared_deck["deck"]
        _grant(
            db,
            root,
            identity_type="USER",
            identity_id="granted-uid",
            identity_name="granted@example.com",
            level=level,
        )
        db.commit()

        assert authorized_collaboration_root(
            db,
            requested_session_id="sess-root-1",
            permission_context=_ctx(
                user_id="granted-uid", user_name="granted@example.com"
            ),
        ) == AuthorizedCollaborationRoot(root_session_id=root.id, root_deck_id=deck.id)


class TestAuthorizedCollaborationRootReturnsNone:
    """Break caught: any no-row condition leaking a root instead of None."""

    def test_unknown_session_id(self, db, shared_deck):
        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-does-not-exist",
                permission_context=_ctx(
                    user_id="owner-uid", user_name="owner@example.com"
                ),
            )
            is None
        )

    def test_unauthorized_stranger_on_a_real_root(self, db, shared_deck):
        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-root-1",
                permission_context=_ctx(
                    user_id="stranger-uid", user_name="stranger@example.com"
                ),
            )
            is None
        )

    def test_guessed_contributor_session_id(self, db, shared_deck):
        """A real contributor id guessed by someone with no grant on its root."""
        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-contrib-1",
                permission_context=_ctx(
                    user_id="stranger-uid", user_name="stranger@example.com"
                ),
            )
            is None
        )

    def test_contributor_session_creator_has_no_implicit_grant(self, db, shared_deck):
        """Creating a contributor session grants nothing on the shared deck."""
        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-contrib-1",
                permission_context=_ctx(
                    user_id="contrib-uid", user_name="contrib@example.com"
                ),
            )
            is None
        )

    def test_missing_contributor_root(self, db):
        """A contributor row whose parent id points at nothing resolves to None."""
        db.commit()
        orphan = UserSession(
            session_id="sess-orphan",
            created_by="contrib@example.com",
            parent_session_id=999_999,
        )
        db.add(orphan)
        db.commit()

        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-orphan",
                permission_context=_ctx(
                    user_id="owner-uid", user_name="owner@example.com"
                ),
            )
            is None
        )

    def test_deleted_root(self, db, shared_deck):
        """Deleting the root removes its contributors and decks; history is gone."""
        db.delete(shared_deck["root"])
        db.commit()

        for requested in ("sess-root-1", "sess-contrib-1"):
            assert (
                authorized_collaboration_root(
                    db,
                    requested_session_id=requested,
                    permission_context=_ctx(
                        user_id="owner-uid", user_name="owner@example.com"
                    ),
                )
                is None
            ), requested

    def test_root_without_a_deck(self, db):
        db.commit()
        _root(db, "sess-deckless", created_by="owner@example.com")
        db.commit()

        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-deckless",
                permission_context=_ctx(
                    user_id="owner-uid", user_name="owner@example.com"
                ),
            )
            is None
        )

    def test_absent_permission_context(self, db, shared_deck):
        assert (
            authorized_collaboration_root(
                db, requested_session_id="sess-root-1", permission_context=None
            )
            is None
        )

    def test_empty_permission_context(self, db, shared_deck):
        assert (
            authorized_collaboration_root(
                db, requested_session_id="sess-root-1", permission_context=_ctx()
            )
            is None
        )

    def test_an_empty_clause_list_denies_by_construction(self, db, shared_deck):
        """The predicate must deny even if EVERY check contributed no clause.

        Break caught: ``or_(*clauses)`` over an empty list produces an empty
        clause that SQLAlchemy drops from the WHERE entirely, so the predicate
        vanishes and the select admits every root — fail-OPEN in an
        authorization path. Today no caller can empty the list because check 5
        is unconditional, which makes that safety incidental to the ordering of
        unrelated code rather than structural. This pins the structure.

        The caller here is the deck OWNER, so the owner clause would admit them
        if the clause list were consulted at all. The list is emptied at source
        and the real scoped select is run against the real database, so the only
        thing that can produce ``None`` is the ``false()`` seed.
        """
        import src.services.collaboration_history as module

        owner = _ctx(user_id="owner-uid", user_name="owner@example.com")
        assert (
            authorized_collaboration_root(
                db, requested_session_id="sess-root-1", permission_context=owner
            )
            is not None
        ), "precondition: this caller IS admitted when the clauses are present"

        with patch.object(module, "_can_view_clauses", return_value=[]):
            assert (
                authorized_collaboration_root(
                    db, requested_session_id="sess-root-1", permission_context=owner
                )
                is None
            )

    def test_grant_on_the_contributor_row_does_not_admit(self, db, shared_deck):
        """Grants live on the root deck; a row hung off a contributor grants nothing."""
        _grant(
            db,
            shared_deck["contributor"],
            identity_type="USER",
            identity_id="sneaky-uid",
            identity_name="sneaky@example.com",
            level=PermissionLevel.CAN_MANAGE,
        )
        db.commit()

        assert (
            authorized_collaboration_root(
                db,
                requested_session_id="sess-contrib-1",
                permission_context=_ctx(
                    user_id="sneaky-uid", user_name="sneaky@example.com"
                ),
            )
            is None
        )


class TestAuthorizedCollaborationRootResolvesContributorsToTheRoot:
    def test_contributor_request_returns_the_root_and_root_deck(self, db, shared_deck):
        root, deck = shared_deck["root"], shared_deck["deck"]

        resolved = authorized_collaboration_root(
            db,
            requested_session_id="sess-contrib-1",
            permission_context=_ctx(user_id="owner-uid", user_name="owner@example.com"),
        )

        assert resolved == AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        )

    def test_scoped_join_returns_exactly_one_row(self, db, shared_deck):
        """Two contributors and two grants must not fan the root out into duplicates."""
        root, deck = shared_deck["root"], shared_deck["deck"]
        _contributor(db, root, "sess-contrib-2", created_by="second@example.com")
        _grant(
            db,
            root,
            identity_type="USER",
            identity_id="owner-uid",
            identity_name="owner@example.com",
            level=PermissionLevel.CAN_EDIT,
        )
        _grant(
            db,
            root,
            identity_type="GROUP",
            identity_id="group-42",
            identity_name="data-team",
            level=PermissionLevel.CAN_VIEW,
        )
        db.commit()

        from src.services.collaboration_history import _authorized_root_select

        rows = db.execute(
            _authorized_root_select(
                requested_session_id="sess-root-1",
                permission_context=_ctx(
                    user_id="owner-uid",
                    user_name="owner@example.com",
                    group_ids=["group-42"],
                ),
            )
        ).all()

        assert rows == [(root.id, deck.id)]


class TestPredicateMatchesTheLivePermissionService:
    """Differential proof that the SQL predicate and get_deck_permission agree.

    Break caught: any of the five checks diverging in either direction — a
    name-granted user denied history the rest of the app grants, or an invalid
    workspace share honoured.
    """

    _STRANGER = _ctx(user_id="s", user_name="s@example.com")
    _CASES = [
        ("owner", None, None, None,
         _ctx(user_id="o", user_name="owner@example.com")),
        ("id-grant", "USER", "viewer-uid", None,
         _ctx(user_id="viewer-uid", user_name="v@example.com")),
        ("name-grant", "USER", "stale-id", None,
         _ctx(user_id="real-uid", user_name="named@example.com")),
        ("group-grant", "GROUP", "group-42", None,
         _ctx(user_id="s", user_name="s@example.com", group_ids=["group-42"])),
        ("share-view", None, None, "CAN_VIEW", _STRANGER),
        ("share-edit", None, None, "CAN_EDIT", _STRANGER),
        ("share-manage", None, None, "CAN_MANAGE", _STRANGER),
        ("share-junk", None, None, "CAN_USE", _STRANGER),
        ("stranger", None, None, None, _STRANGER),
        ("wrong-group", "GROUP", "group-42", None,
         _ctx(user_id="s", user_name="s@example.com", group_ids=["group-9"])),
        ("wrong-id", "USER", "viewer-uid", None,
         _ctx(user_id="other-uid", user_name="other@example.com")),
    ]

    @pytest.mark.parametrize(
        "case", _CASES, ids=[case[0] for case in _CASES]
    )
    @pytest.mark.parametrize("requested", ["root", "contributor"])
    def test_predicate_and_service_agree(self, db, case, requested):
        name, identity_type, identity_id, share, ctx = case
        db.commit()
        root = _root(
            db, "sess-diff-root", created_by="owner@example.com", global_permission=share
        )
        deck = _deck(db, root)
        contributor = _contributor(
            db, root, "sess-diff-contrib", created_by="contrib@example.com"
        )
        if identity_type is not None:
            _grant(
                db,
                root,
                identity_type=identity_type,
                identity_id=identity_id,
                identity_name=(
                    "named@example.com" if name == "name-grant" else "granted@example.com"
                ),
                level=PermissionLevel.CAN_VIEW,
            )
        db.commit()

        requested_id = (
            "sess-diff-root" if requested == "root" else "sess-diff-contrib"
        )
        requested_row = root if requested == "root" else contributor

        service_admits = (
            get_permission_service().get_deck_permission(
                db,
                requested_row.id,
                user_id=ctx.user_id,
                user_name=ctx.user_name,
                group_ids=ctx.group_ids,
            )
            is not None
        )
        predicate_admits = (
            authorized_collaboration_root(
                db, requested_session_id=requested_id, permission_context=ctx
            )
            is not None
        )

        assert predicate_admits == service_admits, (
            f"case {name!r} requested={requested!r}: "
            f"SQL predicate admits={predicate_admits} but "
            f"PermissionService.get_deck_permission admits={service_admits}"
        )
        if predicate_admits:
            assert authorized_collaboration_root(
                db, requested_session_id=requested_id, permission_context=ctx
            ) == AuthorizedCollaborationRoot(
                root_session_id=root.id, root_deck_id=deck.id
            )


# ---------------------------------------------------------------------------
# 2. Correction C-14 — is a depth-2 contributor chain reachable?
# ---------------------------------------------------------------------------


class TestContributorNestingDepth:
    """Settles C-14 with evidence rather than assumption.

    ``PermissionService._resolve_root_session`` walks the whole chain;
    ``SessionManager._get_deck_owner_session`` takes one hop; the plan's
    ``coalesce`` join matches the latter. These tests establish which is right by
    trying to build the depth-2 chain that would distinguish them.
    """

    def _manager_with(self, db):
        from src.api.services.session_manager import SessionManager

        manager = SessionManager()
        ctx = patch("src.api.services.session_manager.get_db_session")
        mock_ctx = ctx.start()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=db)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        return manager, ctx

    def test_depth_2_chain_is_rejected_by_an_explicit_guard(self, db):
        """The named guard: SessionManager.get_or_create_contributor_session."""
        db.commit()
        _release(db, version_number=1, active=True)
        root = _root(db, "sess-depth-root", created_by="owner@example.com")
        _deck(db, root)
        db.commit()

        manager, ctx = self._manager_with(db)
        try:
            level_1 = manager.get_or_create_contributor_session(
                parent_session_id="sess-depth-root",
                created_by="first@example.com",
            )
            assert level_1["is_contributor_session"] is True

            with pytest.raises(ValueError) as excinfo:
                manager.get_or_create_contributor_session(
                    parent_session_id=level_1["session_id"],
                    created_by="second@example.com",
                )
        finally:
            ctx.stop()

        assert str(excinfo.value) == (
            "Cannot create contributor session on another contributor session"
        )

        contributors = db.execute(
            select(UserSession.session_id).where(
                UserSession.parent_session_id.isnot(None)
            )
        ).all()
        assert [row[0] for row in contributors] == [level_1["session_id"]]

        child_ids = select(UserSession.id).where(
            UserSession.parent_session_id.isnot(None)
        )
        nested = db.execute(
            select(UserSession.session_id).where(
                UserSession.parent_session_id.in_(child_ids)
            )
        ).all()
        assert nested == []

    def test_maximum_reachable_chain_length_is_one_hop(self, db):
        """With the guard in force, single-hop coalesce == full chain walk."""
        db.commit()
        _release(db, version_number=1, active=True)
        root = _root(db, "sess-hop-root", created_by="owner@example.com")
        _deck(db, root)
        db.commit()

        manager, ctx = self._manager_with(db)
        try:
            for index, user in enumerate(("a@example.com", "b@example.com")):
                created = manager.get_or_create_contributor_session(
                    parent_session_id="sess-hop-root",
                    created_by=user,
                )
                assert created["parent_session_id"] == "sess-hop-root", index
        finally:
            ctx.stop()

        service = get_permission_service()
        for contributor in db.execute(
            select(UserSession).where(UserSession.parent_session_id.isnot(None))
        ).scalars():
            walked = service._resolve_root_session(db, contributor)
            single_hop = db.get(UserSession, contributor.parent_session_id)
            assert walked.id == single_hop.id == root.id

    def test_a_hand_forced_depth_2_chain_fails_closed(self, db):
        """A depth-2 row that only raw SQL could create must deny, never mis-resolve.

        Production cannot build this shape, so it is documented rather than
        supported: the ``root.parent_session_id IS NULL`` requirement makes the
        single-hop join return None instead of resolving a mid-chain session as
        if it were the deck owner.
        """
        db.commit()
        root = _root(db, "sess-forced-root", created_by="owner@example.com")
        deck = _deck(db, root)
        level_1 = _contributor(db, root, "sess-forced-l1", created_by="a@example.com")
        level_2 = UserSession(
            session_id="sess-forced-l2",
            created_by="b@example.com",
            parent_session_id=level_1.id,
        )
        db.add(level_2)
        db.commit()

        owner_ctx = _ctx(user_id="owner-uid", user_name="owner@example.com")

        assert authorized_collaboration_root(
            db, requested_session_id="sess-forced-l1", permission_context=owner_ctx
        ) == AuthorizedCollaborationRoot(root_session_id=root.id, root_deck_id=deck.id)
        assert (
            authorized_collaboration_root(
                db, requested_session_id="sess-forced-l2", permission_context=owner_ctx
            )
            is None
        )
        # The full-chain walker would have admitted it — recorded divergence.
        assert (
            get_permission_service()
            ._resolve_root_session(db, level_2)
            .id
            == root.id
        )


# ---------------------------------------------------------------------------
# 3. get_collaboration_history — grouping, labels, warning, legacy
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_release_history(db):
    """root x actor A x R1, root x actor B x R2, and one legacy null-release row."""
    db.commit()
    r1 = _release(db, version_number=1)
    r2 = _release(db, version_number=2, active=True)
    root = _root(db, "sess-hist-root", created_by="owner@example.com")
    deck = _deck(db, root)
    actor_a = _contributor(db, root, "sess-hist-a", created_by="a@example.com")
    actor_b = _contributor(db, root, "sess-hist-b", created_by="b@example.com")

    # Oldest: legacy evidence from the root itself, no persisted release.
    _event(db, root=root, deck=deck, actor=root, release=None,
           occurred_at=_BASE_TIME)
    # Middle: actor A on R1, twice.
    _event(db, root=root, deck=deck, actor=actor_a, release=r1,
           occurred_at=_BASE_TIME + timedelta(minutes=1))
    _event(db, root=root, deck=deck, actor=actor_a, release=r1,
           occurred_at=_BASE_TIME + timedelta(minutes=2))
    # Newest: actor B on R2.
    _event(db, root=root, deck=deck, actor=actor_b, release=r2,
           occurred_at=_BASE_TIME + timedelta(minutes=3))
    db.commit()
    return {
        "root": root,
        "deck": deck,
        "actor_a": actor_a,
        "actor_b": actor_b,
        "r1": r1,
        "r2": r2,
        "authorized": AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        ),
    }


class TestGetCollaborationHistory:
    def test_groups_newest_first_with_response_local_labels(
        self, db, mixed_release_history
    ):
        warning, legacy, groups = get_collaboration_history(
            db, root=mixed_release_history["authorized"]
        )

        assert warning is True
        assert legacy is True
        assert groups == [
            CollaborationReleaseGroup(
                actor_label="Contributor 1",
                graph_version=2,
                mutation_count=1,
                last_mutation_at=_BASE_TIME + timedelta(minutes=3),
            ),
            CollaborationReleaseGroup(
                actor_label="Contributor 2",
                graph_version=1,
                mutation_count=2,
                last_mutation_at=_BASE_TIME + timedelta(minutes=2),
            ),
            CollaborationReleaseGroup(
                actor_label="Contributor 3",
                graph_version=None,
                mutation_count=1,
                last_mutation_at=_BASE_TIME,
            ),
        ]

    def test_two_distinct_actors_on_the_same_release_stay_separate(self, db):
        """THE grouping sabotage target: group by release alone and these collapse."""
        db.commit()
        r2 = _release(db, version_number=2, active=True)
        root = _root(db, "sess-same-release", created_by="owner@example.com")
        deck = _deck(db, root)
        actor_a = _contributor(db, root, "sess-sr-a", created_by="a@example.com")
        actor_b = _contributor(db, root, "sess-sr-b", created_by="b@example.com")
        _event(db, root=root, deck=deck, actor=actor_a, release=r2,
               occurred_at=_BASE_TIME + timedelta(minutes=1))
        _event(db, root=root, deck=deck, actor=actor_b, release=r2,
               occurred_at=_BASE_TIME + timedelta(minutes=2))
        db.commit()

        warning, legacy, groups = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=root.id, root_deck_id=deck.id
            ),
        )

        assert warning is False
        assert legacy is False
        assert groups == [
            CollaborationReleaseGroup(
                actor_label="Contributor 1",
                graph_version=2,
                mutation_count=1,
                last_mutation_at=_BASE_TIME + timedelta(minutes=2),
            ),
            CollaborationReleaseGroup(
                actor_label="Contributor 2",
                graph_version=2,
                mutation_count=1,
                last_mutation_at=_BASE_TIME + timedelta(minutes=1),
            ),
        ]

    def test_one_actor_across_two_releases_keeps_one_label(self, db):
        db.commit()
        r1 = _release(db, version_number=1)
        r2 = _release(db, version_number=2, active=True)
        root = _root(db, "sess-one-actor", created_by="owner@example.com")
        deck = _deck(db, root)
        actor = _contributor(db, root, "sess-oa-a", created_by="a@example.com")
        _event(db, root=root, deck=deck, actor=actor, release=r1,
               occurred_at=_BASE_TIME + timedelta(minutes=1))
        _event(db, root=root, deck=deck, actor=actor, release=r2,
               occurred_at=_BASE_TIME + timedelta(minutes=2))
        db.commit()

        warning, legacy, groups = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=root.id, root_deck_id=deck.id
            ),
        )

        assert warning is True
        assert legacy is False
        assert groups == [
            CollaborationReleaseGroup(
                actor_label="Contributor 1",
                graph_version=2,
                mutation_count=1,
                last_mutation_at=_BASE_TIME + timedelta(minutes=2),
            ),
            CollaborationReleaseGroup(
                actor_label="Contributor 1",
                graph_version=1,
                mutation_count=1,
                last_mutation_at=_BASE_TIME + timedelta(minutes=1),
            ),
        ]

    def test_single_release_raises_no_warning(self, db, mixed_release_history):
        db.query(SharedDeckMutationEvent).filter(
            SharedDeckMutationEvent.graph_version == 1
        ).delete(synchronize_session=False)
        db.query(SharedDeckMutationEvent).filter(
            SharedDeckMutationEvent.graph_version.is_(None)
        ).delete(synchronize_session=False)
        db.commit()

        warning, legacy, groups = get_collaboration_history(
            db, root=mixed_release_history["authorized"]
        )

        assert warning is False
        assert legacy is False
        assert [group.graph_version for group in groups] == [2]

    def test_legacy_alone_raises_no_two_version_warning(self, db):
        db.commit()
        root = _root(db, "sess-legacy-only", created_by="owner@example.com")
        deck = _deck(db, root)
        actor_a = _contributor(db, root, "sess-lo-a", created_by="a@example.com")
        actor_b = _contributor(db, root, "sess-lo-b", created_by="b@example.com")
        _event(db, root=root, deck=deck, actor=actor_a, release=None,
               occurred_at=_BASE_TIME + timedelta(minutes=1))
        _event(db, root=root, deck=deck, actor=actor_b, release=None,
               occurred_at=_BASE_TIME + timedelta(minutes=2))
        db.commit()

        warning, legacy, groups = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=root.id, root_deck_id=deck.id
            ),
        )

        assert warning is False
        assert legacy is True
        assert [group.graph_version for group in groups] == [None, None]

    def test_one_release_plus_legacy_raises_no_warning(self, db):
        """Legacy is counted separately: one real version + legacy is not 'two'."""
        db.commit()
        r2 = _release(db, version_number=2, active=True)
        root = _root(db, "sess-one-plus-legacy", created_by="owner@example.com")
        deck = _deck(db, root)
        actor = _contributor(db, root, "sess-opl-a", created_by="a@example.com")
        _event(db, root=root, deck=deck, actor=actor, release=None,
               occurred_at=_BASE_TIME + timedelta(minutes=1))
        _event(db, root=root, deck=deck, actor=actor, release=r2,
               occurred_at=_BASE_TIME + timedelta(minutes=2))
        db.commit()

        warning, legacy, groups = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=root.id, root_deck_id=deck.id
            ),
        )

        assert warning is False
        assert legacy is True
        assert [group.graph_version for group in groups] == [2, None]

    def test_empty_history(self, db, shared_deck):
        warning, legacy, groups = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=shared_deck["root"].id,
                root_deck_id=shared_deck["deck"].id,
            ),
        )

        assert (warning, legacy, groups) == (False, False, [])

    def test_query_is_root_deck_constrained(self, db, mixed_release_history):
        """A second root's evidence must never appear in the first root's history."""
        other_root = _root(db, "sess-other-root", created_by="other@example.com")
        other_deck = _deck(db, other_root)
        other_release = _release(db, version_number=9)
        for minute in (10, 11, 12):
            _event(db, root=other_root, deck=other_deck, actor=other_root,
                   release=other_release,
                   occurred_at=_BASE_TIME + timedelta(minutes=minute))
        db.commit()

        _, _, groups = get_collaboration_history(
            db, root=mixed_release_history["authorized"]
        )

        assert [group.graph_version for group in groups] == [2, 1, None]
        assert 9 not in [group.graph_version for group in groups]

    def test_mismatched_root_and_deck_ids_return_nothing(self, db, mixed_release_history):
        """Both dataclass fields constrain the query, so a mismatch yields nothing."""
        other_root = _root(db, "sess-mismatch", created_by="other@example.com")
        db.commit()

        warning, legacy, groups = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=other_root.id,
                root_deck_id=mixed_release_history["deck"].id,
            ),
        )

        assert (warning, legacy, groups) == (False, False, [])

    def test_exactly_one_grouped_statement_no_n_plus_1(self, db, mixed_release_history):
        engine = db.info["engine"]
        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa_event.listen(engine, "before_cursor_execute", _record)
        try:
            get_collaboration_history(db, root=mixed_release_history["authorized"])
        finally:
            sa_event.remove(engine, "before_cursor_execute", _record)

        assert len(statements) == 1, statements
        assert statements[0].lstrip().upper().startswith("SELECT")
        assert "GROUP BY" in statements[0].upper()

    def test_grouping_survives_all_three_fk_columns_being_nulled(
        self, db, mixed_release_history
    ):
        """Renamed from ...survives_actor_and_deck_row_deletion, which overclaimed.

        This test nulls the FK columns directly; it does NOT delete anything and
        therefore proves nothing about a cascade. The rename is the honest fix
        rather than converting it to a real delete, because this fixture's
        in-memory SQLite reports ``PRAGMA foreign_keys = 0`` — FK constraints are
        not enforced at all, so a real ``DELETE`` here would leave a DANGLING
        ``actor_session_id`` pointing at a removed row instead of firing
        ``ON DELETE SET NULL``. That would be a more misleading test, not a
        better one.

        The real cascade is proved where foreign keys are actually enforced, in
        tests/integration/test_collaboration_history_api_postgres.py:
        ``test_evidence_survives_deleting_every_actor_session``,
        ``..._the_deck_row`` and ``..._the_root_session``.

        What this test does own is the post-cascade *state*: all three FK columns
        NULL, all three opaque identities intact, grouping and labelling
        unaffected.
        """
        db.execute(
            SharedDeckMutationEvent.__table__.update().values(
                actor_session_id=None, root_session_id=None, root_deck_id=None
            )
        )
        db.commit()

        warning, legacy, groups = get_collaboration_history(
            db, root=mixed_release_history["authorized"]
        )

        assert warning is True
        assert legacy is True
        assert [group.actor_label for group in groups] == [
            "Contributor 1",
            "Contributor 2",
            "Contributor 3",
        ]
        surviving = db.execute(
            select(SharedDeckMutationEvent.actor_session_identity)
        ).all()
        assert len({row[0] for row in surviving}) == 3

    def test_two_actors_with_null_ids_on_one_release_do_not_collapse(self, db):
        """The decisive opaque-key guard, run without needing PostgreSQL.

        Break caught: grouping on ``actor_session_id`` instead of
        ``actor_session_identity``. Two LIVE actors have distinct primary keys, so
        the substitution is invisible; and actors on DIFFERENT releases stay
        separate even under the wrong key, because the release is part of the key
        too. Only "same release, both FK columns NULL" forces a collapse — which
        is the post-cascade state this projection is designed to read.
        """
        db.commit()
        r2 = _release(db, version_number=2, active=True)
        root = _root(db, "sess-collapse", created_by="owner@example.com")
        deck = _deck(db, root)
        actor_a = _contributor(db, root, "sess-col-a", created_by="a@example.com")
        actor_b = _contributor(db, root, "sess-col-b", created_by="b@example.com")
        _event(db, root=root, deck=deck, actor=actor_a, release=r2,
               occurred_at=_BASE_TIME + timedelta(minutes=1))
        _event(db, root=root, deck=deck, actor=actor_b, release=r2,
               occurred_at=_BASE_TIME + timedelta(minutes=2))
        db.execute(
            SharedDeckMutationEvent.__table__.update().values(actor_session_id=None)
        )
        db.commit()

        rows = db.execute(
            select(
                SharedDeckMutationEvent.actor_session_id,
                SharedDeckMutationEvent.actor_session_identity,
                SharedDeckMutationEvent.graph_release_id,
            ).order_by(SharedDeckMutationEvent.id)
        ).all()
        assert [row[0] for row in rows] == [None, None]
        assert rows[0][1] != rows[1][1]
        assert rows[0][2] == rows[1][2] == r2.id

        warning, legacy, groups = get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=root.id, root_deck_id=deck.id
            ),
        )

        assert warning is False
        assert legacy is False
        assert groups == [
            CollaborationReleaseGroup(
                actor_label="Contributor 1",
                graph_version=2,
                mutation_count=1,
                last_mutation_at=_BASE_TIME + timedelta(minutes=2),
            ),
            CollaborationReleaseGroup(
                actor_label="Contributor 2",
                graph_version=2,
                mutation_count=1,
                last_mutation_at=_BASE_TIME + timedelta(minutes=1),
            ),
        ]

    def test_rejects_anything_but_an_authorized_root(self, db, mixed_release_history):
        for bad in ("sess-hist-root", 1, None, (1, 2)):
            with pytest.raises(TypeError):
                get_collaboration_history(db, root=bad)

    def test_root_is_keyword_only(self, db, mixed_release_history):
        with pytest.raises(TypeError):
            get_collaboration_history(db, mixed_release_history["authorized"])


# ---------------------------------------------------------------------------
# 4. The route — tripwires, byte-identical 404, privacy
# ---------------------------------------------------------------------------

#: The four seams correction C-15 names, at their exact import sites, plus one.
#:
#: DISCLOSURE about the first entry: ``sessions.get_session`` is a *route
#: handler*. The APIRouter captured that function object at decoration time, so
#: another handler in the same module can never reach the patched module global.
#: That tripwire is therefore inert by construction — it is kept because C-15
#: names it, not because it can fail. The teeth in this set come from
#: ``SessionManager._get_session_or_raise`` (which every realistic legacy lookup
#: reaches) and from ``SessionManager.get_session``, added here as a fifth guard;
#: both were proved to fire by the authorization sabotage recorded in the task
#: report.
_TRIPWIRES = (
    ("src.api.routes.sessions", "get_session"),
    ("src.api.services.session_manager", "SessionManager._get_session_or_raise"),
    ("src.api.services.session_manager", "SessionManager._get_deck_owner_session"),
    ("src.api.routes.deck_contributors", "_get_root_session_or_400"),
    ("src.api.services.session_manager", "SessionManager.get_session"),
)


def _history_url(session_id: str) -> str:
    return f"/api/sessions/{session_id}/collaboration-history"


@pytest.fixture
def route_client(db):
    from src.api.main import app

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class _Tripwires:
    """Patches the four C-15 seams (plus SessionManager.get_session) and counts calls."""

    def __init__(self):
        self._patchers = []
        self.mocks = {}

    def __enter__(self):
        for module, attribute in _TRIPWIRES:
            target = f"{module}.{attribute}"
            patcher = patch(target, autospec=True)
            mock = patcher.start()
            self._patchers.append(patcher)
            self.mocks[target] = mock
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self._patchers):
            patcher.stop()
        return False

    def assert_never_called(self):
        called = {
            target: mock.call_args_list
            for target, mock in self.mocks.items()
            if mock.call_count
        }
        assert called == {}, f"legacy lookup seams were reached: {called}"


def _as(client, url, *, user_name, user_id=None, group_ids=None, manager_db=None):
    """Issue one authenticated GET.

    ``manager_db`` is supplied only when the URL under test is an OLD route that
    opens its own ``get_db_session``. The collaboration-history route never needs
    it — which is itself evidence that it does not reach the SessionManager.
    """
    ctx = _ctx(user_id=user_id, user_name=user_name, group_ids=group_ids)
    with patch("src.api.routes.sessions.get_current_user", return_value=user_name), \
         patch("src.api.routes.sessions.get_permission_context", return_value=ctx), \
         patch("src.api.routes._authz.get_current_user", return_value=user_name), \
         patch("src.api.routes._authz.get_permission_context", return_value=ctx):
        if manager_db is None:
            return client.get(url)
        with patch(
            "src.api.services.session_manager.get_db_session"
        ) as manager_db_ctx, patch(
            "src.api.services.usage_events.record_deck_retrieved"
        ):
            manager_db_ctx.return_value.__enter__ = MagicMock(return_value=manager_db)
            manager_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
            return client.get(url)


class TestCollaborationHistoryRoute:
    def test_authorized_owner_gets_the_grouped_payload(
        self, db, mixed_release_history, route_client
    ):
        response = _as(
            route_client,
            _history_url("sess-hist-root"),
            user_name="owner@example.com",
            user_id="owner-uid",
        )

        assert response.status_code == 200
        assert response.json() == {
            "mixed_release_warning": True,
            "has_legacy_evidence": True,
            "groups": [
                {
                    "actor_label": "Contributor 1",
                    "graph_version": 2,
                    "mutation_count": 1,
                    "last_mutation_at": "2026-09-23T09:03:00",
                },
                {
                    "actor_label": "Contributor 2",
                    "graph_version": 1,
                    "mutation_count": 2,
                    "last_mutation_at": "2026-09-23T09:02:00",
                },
                {
                    "actor_label": "Contributor 3",
                    "graph_version": None,
                    "mutation_count": 1,
                    "last_mutation_at": "2026-09-23T09:00:00",
                },
            ],
        }

    def test_contributor_session_id_resolves_to_the_shared_root(
        self, db, mixed_release_history, route_client
    ):
        _grant(
            db,
            mixed_release_history["root"],
            identity_type="USER",
            identity_id="a-uid",
            identity_name="a@example.com",
            level=PermissionLevel.CAN_VIEW,
        )
        db.commit()

        root_response = _as(
            route_client,
            _history_url("sess-hist-root"),
            user_name="a@example.com",
            user_id="a-uid",
        )
        contributor_response = _as(
            route_client,
            _history_url("sess-hist-a"),
            user_name="a@example.com",
            user_id="a-uid",
        )

        assert root_response.status_code == 200
        assert contributor_response.status_code == 200
        assert contributor_response.content == root_response.content

    @pytest.mark.parametrize(
        "level",
        [
            PermissionLevel.CAN_VIEW,
            PermissionLevel.CAN_EDIT,
            PermissionLevel.CAN_MANAGE,
        ],
    )
    def test_every_authorized_level_reads_history(
        self, db, mixed_release_history, route_client, level
    ):
        _grant(
            db,
            mixed_release_history["root"],
            identity_type="USER",
            identity_id="granted-uid",
            identity_name="granted@example.com",
            level=level,
        )
        db.commit()

        response = _as(
            route_client,
            _history_url("sess-hist-root"),
            user_name="granted@example.com",
            user_id="granted-uid",
        )

        assert response.status_code == 200
        assert response.json()["mixed_release_warning"] is True

    def test_unauthenticated_caller_is_401(self, db, mixed_release_history, route_client):
        with patch("src.api.routes.sessions.get_current_user", return_value=None), \
             patch("src.api.routes.sessions.get_permission_context", return_value=None):
            response = route_client.get(_history_url("sess-hist-root"))

        assert response.status_code == 401
        assert response.json() == {"detail": "Authentication required"}

    @pytest.mark.parametrize(
        "requested,user_name,user_id",
        [
            ("sess-hist-root", "stranger@example.com", "stranger-uid"),
            ("sess-hist-a", "stranger@example.com", "stranger-uid"),
            ("sess-hist-a", "a@example.com", "a-uid"),
            ("sess-does-not-exist", "owner@example.com", "owner-uid"),
        ],
        ids=["unauthorized-root", "guessed-contributor", "contributor-creator", "unknown"],
    )
    def test_every_denied_condition_is_the_same_404(
        self, db, mixed_release_history, route_client, requested, user_name, user_id
    ):
        with _Tripwires() as tripwires, \
             patch(
                 "src.api.routes.sessions.get_collaboration_history", autospec=True
             ) as history:
            response = _as(
                route_client,
                _history_url(requested),
                user_name=user_name,
                user_id=user_id,
            )

            tripwires.assert_never_called()
            assert history.call_count == 0

        assert response.status_code == 404
        assert response.json() == {"detail": f"Session not found: {requested}"}

    def test_denied_404_is_byte_identical_to_the_existing_get_session_404(
        self, db, mixed_release_history, route_client
    ):
        """Privacy: an unauthorized real id and an unknown id are indistinguishable."""
        unknown = "sess-does-not-exist"

        existing_route_404 = _as(
            route_client, f"/api/sessions/{unknown}", user_name="owner@example.com",
            user_id="owner-uid", manager_db=db,
        )
        history_unknown = _as(
            route_client, _history_url(unknown), user_name="owner@example.com",
            user_id="owner-uid",
        )
        history_unauthorized = _as(
            route_client, _history_url(unknown), user_name="stranger@example.com",
            user_id="stranger-uid",
        )

        assert existing_route_404.status_code == 404
        assert existing_route_404.json() == {"detail": f"Session not found: {unknown}"}
        assert history_unknown.status_code == 404
        assert history_unknown.content == existing_route_404.content
        assert history_unauthorized.content == existing_route_404.content

    def test_unauthorized_real_id_and_unknown_id_are_indistinguishable(
        self, db, mixed_release_history, route_client
    ):
        """The same caller must not be able to tell a real id from a fake one.

        The two requests differ ONLY in the id, and the id is echoed in the
        detail, so byte-equality of whole bodies would be false by construction.
        The disclosure question is whether anything BESIDE the echoed id differs
        — status, headers, or the response shape — so that is what is compared,
        with the echoed id substituted out.
        """
        real_but_forbidden = _as(
            route_client,
            _history_url("sess-hist-root"),
            user_name="stranger@example.com",
            user_id="stranger-uid",
        )
        fabricated = _as(
            route_client,
            _history_url("sess-never-existed"),
            user_name="stranger@example.com",
            user_id="stranger-uid",
        )

        assert real_but_forbidden.status_code == 404
        assert fabricated.status_code == 404
        assert real_but_forbidden.json() == {
            "detail": "Session not found: sess-hist-root"
        }
        assert fabricated.json() == {"detail": "Session not found: sess-never-existed"}
        # Identical once the echoed id is normalised away: same body template,
        # same content type, same length modulo the id itself.
        assert real_but_forbidden.content.replace(
            b"sess-hist-root", b"<ID>"
        ) == fabricated.content.replace(b"sess-never-existed", b"<ID>")
        assert (
            real_but_forbidden.headers["content-type"]
            == fabricated.headers["content-type"]
        )

    def test_authorized_path_also_avoids_the_legacy_seams(
        self, db, mixed_release_history, route_client
    ):
        with _Tripwires() as tripwires:
            response = _as(
                route_client,
                _history_url("sess-hist-root"),
                user_name="owner@example.com",
                user_id="owner-uid",
            )
            tripwires.assert_never_called()

        assert response.status_code == 200

    def test_deleted_root_is_the_same_404(self, db, mixed_release_history, route_client):
        db.delete(mixed_release_history["root"])
        db.commit()

        response = _as(
            route_client,
            _history_url("sess-hist-root"),
            user_name="owner@example.com",
            user_id="owner-uid",
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Session not found: sess-hist-root"}


@pytest.fixture
def distinctive_history(db):
    """History whose every internal identifier is unmistakable in a substring sweep.

    Primary keys are forced into the 907xxx range and Graph Versions into the
    70s so that a leaked id cannot be confused with a label ordinal (1, 2, 3), a
    mutation count (1) or a version number (71, 72).
    """
    db.commit()
    r1 = GraphRelease(
        id=907_101,
        version_number=71,
        release_note="privacy fixture release v71",
        published_by="fixture@example.com",
        published_at=_BASE_TIME - timedelta(days=2),
        effective_from=_BASE_TIME - timedelta(days=2),
        effective_to=_BASE_TIME - timedelta(days=1),
    )
    r2 = GraphRelease(
        id=907_102,
        version_number=72,
        release_note="privacy fixture release v72",
        published_by="fixture@example.com",
        published_at=_BASE_TIME - timedelta(days=1),
        effective_from=_BASE_TIME - timedelta(days=1),
        effective_to=None,
    )
    db.add_all([r1, r2])
    root = UserSession(
        id=907_001,
        session_id="sess-privacy-root-830471",
        created_by="owner-830471@example.com",
    )
    db.add(root)
    db.flush()
    deck = SessionSlideDeck(
        id=907_004, session_id=root.id, title="Privacy fixture deck"
    )
    db.add(deck)
    actor_a = UserSession(
        id=907_002,
        session_id="sess-privacy-actor-830472",
        created_by="actor-830472@example.com",
        parent_session_id=root.id,
    )
    actor_b = UserSession(
        id=907_003,
        session_id="sess-privacy-actor-830473",
        created_by="actor-830473@example.com",
        parent_session_id=root.id,
    )
    db.add_all([actor_a, actor_b])
    db.flush()

    _event(db, root=root, deck=deck, actor=root, release=None,
           occurred_at=_BASE_TIME + timedelta(minutes=1), object_id="slide-830474")
    _event(db, root=root, deck=deck, actor=actor_a, release=r1,
           occurred_at=_BASE_TIME + timedelta(minutes=2), object_id="slide-830474")
    _event(db, root=root, deck=deck, actor=actor_b, release=r2,
           occurred_at=_BASE_TIME + timedelta(minutes=3), object_id="slide-830474")
    db.commit()
    return {
        "root": root,
        "deck": deck,
        "actor_a": actor_a,
        "actor_b": actor_b,
        "r1": r1,
        "r2": r2,
    }


class TestCollaborationHistoryPrivacy:
    """Break caught: any identifier, name, principal or content leaving the seam."""

    def test_payload_key_sets_are_exactly_the_six_permitted_values(
        self, db, mixed_release_history, route_client
    ):
        response = _as(
            route_client,
            _history_url("sess-hist-root"),
            user_name="owner@example.com",
            user_id="owner-uid",
        )
        body = response.json()

        assert sorted(body.keys()) == [
            "groups",
            "has_legacy_evidence",
            "mixed_release_warning",
        ]
        for group in body["groups"]:
            assert sorted(group.keys()) == [
                "actor_label",
                "graph_version",
                "last_mutation_at",
                "mutation_count",
            ]

    def test_no_identifier_name_or_principal_appears_in_the_response_text(
        self, db, distinctive_history, route_client
    ):
        """Every internal identifier here is unmistakable, so a leak cannot hide.

        Primary keys are seeded in the 907xxx range and Graph Versions in the
        70s, so no forbidden needle can collide with a legitimate label ordinal,
        mutation count or version number in the payload.
        """
        history = distinctive_history
        response = _as(
            route_client,
            _history_url("sess-privacy-root-830471"),
            user_name="owner-830471@example.com",
            user_id="owner-uid-830471",
        )
        text = response.text

        assert response.status_code == 200
        forbidden = [
            "sess-privacy-root-830471",
            "sess-privacy-actor-830472",
            "sess-privacy-actor-830473",
            "owner-830471@example.com",
            "actor-830472@example.com",
            "actor-830473@example.com",
            "owner-uid-830471",
            str(history["root"].collaboration_identity),
            str(history["actor_a"].collaboration_identity),
            str(history["actor_b"].collaboration_identity),
            str(history["deck"].collaboration_identity),
            str(history["root"].id),
            str(history["actor_a"].id),
            str(history["actor_b"].id),
            str(history["deck"].id),
            str(history["r1"].id),
            str(history["r2"].id),
            "update_slide",
            "slide-830474",
            "graph_release_id",
            "actor_session_id",
            "actor_session_identity",
            "root_deck_identity",
            "root_session",
            "session_id",
            "created_by",
            "active",
            "Legacy",
        ]
        leaked = [needle for needle in forbidden if needle in text]
        assert leaked == [], f"response disclosed {leaked}: {text}"

    def test_distinctive_payload_is_exactly_the_permitted_values(
        self, db, distinctive_history, route_client
    ):
        response = _as(
            route_client,
            _history_url("sess-privacy-root-830471"),
            user_name="owner-830471@example.com",
            user_id="owner-uid-830471",
        )

        assert response.json() == {
            "mixed_release_warning": True,
            "has_legacy_evidence": True,
            "groups": [
                {
                    "actor_label": "Contributor 1",
                    "graph_version": 72,
                    "mutation_count": 1,
                    "last_mutation_at": "2026-09-23T09:03:00",
                },
                {
                    "actor_label": "Contributor 2",
                    "graph_version": 71,
                    "mutation_count": 1,
                    "last_mutation_at": "2026-09-23T09:02:00",
                },
                {
                    "actor_label": "Contributor 3",
                    "graph_version": None,
                    "mutation_count": 1,
                    "last_mutation_at": "2026-09-23T09:01:00",
                },
            ],
        }

    def test_release_group_dataclass_exposes_only_four_fields(self):
        from dataclasses import fields

        assert [field.name for field in fields(CollaborationReleaseGroup)] == [
            "actor_label",
            "graph_version",
            "mutation_count",
            "last_mutation_at",
        ]
        assert [field.name for field in fields(AuthorizedCollaborationRoot)] == [
            "root_session_id",
            "root_deck_id",
        ]

    def test_interfaces_are_frozen(self):
        root = AuthorizedCollaborationRoot(root_session_id=1, root_deck_id=2)
        group = CollaborationReleaseGroup(
            actor_label="Contributor 1",
            graph_version=1,
            mutation_count=1,
            last_mutation_at=_BASE_TIME,
        )
        with pytest.raises(Exception):
            root.root_session_id = 9
        with pytest.raises(Exception):
            group.actor_label = "Contributor 9"

    def test_labels_never_carry_the_root_version(self, db, mixed_release_history):
        """Labels are Contributor N only — never the root session's graph version."""
        _, _, groups = get_collaboration_history(
            db, root=mixed_release_history["authorized"]
        )

        assert [group.actor_label for group in groups] == [
            "Contributor 1",
            "Contributor 2",
            "Contributor 3",
        ]
        for group in groups:
            assert "Graph" not in group.actor_label
            assert "Legacy" not in group.actor_label
            assert "active" not in group.actor_label.lower()


def test_uuid_import_is_used_for_identity_assertions(db, shared_deck):
    """The opaque identities really are UUIDs, so grouping cannot key on an int."""
    assert isinstance(shared_deck["root"].collaboration_identity, uuid.UUID)
    assert isinstance(shared_deck["deck"].collaboration_identity, uuid.UUID)
