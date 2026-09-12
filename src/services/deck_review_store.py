"""Deck-level review storage — content-addressed by deck digest.

Public API
----------
:func:`compute_deck_digest`  ``(slide_htmls: list[str]) -> str``
:func:`save_deck_review`     ``(db, deck_id, digest, findings, author) -> DeckReview``
:func:`get_deck_review`      ``(db, deck_id, digest) -> dict | None``

**Plan deviation — read this before calling these functions from ws4c/d/e.**
The plan (``docs/superpowers/plans/2026-08-25-ws4b-contracts-and-schema.md``,
§B2.2) specifies ``save_deck_review(session_id, deck_id, …)`` and
``get_deck_review(session_id, deck_id)``.  Both ship differently:

* ``save_deck_review(db: Session, deck_id: int, digest: str, findings, author)``
* ``get_deck_review(db: Session, deck_id: int, digest: str) -> dict | None``

The ``session_id`` parameter is absent and ``digest`` is explicit.  Reason: a
content-addressed getter must be told which digest to look up; without it the
function would have to read the deck's slides itself, dragging ``SessionManager``
into a store that is explicitly a model-facing read with no route.  Passing both
``session_id`` and ``deck_id`` when one is derived from the other is also
contradictory.  The ruling and rationale are in
``docs/superpowers/plans/.ws4b-PLAN-CORRECTIONS.md`` §19.

Content-addressing rationale — three consequences, all simplifications
-----------------------------------------------------------------------
An SCD2 pair records *when* a review was current; every consumer needs *which
deck state it judged*, and those two things come apart the moment a user edits
and reverts.

**Restore needs no handling at all.** There is no "current" row to go stale.
When a user restores to an earlier save point, the digest of the restored
content matches the row that already exists.  The architect node asks "has
this exact content been reviewed?" and gets the answer immediately, without
any special restore path.

**The save-point cap cannot break it.** ``VERSION_LIMIT = 40`` prunes the
oldest ``SlideDeckVersion``; anything FK'd to ``slide_deck_versions`` would
orphan or cascade away the very history this table keeps.  These functions
touch ``session_slide_decks`` only — never ``slide_deck_versions``.

**A reorder correctly invalidates a deck review.** The deck digest is
order-sensitive: two decks with the same slides in different positions produce
different digests, which is intentional — a deck review judges the narrative
arc and a reorder changes it.  This is the OPPOSITE of the per-slide rule,
where a verdict travels with its slide across reorders because per-slide
verdicts judge content, not position.  Both behaviours are correct; they
differ because their grain differs.  A reader who knows only the per-slide
rule will read the order-sensitivity as a bug; it is not.

Caller note (resolving deck_id from a session_id string)
---------------------------------------------------------
The production caller (architect_node, ws4c) holds a ``session_id`` string,
not a ``deck_id`` integer.  It should resolve ``deck_id`` via::

    user_session = db.query(UserSession).filter(
        UserSession.session_id == session_id
    ).first()
    owner = session_manager._get_deck_owner_session(db, user_session)
    deck = db.query(SessionSlideDeck).filter(
        SessionSlideDeck.session_id == owner.id
    ).first()
    deck_id = deck.id

``_get_deck_owner_session`` takes a ``UserSession`` object and a ``db``
session — not a ``session_id`` string — so look the session up first.  Do
not write a second implementation of the contributor-following logic; reuse
that method.

B2.2b — Finding.slide_index stability
--------------------------------------
The ``slide_index`` field on each :class:`~src.domain.finding.Finding` is
captured at review time and serialised into ``findings_json``.
:func:`get_deck_review` reads it back by constructing ``Finding(**raw)``; it
does NOT recompute the index from the slide's current position in the deck.

Deck-level findings carry ``slide_index = -1`` (they reference the deck as a
whole, not a specific slide position), and that ``-1`` is stored and retrieved
as written.  For any slide-level findings nested inside a deck review, the
stored ``slide_index`` reflects which slide was referenced when the review was
written — preserving the reviewer's attribution across subsequent reorders.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.database.models.deck_review import DeckReview
from src.domain.finding import Finding
from src.utils.slide_hash import compute_slide_hash

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def compute_deck_digest(slide_htmls: List[str]) -> str:
    """Return a content-addressed digest for the ordered list of slide HTML strings.

    Each slide is first normalised and hashed with :func:`compute_slide_hash`
    (which lowercases, collapses whitespace runs to a single space, strips
    leading/trailing whitespace, and removes HTML comments).  The per-slide
    hashes are then joined **in order** with ``"|"`` as a separator, and the
    first 16 hex characters of the SHA-256 of that joined string are returned.

    **Order matters.** Two decks with the same slides in different positions
    produce different digests — intentional, because a deck review judges the
    narrative arc and a reorder changes the arc.

    **HTML comments are stripped** before hashing (by ``compute_slide_hash``).
    Two decks that differ only by HTML comments share the same digest.  This is
    a documented property of the normalisation, not a collision.

    **Inter-token whitespace is NOT removed.**  ``"<div>  a  </div>"`` and
    ``"<div>a</div>"`` normalise to ``"<div> a </div>"`` and ``"<div>a</div>"``
    respectively and hash *differently* (measured: ``compute_slide_hash``
    collapses runs but leaves one space between tokens).  Do not assert they
    produce the same digest.

    Args:
        slide_htmls: HTML string for each slide, in deck order.

    Returns:
        16-character hexadecimal string.
    """
    per_slide = [compute_slide_hash(html) for html in slide_htmls]
    combined = "|".join(per_slide)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def save_deck_review(
    db: Session,
    deck_id: int,
    digest: str,
    findings: List[Finding],
    author: Optional[str] = None,
) -> DeckReview:
    """Persist a deck-level review verdict, keyed by ``(deck_id, digest)``.

    If a row already exists for this ``(deck_id, digest)`` pair the existing
    row is updated in place rather than a duplicate inserted.  The unique
    constraint on ``(deck_id, deck_digest)`` guarantees at most one row per
    (deck, content state).

    Args:
        db:       Open SQLAlchemy session.  Caller is responsible for commit.
        deck_id:  Primary key of the ``session_slide_decks`` row.  This is an
                  integer PK, not a ``session_id`` string and not a
                  ``slide_deck_versions`` id.
        digest:   Value returned by :func:`compute_deck_digest` for the
                  reviewed deck state.
        findings: List of :class:`~src.domain.finding.Finding` objects produced
                  by the deck reviewer node.
        author:   Username or node identifier of the review producer.

    Returns:
        The persisted :class:`~src.database.models.deck_review.DeckReview` row
        (added/updated but not yet committed).
    """
    findings_json = json.dumps([f.model_dump() for f in findings])
    existing = (
        db.query(DeckReview)
        .filter(DeckReview.deck_id == deck_id, DeckReview.deck_digest == digest)
        .first()
    )
    if existing is not None:
        existing.findings_json = findings_json
        existing.author = author
        db.flush()
        return existing

    row = DeckReview(
        deck_id=deck_id,
        deck_digest=digest,
        findings_json=findings_json,
        author=author,
    )
    db.add(row)
    db.flush()
    return row


# NOTE — plan deviation: the plan specifies get_deck_review(session_id, deck_id).
# This ships as (db, deck_id, digest). See module docstring and
# docs/superpowers/plans/.ws4b-PLAN-CORRECTIONS.md §19 for the ruling.
def get_deck_review(
    db: Session,
    deck_id: int,
    digest: str,
) -> Optional[Dict[str, Any]]:
    """Return the stored deck review for ``(deck_id, digest)``, or ``None``.

    This is the content-addressed lookup: given the digest of the current deck
    state, return the review produced for that exact state — even if the deck
    was subsequently edited and then reverted.

    Returns a dict with:

    * ``digest``   — the deck digest (same as the input argument)
    * ``findings`` — list of :class:`~src.domain.finding.Finding` objects
                     reconstructed from the stored JSON; individual items that
                     fail validation are silently skipped
    * ``author``   — username/node that produced the review, or ``None``

    Returns ``None`` when no review exists for this ``(deck_id, digest)`` pair.

    This is a model-facing read for the architect node.  Do **not** add a
    route or a key to ``get_slide_deck``'s dict for this — the human copy of
    the verdict is a separate path (a persisted ``role="assistant"`` chat
    message written by ``deck_reviewer_node``).
    """
    row = (
        db.query(DeckReview)
        .filter(DeckReview.deck_id == deck_id, DeckReview.deck_digest == digest)
        .first()
    )
    if row is None:
        return None

    try:
        raw_list = json.loads(row.findings_json)
    except Exception:
        log.warning(
            "deck_reviews id=%s has unparseable findings_json; returning empty list",
            row.id,
        )
        raw_list = []

    findings: List[Finding] = []
    for item in raw_list:
        if isinstance(item, dict):
            try:
                findings.append(Finding(**item))
            except Exception:
                pass

    return {
        "digest": row.deck_digest,
        "findings": findings,
        "author": row.author,
    }
