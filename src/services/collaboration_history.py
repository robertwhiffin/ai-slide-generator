"""Authorization-scoped collaboration history for a shared deck.

Two responsibilities, deliberately split so the second cannot be reached without
the first:

``authorized_collaboration_root``
    The collaboration endpoint's **only** entry lookup. It resolves a requested
    session id to its deck-owning root and authorizes the caller in the same
    statement, returning ``None`` for every no-row condition — unknown id,
    unauthorized caller, guessed contributor id, missing root, deleted root,
    deckless root. It never calls ``get_session``,
    ``SessionManager._get_session_or_raise``,
    ``SessionManager._get_deck_owner_session`` or
    ``deck_contributors._get_root_session_or_400``, so a denied caller cannot
    learn whether the id exists.

``get_collaboration_history``
    Accepts only an ``AuthorizedCollaborationRoot`` — never a requested session
    id — so the projection is structurally unreachable without authorization.

The CAN_VIEW predicate (correction C-13)
----------------------------------------
``PermissionService.get_deck_permission`` has **five** checks, not four, and the
SQL below reproduces all five against the resolved root:

1. Deck owner — ``root.created_by == user_name``.
2. Direct USER grant matched by ``identity_id``.
3. Fallback direct USER grant matched by ``identity_name`` — the check a single
   "direct contributor" clause silently drops, which would 404 every
   name-granted user out of history while the rest of the application admits
   them.
4. GROUP grant whose ``identity_id`` is one of the caller's groups.
5. Workspace-wide share, filtered to ``VALID_DECK_GLOBAL_PERMISSIONS``
   (``{CAN_VIEW, CAN_EDIT}``) — ``CAN_MANAGE`` is deliberately **not** a valid
   workspace share, so an over-broad column value must not grant access.

The predicate is a disjunction because any single check admitting is enough for
CAN_VIEW; the live service's ``PERMISSION_PRIORITY`` maximum only matters when a
*level* is needed, and history needs none.
``tests/unit/test_collaboration_history.py::TestPredicateMatchesTheLivePermissionService``
proves the two agree in both directions across the full grant matrix.

Root resolution depth (correction C-14)
---------------------------------------
``PermissionService._resolve_root_session`` walks the whole ``parent_session_id``
chain; ``SessionManager._get_deck_owner_session`` takes exactly one hop. The
single-hop ``coalesce`` join below is correct because production cannot build a
depth-2 chain: ``SessionManager.get_or_create_contributor_session`` rejects a
contributor parent outright ("Cannot create contributor session on another
contributor session"), and that is the only production writer of a non-null
``parent_session_id``. The ``root.parent_session_id IS NULL`` requirement makes
the join **fail closed** on a hand-forced depth-2 row rather than mis-resolving a
mid-chain session as the deck owner. See
``TestContributorNestingDepth`` for the evidence.

Privacy
-------
Only ``actor_label``, ``graph_version``, ``mutation_count`` and
``last_mutation_at`` leave this module, plus the two summary booleans. No actor
session id, session name, raw collaboration UUID, internal release id, pin,
prompt, content, user id or principal.

Grouping and the SET NULL design
--------------------------------
Grouping keys on the opaque ``actor_session_identity`` — never
``actor_session_id`` — so evidence stays groupable after the ``ON DELETE SET
NULL`` columns are nulled. Two live actors have distinct primary keys, which
makes a wrong-column substitution invisible; the guard that catches it therefore
needs two actors on the SAME release with both FK columns NULL, and it lives at
``test_two_deleted_actors_on_one_release_do_not_collapse`` (PostgreSQL, real
``DELETE``) and its SQLite twin.

Scope note, stated rather than implied: the grouped query joins
``session_slide_decks`` through the deck's immutable ``collaboration_identity``,
so once the deck ROW is gone the projection can no longer reach the evidence. That
is consistent, not a gap — ``authorized_collaboration_root``'s deck join denies
first, so the endpoint 404s and the projection is never called. Retention of the
rows themselves after deletion is Task 1b's contract, covered in
``tests/integration/test_shared_deck_mutation_lifecycle_postgres.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.orm import Session, aliased

from src.core.permission_context import PermissionContext
from src.database.models.deck_contributor import DeckContributor
from src.database.models.session import (
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.services.permission_service import VALID_DECK_GLOBAL_PERMISSIONS

#: Response-local contributor label prefix. Labels are assigned per distinct
#: opaque actor identity in the response's own newest-first order, so they are
#: stable within one response and meaningless outside it.
CONTRIBUTOR_LABEL_PREFIX = "Contributor"

#: The only ``global_permission`` values that grant workspace-wide access.
#: Sorted for a stable, reviewable IN list; ``CAN_MANAGE`` is absent on purpose.
_VALID_GLOBAL_SHARE_VALUES: tuple[str, ...] = tuple(
    sorted(level.value for level in VALID_DECK_GLOBAL_PERMISSIONS)
)


@dataclass(frozen=True)
class AuthorizedCollaborationRoot:
    """Proof that the caller may read one root deck's collaboration history."""

    root_session_id: int
    root_deck_id: int


@dataclass(frozen=True)
class CollaborationReleaseGroup:
    """One opaque actor's mutations on one exact Graph Release."""

    actor_label: str
    graph_version: int | None
    mutation_count: int
    last_mutation_at: datetime


def _deck_grant_exists(root, *clauses):
    """Correlated EXISTS over the root deck's contributor grants."""
    return (
        select(DeckContributor.id)
        .where(DeckContributor.user_session_id == root.id, *clauses)
        .correlate(root)
        .exists()
    )


def _can_view_clauses(root, permission_context: PermissionContext | None) -> list:
    """The five live CAN_VIEW checks as a list of independent clauses.

    A check contributes no clause when the caller carries nothing to match it
    with, exactly as the live service skips it. Check 5 always contributes
    because it depends on the deck's own column rather than on the caller, which
    is the live behaviour of ``get_deck_permission``'s workspace-share check.

    Split out from ``_can_view_predicate`` so the empty-list case is directly
    testable: the fail-open risk lives in how the clauses are combined, and a
    test cannot pin that while the list is unreachable.
    """
    user_id = permission_context.user_id if permission_context else None
    user_name = permission_context.user_name if permission_context else None
    group_ids = list(permission_context.group_ids or []) if permission_context else []

    clauses = []

    # Check 1 — deck owner (implicit CAN_MANAGE on the root).
    if user_name:
        clauses.append(root.created_by == user_name)

    # Check 2 — direct USER grant matched by identity_id.
    if user_id:
        clauses.append(
            _deck_grant_exists(
                root,
                DeckContributor.identity_type == "USER",
                DeckContributor.identity_id == user_id,
            )
        )

    # Check 3 — fallback direct USER grant matched by identity_name.
    if user_name:
        clauses.append(
            _deck_grant_exists(
                root,
                DeckContributor.identity_type == "USER",
                DeckContributor.identity_name == user_name,
            )
        )

    # Check 4 — GROUP grant for one of the caller's groups.
    if group_ids:
        clauses.append(
            _deck_grant_exists(
                root,
                DeckContributor.identity_type == "GROUP",
                DeckContributor.identity_id.in_(group_ids),
            )
        )

    # Check 5 — workspace-wide share, CAN_VIEW/CAN_EDIT only. NULL and any
    # other value (CAN_MANAGE included) yield NULL/false rather than access.
    clauses.append(root.global_permission.in_(_VALID_GLOBAL_SHARE_VALUES))

    return clauses


def _can_view_predicate(root, permission_context: PermissionContext | None):
    """Combine the five CAN_VIEW checks, denying by construction when empty.

    ``false()`` is the seed, not decoration. ``or_()`` over an empty list
    produces an empty clause that SQLAlchemy drops from the WHERE entirely, so
    the predicate would vanish and the select would admit EVERY root — a
    fail-OPEN degradation in an authorization path. Today only check 5 being
    unconditional keeps the list non-empty, which makes that correctness
    incidental: it rests on the ordering of unrelated code rather than on the
    structure here. Seeding with ``false()`` makes an empty clause list deny by
    construction. Pinned by
    ``test_an_empty_clause_list_denies_by_construction``.
    """
    return or_(false(), *_can_view_clauses(root, permission_context))


def _authorized_root_select(
    *, requested_session_id: str, permission_context: PermissionContext | None
) -> Select:
    """The single authorization-scoped statement, exposed for direct assertion.

    Selects only ``root.id`` and ``root.slide_deck.id``. The requested session id
    and the CAN_VIEW predicate are both in the WHERE clause, so no unrestricted
    ``requested``/``root`` query exists anywhere on this path.
    """
    requested = aliased(UserSession, name="requested")
    root = aliased(UserSession, name="root")
    root_deck = aliased(SessionSlideDeck, name="root_deck")

    return (
        select(root.id, root_deck.id)
        .select_from(requested)
        .join(
            root,
            root.id == func.coalesce(requested.parent_session_id, requested.id),
        )
        .join(root_deck, root_deck.session_id == root.id)
        .where(
            requested.session_id == requested_session_id,
            root.parent_session_id.is_(None),
            _can_view_predicate(root, permission_context),
        )
    )


def authorized_collaboration_root(
    db: Session,
    *,
    requested_session_id: str,
    permission_context: PermissionContext | None,
) -> AuthorizedCollaborationRoot | None:
    """Resolve and authorize a requested session's root deck in one statement.

    Returns ``None`` — never raises and never discloses which condition failed —
    for an unknown session id, an unauthorized caller, a guessed contributor id,
    a contributor whose root is missing, a deleted root, and a root with no deck.
    """
    if not requested_session_id:
        return None

    row = db.execute(
        _authorized_root_select(
            requested_session_id=requested_session_id,
            permission_context=permission_context,
        )
    ).first()
    if row is None:
        return None
    return AuthorizedCollaborationRoot(root_session_id=row[0], root_deck_id=row[1])


def _grouped_history_select(root: AuthorizedCollaborationRoot) -> Select:
    """One grouped, root-deck-constrained aggregation — no N+1.

    Constrained through the deck's immutable ``collaboration_identity`` so the
    ``ix_shared_deck_event_root_deck_actor_release`` index serves the query and
    the filter survives the ``ON DELETE SET NULL`` FK columns being nulled. Both
    fields of ``AuthorizedCollaborationRoot`` constrain the statement, so a
    mismatched pair yields nothing rather than silently ignoring one of them.

    The ordering columns are all non-null on both SQLite and PostgreSQL, so the
    two dialects agree on the total order without relying on either one's
    NULLS FIRST/LAST default.
    """
    event = SharedDeckMutationEvent
    deck = SessionSlideDeck
    last_mutation_at = func.max(event.occurred_at)
    mutation_count = func.count()

    return (
        select(
            event.actor_session_identity,
            event.graph_version,
            mutation_count.label("mutation_count"),
            last_mutation_at.label("last_mutation_at"),
        )
        .join(deck, deck.collaboration_identity == event.root_deck_identity)
        .where(
            deck.id == root.root_deck_id,
            deck.session_id == root.root_session_id,
        )
        .group_by(
            event.actor_session_identity,
            event.graph_release_id,
            event.graph_version,
        )
        .order_by(
            last_mutation_at.desc(),
            mutation_count.desc(),
            func.coalesce(event.graph_version, -1).desc(),
            event.actor_session_identity,
        )
    )


def get_collaboration_history(
    db: Session, *, root: AuthorizedCollaborationRoot
) -> tuple[bool, bool, list[CollaborationReleaseGroup]]:
    """Project one root deck's collaboration evidence.

    Args:
        db: Database session.
        root: The authorization proof from ``authorized_collaboration_root``. A
            requested session id is rejected with ``TypeError`` so the
            projection cannot be reached without authorization.

    Returns:
        ``(mixed_release_warning, has_legacy_evidence, groups)``.

        ``mixed_release_warning`` is true only when two or more **persisted
        non-null** graph versions appear. Legacy (null-release) evidence is
        counted separately in ``has_legacy_evidence`` and never contributes to
        the two-version warning, and is never described as active.

        ``groups`` is newest first, grouped by opaque actor identity plus exact
        release, with response-local ``Contributor N`` labels assigned per
        distinct actor in that order — so one actor spanning two releases keeps
        one label, and two actors on the same release keep two.
    """
    if not isinstance(root, AuthorizedCollaborationRoot):
        raise TypeError(
            "get_collaboration_history accepts only an AuthorizedCollaborationRoot; "
            f"got {type(root).__name__}"
        )

    rows = db.execute(_grouped_history_select(root)).all()

    labels: dict[object, str] = {}
    groups: list[CollaborationReleaseGroup] = []
    for actor_identity, graph_version, mutation_count, last_mutation_at in rows:
        label = labels.get(actor_identity)
        if label is None:
            label = f"{CONTRIBUTOR_LABEL_PREFIX} {len(labels) + 1}"
            labels[actor_identity] = label
        groups.append(
            CollaborationReleaseGroup(
                actor_label=label,
                graph_version=graph_version,
                mutation_count=mutation_count,
                last_mutation_at=last_mutation_at,
            )
        )

    persisted_versions = {
        group.graph_version for group in groups if group.graph_version is not None
    }
    mixed_release_warning = len(persisted_versions) >= 2
    has_legacy_evidence = any(group.graph_version is None for group in groups)
    return mixed_release_warning, has_legacy_evidence, groups
