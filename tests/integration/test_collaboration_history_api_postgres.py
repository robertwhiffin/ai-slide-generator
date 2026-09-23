"""Collaboration history over a real PostgreSQL database and the real route.

The unit suite proves the predicate and projection against SQLite. This module
proves the same contracts where they actually run: real PostgreSQL types
(``uuid`` collaboration identities, ``timestamp`` aggregation), the real
``_run_migrations`` schema, the real FastAPI route and the real
``PermissionService``.

Four things only a real database can settle:

1. The five CAN_VIEW checks of correction C-13 admit independently, and a
   ``CAN_MANAGE`` workspace share does not — against ``uuid``/``varchar`` column
   types and PostgreSQL's own NULL semantics for ``IN``.
2. The grouped aggregation is one statement, groups on the opaque
   ``actor_session_identity``, and orders newest-first identically to SQLite
   despite PostgreSQL's opposite ``NULLS`` default for ``DESC``.
3. Evidence survives ``ON DELETE SET NULL`` when the actor session, the root
   session and the deck rows really are deleted by the database.
4. Every denied condition returns the byte-identical 404 that
   ``GET /api/sessions/{session_id}`` returns for an unknown id, and reaches none
   of the four legacy lookup seams named in correction C-15.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.core.database import get_db
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
    authorized_collaboration_root,
    get_collaboration_history,
)
from src.services.permission_service import get_permission_service
from src.services.shared_deck_attribution import (
    MutationActor,
    record_shared_deck_mutation,
)

pytestmark = pytest.mark.postgres

_BASE_TIME = datetime(2026, 9, 23, 9, 0, 0)

#: The four seams correction C-15 requires zero calls on for every denied path,
#: at their exact import sites, plus ``SessionManager.get_session`` as a fifth
#: guard.
#:
#: DISCLOSURE: the C-15 ``sessions.get_session`` target is a *route handler*. The
#: APIRouter captured that function object at decoration time, so a module-level
#: patch of it can never be reached from another handler — that entry is inert by
#: construction and is kept only because C-15 names it. The teeth come from
#: ``SessionManager._get_session_or_raise`` and ``SessionManager.get_session``.
_TRIPWIRES = (
    "src.api.routes.sessions.get_session",
    "src.api.services.session_manager.SessionManager._get_session_or_raise",
    "src.api.services.session_manager.SessionManager._get_deck_owner_session",
    "src.api.routes.deck_contributors._get_root_session_or_400",
    "src.api.services.session_manager.SessionManager.get_session",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _factory(postgres_engine):
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)


def _release(db, *, version_number: int, active: bool) -> GraphRelease:
    published = datetime(2026, 9, version_number, tzinfo=timezone.utc)
    release = GraphRelease(
        version_number=version_number,
        release_note=f"collaboration history PostgreSQL release v{version_number}",
        published_by="fixture@example.com",
        published_at=published,
        effective_from=published,
        effective_to=None if active else published + timedelta(days=1),
    )
    db.add(release)
    db.flush()
    return release


def _root_with_deck(db, session_id, *, created_by, global_permission=None):
    root = UserSession(
        session_id=session_id,
        created_by=created_by,
        global_permission=global_permission,
    )
    db.add(root)
    db.flush()
    deck = SessionSlideDeck(session_id=root.id, title=f"Deck {session_id}")
    db.add(deck)
    db.flush()
    return root, deck


def _contributor(db, root, session_id, *, created_by, release=None):
    contributor = UserSession(
        session_id=session_id,
        created_by=created_by,
        parent_session_id=root.id,
        graph_release_id=None if release is None else release.id,
    )
    db.add(contributor)
    db.flush()
    return contributor


def _grant(db, root, *, identity_type, identity_id, identity_name, level):
    db.add(
        DeckContributor(
            user_session_id=root.id,
            identity_type=identity_type,
            identity_id=identity_id,
            identity_name=identity_name,
            permission_level=level.value,
        )
    )
    db.flush()


def _record(db, *, root, deck, actor, release, object_id="slide-1"):
    """Write evidence through Task 3's real attribution seam.

    ``occurred_at`` is whatever the writer stamped. It is deliberately NOT
    rewritten afterwards: Task 1's PostgreSQL trigger makes the table genuinely
    append-only, so an ``UPDATE`` here raises "shared deck mutation events are
    append-only". Sequential ``datetime.utcnow()`` values are strictly increasing
    at microsecond resolution, so insertion order *is* chronological order and
    every assertion below compares against the timestamps the writer actually
    produced rather than fabricated ones.
    """
    return record_shared_deck_mutation(
        db,
        requesting_session=actor,
        deck_owner=root,
        deck=deck,
        actor=MutationActor(actor.session_id, None if release is None else release.id),
        operation="update_slide",
        object_type="deck",
        object_id=object_id,
    )


def _ctx(*, user_id=None, user_name=None, group_ids=None) -> PermissionContext:
    return PermissionContext(
        user_id=user_id, user_name=user_name, group_ids=list(group_ids or [])
    )


def _history_url(session_id: str) -> str:
    return f"/api/sessions/{session_id}/collaboration-history"


class _Tripwires:
    """Patch the five lookup seams and record every call made through them."""

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


@pytest.fixture
def pg_client(postgres_engine):
    """The real app over the throwaway PostgreSQL database."""
    factory = _factory(postgres_engine)
    db = factory()

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client, db
    app.dependency_overrides.clear()
    db.close()


def _as(client, url, *, user_name, user_id=None, group_ids=None, manager_db=None):
    ctx = _ctx(user_id=user_id, user_name=user_name, group_ids=group_ids)
    with patch("src.api.routes.sessions.get_current_user", return_value=user_name), \
         patch("src.api.routes.sessions.get_permission_context", return_value=ctx), \
         patch("src.api.routes._authz.get_current_user", return_value=user_name), \
         patch("src.api.routes._authz.get_permission_context", return_value=ctx):
        if manager_db is None:
            return client.get(url)
        with patch(
            "src.api.services.session_manager.get_db_session"
        ) as manager_ctx, patch(
            "src.api.services.usage_events.record_deck_retrieved"
        ):
            manager_ctx.return_value.__enter__ = MagicMock(return_value=manager_db)
            manager_ctx.return_value.__exit__ = MagicMock(return_value=False)
            return client.get(url)


@pytest.fixture
def mixed_release_deck(pg_client):
    """root x actor A x v1, root x actor B x v2, plus one legacy null-release row."""
    client, db = pg_client
    v1 = _release(db, version_number=1, active=False)
    v2 = _release(db, version_number=2, active=True)
    root, deck = _root_with_deck(
        db, "pg-root", created_by="owner@example.com"
    )
    actor_a = _contributor(db, root, "pg-actor-a", created_by="a@example.com", release=v1)
    actor_b = _contributor(db, root, "pg-actor-b", created_by="b@example.com", release=v2)

    # Written oldest-first, so the projection must return them newest-first.
    legacy = _record(db, root=root, deck=deck, actor=root, release=None)
    _a_first = _record(db, root=root, deck=deck, actor=actor_a, release=v1)
    a_latest = _record(db, root=root, deck=deck, actor=actor_a, release=v1)
    b_only = _record(db, root=root, deck=deck, actor=actor_b, release=v2)
    db.commit()

    assert legacy.occurred_at < _a_first.occurred_at < a_latest.occurred_at < (
        b_only.occurred_at
    ), "utcnow() must be strictly increasing for the ordering assertions to mean anything"

    return {
        "client": client,
        "db": db,
        "root": root,
        "deck": deck,
        "actor_a": actor_a,
        "actor_b": actor_b,
        "v1": v1,
        "v2": v2,
        # The exact timestamps the real writer stamped, newest-group first.
        "expected_last_at": [
            b_only.occurred_at,
            a_latest.occurred_at,
            legacy.occurred_at,
        ],
    }


# ---------------------------------------------------------------------------
# 1. The five CAN_VIEW checks over real PostgreSQL types (C-13)
# ---------------------------------------------------------------------------


def test_deck_owner_admits(mixed_release_deck):
    db, root, deck = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
    )

    assert authorized_collaboration_root(
        db,
        requested_session_id="pg-root",
        permission_context=_ctx(user_id="owner-uid", user_name="owner@example.com"),
    ) == AuthorizedCollaborationRoot(root_session_id=root.id, root_deck_id=deck.id)


def test_direct_grant_by_identity_id_admits(mixed_release_deck):
    db, root, deck = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
    )
    _grant(db, root, identity_type="USER", identity_id="viewer-uid",
           identity_name="not-the-callers-name", level=PermissionLevel.CAN_VIEW)
    db.commit()

    assert authorized_collaboration_root(
        db,
        requested_session_id="pg-root",
        permission_context=_ctx(user_id="viewer-uid", user_name="viewer@example.com"),
    ) == AuthorizedCollaborationRoot(root_session_id=root.id, root_deck_id=deck.id)


def test_fallback_grant_by_identity_name_admits(mixed_release_deck):
    """C-13 check 3: the grant matches only by NAME, never by id."""
    db, root, deck = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
    )
    _grant(db, root, identity_type="USER", identity_id="a-stale-directory-id",
           identity_name="named@example.com", level=PermissionLevel.CAN_VIEW)
    db.commit()

    assert authorized_collaboration_root(
        db,
        requested_session_id="pg-root",
        permission_context=_ctx(
            user_id="the-callers-real-uid", user_name="named@example.com"
        ),
    ) == AuthorizedCollaborationRoot(root_session_id=root.id, root_deck_id=deck.id)


def test_group_grant_admits(mixed_release_deck):
    db, root, deck = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
    )
    _grant(db, root, identity_type="GROUP", identity_id="group-42",
           identity_name="data-team", level=PermissionLevel.CAN_VIEW)
    db.commit()

    assert authorized_collaboration_root(
        db,
        requested_session_id="pg-root",
        permission_context=_ctx(
            user_id="stranger-uid",
            user_name="stranger@example.com",
            group_ids=["group-7", "group-42"],
        ),
    ) == AuthorizedCollaborationRoot(root_session_id=root.id, root_deck_id=deck.id)


@pytest.mark.parametrize("share", ["CAN_VIEW", "CAN_EDIT"])
def test_valid_workspace_share_admits(pg_client, share):
    _, db = pg_client
    root, deck = _root_with_deck(
        db, f"pg-share-{share}", created_by="owner@example.com", global_permission=share
    )
    db.commit()

    assert authorized_collaboration_root(
        db,
        requested_session_id=f"pg-share-{share}",
        permission_context=_ctx(user_id="stranger-uid", user_name="stranger@example.com"),
    ) == AuthorizedCollaborationRoot(root_session_id=root.id, root_deck_id=deck.id)


def test_can_manage_workspace_share_does_not_admit(pg_client):
    """CAN_MANAGE is deliberately not in VALID_DECK_GLOBAL_PERMISSIONS."""
    _, db = pg_client
    _root_with_deck(
        db,
        "pg-overshared",
        created_by="owner@example.com",
        global_permission="CAN_MANAGE",
    )
    db.commit()

    assert (
        authorized_collaboration_root(
            db,
            requested_session_id="pg-overshared",
            permission_context=_ctx(
                user_id="stranger-uid", user_name="stranger@example.com"
            ),
        )
        is None
    )


def test_predicate_agrees_with_the_live_permission_service(mixed_release_deck):
    """Differential proof over real PostgreSQL, in both directions."""
    db, root = mixed_release_deck["db"], mixed_release_deck["root"]
    _grant(db, root, identity_type="USER", identity_id="stale-id",
           identity_name="named@example.com", level=PermissionLevel.CAN_VIEW)
    _grant(db, root, identity_type="GROUP", identity_id="group-42",
           identity_name="data-team", level=PermissionLevel.CAN_EDIT)
    db.commit()
    service = get_permission_service()

    cases = [
        ("owner", _ctx(user_id="o", user_name="owner@example.com")),
        ("name-grant", _ctx(user_id="real-uid", user_name="named@example.com")),
        ("group", _ctx(user_id="s", user_name="s@example.com", group_ids=["group-42"])),
        ("stranger", _ctx(user_id="s", user_name="s@example.com")),
        ("wrong-group", _ctx(user_id="s", user_name="s@example.com", group_ids=["g9"])),
    ]
    for label, ctx in cases:
        for requested, row_id in (
            ("pg-root", root.id),
            ("pg-actor-a", mixed_release_deck["actor_a"].id),
        ):
            service_admits = (
                service.get_deck_permission(
                    db,
                    row_id,
                    user_id=ctx.user_id,
                    user_name=ctx.user_name,
                    group_ids=ctx.group_ids,
                )
                is not None
            )
            predicate_admits = (
                authorized_collaboration_root(
                    db, requested_session_id=requested, permission_context=ctx
                )
                is not None
            )
            assert predicate_admits == service_admits, (
                f"{label} / {requested}: predicate={predicate_admits} "
                f"service={service_admits}"
            )


# ---------------------------------------------------------------------------
# 2. Grouping, ordering and the one-statement guarantee over PostgreSQL
# ---------------------------------------------------------------------------


def test_grouped_history_over_postgres(mixed_release_deck):
    db, root, deck = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
    )

    warning, legacy, groups = get_collaboration_history(
        db,
        root=AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        ),
    )

    expected_last_at = mixed_release_deck["expected_last_at"]
    assert warning is True
    assert legacy is True
    assert [
        (group.actor_label, group.graph_version, group.mutation_count,
         group.last_mutation_at)
        for group in groups
    ] == [
        ("Contributor 1", 2, 1, expected_last_at[0]),
        ("Contributor 2", 1, 2, expected_last_at[1]),
        ("Contributor 3", None, 1, expected_last_at[2]),
    ]


def test_two_actors_on_one_release_stay_separate_over_postgres(pg_client):
    _, db = pg_client
    v2 = _release(db, version_number=2, active=True)
    root, deck = _root_with_deck(db, "pg-same-release", created_by="owner@example.com")
    actor_a = _contributor(db, root, "pg-sr-a", created_by="a@example.com", release=v2)
    actor_b = _contributor(db, root, "pg-sr-b", created_by="b@example.com", release=v2)
    _record(db, root=root, deck=deck, actor=actor_a, release=v2)
    _record(db, root=root, deck=deck, actor=actor_b, release=v2)
    db.commit()

    warning, legacy, groups = get_collaboration_history(
        db,
        root=AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        ),
    )

    assert warning is False
    assert legacy is False
    assert [(group.actor_label, group.graph_version, group.mutation_count)
            for group in groups] == [
        ("Contributor 1", 2, 1),
        ("Contributor 2", 2, 1),
    ]


def test_history_is_one_grouped_statement_over_postgres(mixed_release_deck):
    from sqlalchemy import event as sa_event

    db, root, deck = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
    )
    engine = db.get_bind()
    statements: list[str] = []

    def _record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", _record_statement)
    try:
        get_collaboration_history(
            db,
            root=AuthorizedCollaborationRoot(
                root_session_id=root.id, root_deck_id=deck.id
            ),
        )
    finally:
        sa_event.remove(engine, "before_cursor_execute", _record_statement)

    assert len(statements) == 1, statements
    assert "GROUP BY" in statements[0].upper()


def test_history_is_root_deck_constrained_over_postgres(mixed_release_deck):
    db, root, deck = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
    )
    other_release = _release(db, version_number=9, active=False)
    other_root, other_deck = _root_with_deck(
        db, "pg-other-root", created_by="other@example.com"
    )
    other_root.graph_release_id = other_release.id
    db.flush()
    for _ in range(2):
        _record(db, root=other_root, deck=other_deck, actor=other_root,
                release=other_release)
    db.commit()

    _, _, groups = get_collaboration_history(
        db,
        root=AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        ),
    )

    assert [group.graph_version for group in groups] == [2, 1, None]


# ---------------------------------------------------------------------------
# 3. ON DELETE SET NULL really nulls the FKs, and evidence stays groupable
# ---------------------------------------------------------------------------


def test_evidence_survives_real_actor_deletion(mixed_release_deck):
    """Deleting the actor session nulls actor_session_id but keeps the group."""
    db, root, deck, actor_a = (
        mixed_release_deck["db"],
        mixed_release_deck["root"],
        mixed_release_deck["deck"],
        mixed_release_deck["actor_a"],
    )
    actor_a_identity = actor_a.collaboration_identity

    db.execute(
        text("DELETE FROM user_sessions WHERE id = :id"), {"id": actor_a.id}
    )
    db.commit()

    surviving = db.execute(
        select(
            SharedDeckMutationEvent.actor_session_id,
            SharedDeckMutationEvent.actor_session_identity,
        ).where(SharedDeckMutationEvent.actor_session_identity == actor_a_identity)
    ).all()
    assert len(surviving) == 2
    assert [row[0] for row in surviving] == [None, None]

    warning, legacy, groups = get_collaboration_history(
        db,
        root=AuthorizedCollaborationRoot(
            root_session_id=root.id, root_deck_id=deck.id
        ),
    )

    assert warning is True
    assert legacy is True
    assert [(group.actor_label, group.graph_version, group.mutation_count)
            for group in groups] == [
        ("Contributor 1", 2, 1),
        ("Contributor 2", 1, 2),
        ("Contributor 3", None, 1),
    ]


# ---------------------------------------------------------------------------
# 4. The route — authorized, denied, byte-identical 404, tripwires
# ---------------------------------------------------------------------------


def test_route_returns_the_grouped_payload(mixed_release_deck):
    client = mixed_release_deck["client"]
    expected_last_at = mixed_release_deck["expected_last_at"]

    response = _as(
        client, _history_url("pg-root"),
        user_name="owner@example.com", user_id="owner-uid",
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
                "last_mutation_at": expected_last_at[0].isoformat(),
            },
            {
                "actor_label": "Contributor 2",
                "graph_version": 1,
                "mutation_count": 2,
                "last_mutation_at": expected_last_at[1].isoformat(),
            },
            {
                "actor_label": "Contributor 3",
                "graph_version": None,
                "mutation_count": 1,
                "last_mutation_at": expected_last_at[2].isoformat(),
            },
        ],
    }


@pytest.mark.parametrize(
    "level",
    [PermissionLevel.CAN_VIEW, PermissionLevel.CAN_EDIT, PermissionLevel.CAN_MANAGE],
)
def test_route_admits_every_authorized_level(mixed_release_deck, level):
    client, db, root = (
        mixed_release_deck["client"],
        mixed_release_deck["db"],
        mixed_release_deck["root"],
    )
    _grant(db, root, identity_type="USER", identity_id="granted-uid",
           identity_name="granted@example.com", level=level)
    db.commit()

    response = _as(
        client, _history_url("pg-root"),
        user_name="granted@example.com", user_id="granted-uid",
    )

    assert response.status_code == 200
    assert response.json()["mixed_release_warning"] is True


def test_route_resolves_a_contributor_id_to_the_same_root_payload(mixed_release_deck):
    client, db, root = (
        mixed_release_deck["client"],
        mixed_release_deck["db"],
        mixed_release_deck["root"],
    )
    _grant(db, root, identity_type="USER", identity_id="a-uid",
           identity_name="a@example.com", level=PermissionLevel.CAN_VIEW)
    db.commit()

    root_response = _as(client, _history_url("pg-root"),
                        user_name="a@example.com", user_id="a-uid")
    contributor_response = _as(client, _history_url("pg-actor-a"),
                               user_name="a@example.com", user_id="a-uid")

    assert root_response.status_code == 200
    assert contributor_response.status_code == 200
    assert contributor_response.content == root_response.content


@pytest.mark.parametrize(
    "requested,user_name,user_id",
    [
        ("pg-root", "stranger@example.com", "stranger-uid"),
        ("pg-actor-a", "stranger@example.com", "stranger-uid"),
        ("pg-actor-a", "a@example.com", "a-uid"),
        ("pg-does-not-exist", "owner@example.com", "owner-uid"),
    ],
    ids=["unauthorized-root", "guessed-contributor", "contributor-creator", "unknown"],
)
def test_every_denied_condition_is_the_same_404_with_zero_seam_calls(
    mixed_release_deck, requested, user_name, user_id
):
    client = mixed_release_deck["client"]

    with _Tripwires() as tripwires, patch(
        "src.api.routes.sessions.get_collaboration_history", autospec=True
    ) as history:
        response = _as(client, _history_url(requested),
                       user_name=user_name, user_id=user_id)
        tripwires.assert_never_called()
        assert history.call_count == 0

    assert response.status_code == 404
    assert response.json() == {"detail": f"Session not found: {requested}"}


def test_denied_404_is_byte_identical_to_the_existing_get_session_404(
    mixed_release_deck,
):
    client, db = mixed_release_deck["client"], mixed_release_deck["db"]
    unknown = "pg-does-not-exist"

    existing = _as(client, f"/api/sessions/{unknown}",
                   user_name="owner@example.com", user_id="owner-uid",
                   manager_db=db)
    history_unknown = _as(client, _history_url(unknown),
                          user_name="owner@example.com", user_id="owner-uid")
    history_unauthorized = _as(client, _history_url("pg-root"),
                               user_name="stranger@example.com",
                               user_id="stranger-uid")

    assert existing.status_code == 404
    assert history_unknown.status_code == 404
    assert history_unknown.content == existing.content
    assert history_unauthorized.status_code == 404
    assert history_unauthorized.content == (
        b'{"detail":"Session not found: pg-root"}'
    )


def test_authorized_route_also_reaches_no_legacy_seam(mixed_release_deck):
    client = mixed_release_deck["client"]

    with _Tripwires() as tripwires:
        response = _as(client, _history_url("pg-root"),
                       user_name="owner@example.com", user_id="owner-uid")
        tripwires.assert_never_called()

    assert response.status_code == 200


def test_unauthenticated_caller_is_401(mixed_release_deck):
    client = mixed_release_deck["client"]

    with patch("src.api.routes.sessions.get_current_user", return_value=None), \
         patch("src.api.routes.sessions.get_permission_context", return_value=None):
        response = client.get(_history_url("pg-root"))

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_route_discloses_only_the_permitted_values(mixed_release_deck):
    client, history = mixed_release_deck["client"], mixed_release_deck

    response = _as(client, _history_url("pg-root"),
                   user_name="owner@example.com", user_id="owner-uid")
    body = response.json()
    text_body = response.text

    assert sorted(body.keys()) == [
        "groups", "has_legacy_evidence", "mixed_release_warning",
    ]
    for group in body["groups"]:
        assert sorted(group.keys()) == [
            "actor_label", "graph_version", "last_mutation_at", "mutation_count",
        ]
    for needle in (
        "pg-root",
        "pg-actor-a",
        "pg-actor-b",
        "owner@example.com",
        "a@example.com",
        "b@example.com",
        "owner-uid",
        str(history["root"].collaboration_identity),
        str(history["actor_a"].collaboration_identity),
        str(history["deck"].collaboration_identity),
        "update_slide",
        "slide-1",
        "graph_release_id",
        "actor_session",
        "Legacy",
        "active",
    ):
        assert needle not in text_body, f"response disclosed {needle!r}: {text_body}"


def test_deleted_root_is_the_same_404(mixed_release_deck):
    client, db, root = (
        mixed_release_deck["client"],
        mixed_release_deck["db"],
        mixed_release_deck["root"],
    )
    db.execute(text("DELETE FROM user_sessions WHERE id = :id"), {"id": root.id})
    db.commit()

    response = _as(client, _history_url("pg-root"),
                   user_name="owner@example.com", user_id="owner-uid")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found: pg-root"}
