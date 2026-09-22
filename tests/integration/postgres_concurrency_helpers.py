"""Shared helpers for Postgres concurrency tests.

Extracted from ``test_claim_exclusivity_postgres.py`` so that
``test_layer4_multi_worker.py`` can import them without creating a
cross-module dependency that silently breaks on refactor.

NOT fixtures: none of these are decorated with ``@pytest.fixture``.
They are pure utilities for building Postgres concurrency harnesses —
gate objects, thread-aware DB session replacements, test-data seeders,
and a lock-waiter observer.  Keeping them here rather than in
``conftest.py`` avoids bloating the fixture file with non-fixture code.

``test_claim_exclusivity_postgres.py`` re-exports everything it used to
define, so call sites outside this module see no change.
"""
from __future__ import annotations

import contextlib
import threading
import time
from datetime import timedelta
from typing import Dict, Optional

from sqlalchemy import text

from src.database.models.session import SessionSlideDeck, UserSession

#: How long a helper will wait for a gate or a lock to appear before declaring
#: the test inconclusive.  Generous: a slow CI runner must not turn "we could
#: not observe the overlap" into a false negative, and the failure text says
#: which.
_WAIT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Gating one claimer's transaction so the others provably overlap it
# ---------------------------------------------------------------------------


class _ClaimGate:
    """Holds one claimer's transaction open between its UPDATE and its COMMIT.

    ``executed`` is set once ``claim_due_marker``'s body has returned — the
    UPDATE has run and the marker row's lock is HELD by an uncommitted
    transaction.  ``release`` is set by the test when it wants that transaction
    to commit.
    """

    def __init__(self) -> None:
        self.executed = threading.Event()
        self.release = threading.Event()


def _thread_aware_db(factory, gates: Dict[str, _ClaimGate]):
    """A ``get_db_session`` replacement that gates SOME threads and not others.

    ``patch`` replaces a module attribute process-wide, so a single callable
    has to serve every claimer.  It dispatches on
    ``threading.current_thread().name``: a thread named in *gates* has its
    commit deferred until the gate opens; everyone else commits normally.
    """

    @contextlib.contextmanager
    def fake_get_db_session():
        db = factory()
        gate = gates.get(threading.current_thread().name)
        try:
            yield db
            if gate is not None:
                # The UPDATE has run; the row lock is held and nothing is
                # committed.  Announce that, then wait for permission to commit.
                gate.executed.set()
                if not gate.release.wait(timeout=_WAIT_SECONDS):
                    raise AssertionError(
                        "the gated claimer was never released; the test's "
                        "sequencing broke, so no winner count here is evidence"
                    )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return fake_get_db_session


# ---------------------------------------------------------------------------
# One owner session and its deck, with a marker at a chosen age
# ---------------------------------------------------------------------------


class _Deck:
    def __init__(self, factory, session_id: str, deck_id: int, owner_pk: int):
        self._factory = factory
        self.session_id = session_id
        self.deck_id = deck_id
        self.owner_pk = owner_pk

    def set_marker(
        self,
        *,
        age_seconds: float,
        base,
        author: Optional[str] = "arc-author@example.com",
        claim_age_seconds: Optional[float] = None,
    ) -> None:
        """Write the marker *age_seconds* before *base*.

        *base* is the same instant the test passes to ``claim_due_marker``, so
        the marker's position relative to the debounce window is exact rather
        than a few microseconds either side of it.
        """
        self._exec(
            "UPDATE session_slide_decks SET spec_dirty_at = :at, "
            "spec_dirty_by = :by, spec_dirty_claimed_at = :claimed WHERE id = :id",
            {
                "at": base - timedelta(seconds=age_seconds),
                "by": author,
                "claimed": (
                    None
                    if claim_age_seconds is None
                    else base - timedelta(seconds=claim_age_seconds)
                ),
                "id": self.deck_id,
            },
        )

    def row(self) -> SessionSlideDeck:
        db = self._factory()
        try:
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.id == self.deck_id)
                .one()
            )
            db.expunge(deck)
            return deck
        finally:
            db.close()

    def _exec(self, sql: str, params: dict) -> None:
        db = self._factory()
        try:
            db.execute(text(sql), params)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _seed_owner_deck(factory, session_id: str = "pg-owner-sess-0001") -> _Deck:
    """Create a minimal owner session + slide deck and return a _Deck handle."""
    db = factory()
    try:
        owner = UserSession(session_id=session_id, created_by="owner@example.com")
        db.add(owner)
        db.flush()
        deck = SessionSlideDeck(
            session_id=owner.id,
            title="Exclusivity Deck",
            html_content="",
            scripts_content="",
            slide_count=1,
        )
        db.add(deck)
        db.commit()
        return _Deck(factory, session_id, deck.id, owner.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Observing the overlap from a third connection
# ---------------------------------------------------------------------------


def _lock_waiters(engine) -> int:
    """How many backends on THIS database are currently waiting on a lock.

    Read from a connection of its own, because the claimers' connections are
    either blocked or idle-in-transaction and cannot report on themselves.
    Scoped to ``current_database()``, which is this test's throwaway database,
    so a parallel xdist worker's backends are never counted.
    """
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' "
                "AND pid <> pg_backend_pid()"
            )
        ).scalar()


def _await_lock_waiters(engine, expected: int) -> int:
    """Block until *expected* backends are waiting on a lock; return the peak."""
    deadline = time.monotonic() + _WAIT_SECONDS
    peak = 0
    while time.monotonic() < deadline:
        seen = _lock_waiters(engine)
        peak = max(peak, seen)
        if seen >= expected:
            return peak
        time.sleep(0.02)
    return peak
